"""Endpoint de chat con LangGraph + streaming SSE.

POST /api/v1/hub/chat/{chatbot_id}
  Invoca el grafo LangGraph y devuelve la respuesta del agente
  en tiempo real como Server-Sent Events (text/event-stream).

Protocolo SSE:
  event: status   data: {"node": "<node_name>", "msg": "<mensaje_progreso>"}
  event: token    data: {"delta": "<fragmento>"}
  event: done     data: {"interaction_id": "<uuid>", "sources": [...],
                          "language_fallback": bool, "translation_warning": str | null,
                          "reformulada": bool}
  event: error    data: {"message": "<descripcion>"}

Deploy: edge
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import (
    get_current_user_optional,
    require_scopes_allowing_widget,
)
from server.app.core.auth import UserInfo
from server.app.core.auth.chatbot_access import VIA_WIDGET, assert_chatbot_access
from server.app.core.auth.widget_key import (
    CABECERA as CABECERA_WIDGET,
    actor_anonimo_de_widget,
    resolver_widget_key,
)
from server.app.core.auth.delegated_actor import resolve_effective_actor
from server.app.core.auth.models import UserRole
from server.app.core.auth.pat.scopes import CHAT_DEBUG
from server.app.api.deps import get_session
from server.app.core.chatbot_availability import assert_chatbot_available
from server.app.core.quotas import assert_within_quota
from server.app.core.rate_limit import ip_de, limitar_chat
from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion
from server.app.modules.agents_hub.services.embedding_space import (
    EmbeddingSpaceMismatch,
)
from server.app.modules.agents_hub.services.turno_de_chat import (
    RutaNoResuelta,
    SubagenteNoEncontrado,
    emitir_turno,
    inspeccionar,
    preparar_turno,
)

router = APIRouter(prefix="/hub/chat", tags=["hub-chat"])


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


class ChatTurn(BaseModel):
    """Un turno anterior de la conversación."""

    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=10_000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10_000)
    # RAG.10: el historial lo manda el cliente. La API es sin estado y no existe entidad
    # «conversación», así que no hay de dónde recuperarlo en el servidor. Se usa solo para
    # reescribir la consulta de búsqueda; la generación sigue recibiendo el mensaje actual.
    # Se acota a 50 turnos para que el cuerpo de la petición no sea ilimitado; el
    # reescritor solo mira los últimos.
    history: list[ChatTurn] = Field(default_factory=list, max_length=50)
    # RAG.11: ejecuta el pipeline entero y devuelve el prompt final SIN invocar al modelo.
    # Requiere sesión admin o PAT con `chat:debug`; el widget público recibe 403.
    debug_bypass: bool = False


def puede_depurar(request: Request, user: UserInfo | None) -> bool:
    """Quién puede pedir el bypass (RAG.11).

    Dos clases de principal y dos comprobaciones distintas: un PAT lleva el permiso
    explícito o no lo lleva —no lo hereda de quien lo emitió, que es el sentido de acotar
    un token de máquina—, y una sesión humana lo tiene por rol. Un `require_scopes` a secas
    no serviría: deja pasar cualquier sesión JWT, incluida la del widget público.
    """
    scopes = getattr(request.state, "pat_scopes", None)
    if scopes is not None:
        return CHAT_DEBUG in scopes
    # El widget llega con su credencial de sitio y sin sesión: no hay rol que mirar (#275).
    if user is None:
        return False
    return user.role in (UserRole.ADMIN.value, UserRole.SUPERADMIN.value)


@router.post(
    "/{chatbot_id}",
    status_code=200,
    dependencies=[Depends(require_scopes_allowing_widget("chat:test"))],
)
async def chat_stream(
    chatbot_id: uuid.UUID,
    request: ChatRequest,
    http_request: Request,
    user: UserInfo | None = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_session),
):
    """Chat con streaming SSE, o inspección del prompt final si `debug_bypass` (RAG.11)."""
    # SEC.8.5: sin sesión Y sin credencial de sitio no se sigue. Va antes de resolver el
    # chatbot a propósito: comprobarlo después convertiría el 401 en un 404 para quien no
    # está autenticado, o sea en un oráculo de qué chatbots existen.
    cabecera_widget = http_request.headers.get(CABECERA_WIDGET)
    if user is None and not cabecera_widget:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if request.debug_bypass and not puede_depurar(http_request, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "El modo de depuración expone el system prompt y la configuración "
                "resuelta del chatbot: requiere sesión de administración o un PAT con "
                f"el scope '{CHAT_DEBUG}'."
            ),
        )

    result = await session.execute(
        select(HubChatbot).where(HubChatbot.id == chatbot_id)
    )
    chatbot = result.scalar_one_or_none()
    if chatbot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chatbot {chatbot_id} not found",
        )

    # SEC.2 + SEC.2.1: quién puede conversar con este chatbot se decide en UN solo sitio.
    # Conversar no es «solo leer»: la respuesta cita el corpus, así que el chat sería la vía
    # de exfiltración más cómoda que existe —más que el propio CRUD—.
    #
    # El actor efectivo, y no el principal: cuando la peticion llega por un cliente de
    # confianza con `chat:onbehalf`, quien pregunta es la persona que la cabecera declara,
    # y es su rol y sus grupos lo que decide, no los del dueño del PAT.
    # SEC.8.5: dos vías. La credencial de sitio identifica un sitio, no a una persona, así
    # que `assert_chatbot_access` con `via=VIA_WIDGET` solo la deja pasar a un chatbot
    # `public_anon`. Antes esta ruta exigía sesión siempre, y por eso el widget acababa
    # embebiendo un JWT o un PAT completo en el HTML de la página.
    clave = await resolver_widget_key(session, cabecera_widget)
    es_widget = clave is not None and clave.chatbot_id == chatbot_id

    if es_widget:
        assert_chatbot_access(None, chatbot, via=VIA_WIDGET)
        actor = actor_anonimo_de_widget(chatbot_id)
    else:
        if user is None:
            # Traía credencial de sitio, pero no vale para este chatbot: es un 403 y no un
            # 401, porque identificarse mejor no arreglaría nada.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ACCESS_MODE_FORBIDDEN",
                    "reason": "the widget credential does not belong to this chatbot",
                },
            )
        actor = resolve_effective_actor(http_request, user)
        assert_chatbot_access(actor, chatbot, via="session")

    # SEC.4.1: ¿está abierto? Va **después** del acceso y **antes** de la cuota: contarle a
    # alguien que el plazo se cerró es contarle que el trámite existe, y eso solo se le dice
    # a quien podría usarlo.
    await assert_chatbot_available(session, chatbot)

    # SEC.4: primero el limitador —cuenta peticiones y es barato— y después la cuota, que
    # cuenta tokens y necesita ir a la BD. Las dos por actor efectivo: si se contaran por
    # credencial, un cliente de confianza que atiende a cien personas se llevaría el límite
    # y la cuota de una sola.
    # SEC.9.6 — para el widget, `actor.subject_id` es `widget:{chatbot_id}`, el MISMO para todos
    # los visitantes anónimos: un solo visitante agotaba el cupo de peticiones de todos los
    # demás. Pasando `None` el limitador cae a la IP, que es su comportamiento para el tráfico
    # sin identidad. Y `ip=` en las dos llamadas de cuota es lo que hace que
    # `anon_ip_daily_token_quota` deje de ser código muerto.
    ip_del_visitante = ip_de(http_request)
    limitar_chat(
        http_request,
        actor_id=None if es_widget else actor.subject_id,
        chatbot_id=chatbot_id,
    )
    organizacion = await session.get(HubOrganizacion, chatbot.organizacion_id)
    await assert_within_quota(
        session, actor, chatbot, organizacion, ip=ip_del_visitante if es_widget else None
    )

    try:
        turno = await preparar_turno(
            session,
            chatbot,
            mensaje=request.message,
            historial=[(t.role, t.content) for t in request.history],
            debug_bypass=request.debug_bypass,
        )
    except EmbeddingSpaceMismatch as desajuste:
        # RAG.9: parar antes que responder mal. Si el corpus está embebido con otro modelo, la
        # búsqueda devuelve fuentes de un espacio que no es el suyo.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(desajuste)
        ) from desajuste
    except RutaNoResuelta as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SubagenteNoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if request.debug_bypass:
        # JSON, no SSE: no hay nada que transmitir en trozos —no se genera texto— y quien
        # depura quiere el objeto entero de una vez. Tampoco se persiste `HubInteraction`:
        # esto es inspección, no conversación, y contarla ensuciaría las métricas de uso.
        return await inspeccionar(turno)

    return StreamingResponse(
        emitir_turno(
            turno,
            session=session,
            actor=actor,
            mensaje=request.message,
            numero_de_turno=len(request.history) + 1,
            ip=ip_del_visitante if es_widget else None,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
