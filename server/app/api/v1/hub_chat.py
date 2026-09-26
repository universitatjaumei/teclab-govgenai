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

import json
import logging
import uuid
from time import perf_counter
from typing import AsyncIterator, Literal

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
from server.app.core.llm_text import texto_de
from server.app.core.auth.models import UserRole
from server.app.core.auth.pat.scopes import CHAT_DEBUG
from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import GraphFactory
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
    GraphDeps,
)
from server.app.modules.agents_hub.agent.router_node import build_route_to_subagent_node
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.core.chatbot_availability import assert_chatbot_available
from server.app.core.quotas import assert_within_quota, contabilizar_interaccion
from server.app.core.rate_limit import ip_de, limitar_chat
from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion
from server.app.modules.agents_hub.database.operational_models import HubInteraction
from server.app.modules.agents_hub.evaluation.traza import construye_traza
from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
from server.app.modules.agents_hub.services.embedding_resolver import (
    resolve_embedding_service,
)
from server.app.modules.agents_hub.services.embedding_space import (
    EmbeddingSpaceMismatch,
    assert_embedding_space_matches,
)
from server.app.modules.agents_hub.services.model_factory import get_model
from server.app.modules.agents_hub.services.observability import create_callback_handler

router = APIRouter(prefix="/hub/chat", tags=["hub-chat"])


class _ChatbotChildrenProvider:
    def __init__(self, db_session: AsyncSession):
        self._session = db_session

    async def get_children(self, parent_id: uuid.UUID):
        result = await self._session.execute(
            select(HubChatbot).where(HubChatbot.parent_chatbot_id == parent_id)
        )
        return list(result.scalars().all())

# Nodos del CoreGraph → mensaje de progreso. RAG.2 cambió los nombres internos de los
# nodos (search_or_skip → retrieve, generate_response → generate_answer) pero NO el
# contrato SSE observable: los tres mensajes que ve el usuario son los mismos, y los nodos
# internos que no tenían mensaje (merge, log, fallback) siguen sin emitir status.
NODE_STATUS_MESSAGES: dict[str, str] = {
    "detect_language":  "Detectando idioma...",
    "retrieve":         "Buscando en la base de conocimiento...",
    "generate_answer":  "Generando respuesta...",
}

#: USR.8 — un fallo después del grafo se le dice al cliente **y** se deja en el log. Sin la
#: traza, «el chat se queda pensando» no se puede diagnosticar: el evento `error` lleva el
#: mensaje, pero no dónde pasó.
logger = logging.getLogger(__name__)

# Nodo del CoreGraph cuyo on_chain_end trae el estado final del que salen las fuentes.
_FINAL_NODES = ("generate_answer", "fallback")

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


def puede_depurar(request: Request, user: UserInfo) -> bool:
    """Quién puede pedir el bypass (RAG.11).

    Dos clases de principal y dos comprobaciones distintas: un PAT lleva el permiso
    explícito o no lo lleva —no lo hereda de quien lo emitió, que es el sentido de acotar
    un token de máquina—, y una sesión humana lo tiene por rol. Un `require_scopes` a secas
    no serviría: deja pasar cualquier sesión JWT, incluida la del widget público.
    """
    scopes = getattr(request.state, "pat_scopes", None)
    if scopes is not None:
        return CHAT_DEBUG in scopes
    return user.role in (UserRole.ADMIN.value, UserRole.SUPERADMIN.value)


#: Lo único que el cliente recibe cuando el turno falla (issue #147).
#:
#: Antes iba `str(exc)`, y el widget del chatbot es **público**: cualquiera podía provocar un
#: error y leer el mensaje de una excepción de base de datos, una ruta del contenedor o la
#: respuesta cruda del proveedor de modelo. El cliente tiene que saber que hubo un error; cuál,
#: no. El detalle va al registro, que es donde lo necesita quien lo arregla.
#:
#: Es texto fijo a propósito y no un mensaje por chatbot: éste no es el «no tengo información»
#: de UX.4 —que sí es del chatbot y va en su lengua— sino una avería del servicio. Si algún día
#: hay que traducirlo, el sitio es el cliente, que ya sabe en qué lengua está.
MENSAJE_DE_ERROR = "S'ha produït un error en processar la consulta."


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _uso_del_evento(event: dict) -> tuple[int, int]:
    """Tokens de entrada y salida que declara el proveedor, o `(0, 0)`.

    LangChain los expone en `usage_metadata` desde la versión unificada y, en modelos más
    antiguos, dentro de `response_metadata['token_usage']`. Se miran los dos sitios porque el
    proveedor se elige por configuración y no se puede saber aquí cuál responderá.
    """
    salida = (event.get("data") or {}).get("output")
    if salida is None:
        return 0, 0

    uso = getattr(salida, "usage_metadata", None)
    if isinstance(uso, dict) and (uso.get("input_tokens") or uso.get("output_tokens")):
        return int(uso.get("input_tokens") or 0), int(uso.get("output_tokens") or 0)

    metadatos = getattr(salida, "response_metadata", None) or {}
    crudo = metadatos.get("token_usage") or metadatos.get("usage") or {}
    if isinstance(crudo, dict):
        return (
            int(crudo.get("prompt_tokens") or crudo.get("input_tokens") or 0),
            int(crudo.get("completion_tokens") or crudo.get("output_tokens") or 0),
        )
    return 0, 0


def _tokens_estimados(texto: str) -> int:
    """Estimación por longitud cuando el proveedor no declara nada.

    Cuatro caracteres por token: la regla de servilleta habitual para texto latino. No
    pretende ser exacta —por eso lo que se guarda junto al número es `usage_source
    = 'estimated'`—, solo evitar que una cuota se quede a cero porque el proveedor calle.
    """
    return max(1, len(texto or "") // 4) if texto else 0


#: Cómo se llama cada lengua **en la lengua de quien lee el aviso** (VIS.5).
#:
#: Tres tablas y no una: el aviso se le muestra a quien acaba de escribir en su lengua, así que
#: decirle «catalan» en castellano —y encima sin tilde— convierte una advertencia útil en una
#: impertinencia. La lengua de la fuente se nombra dentro de la frase, luego hay que declinarla
#: en cada idioma.
# ACT.2: la clave del valenciano es `val`, la del CORPUS, y `ca` ya no aparece. La versión
# anterior estaba escrita en `ca` en las dos direcciones, así que:
#   · como lengua de la FUENTE nunca acertaba —los documentos llevan `val`— y el nombre salía con
#     el código crudo: «⚠️ La normativa citada está en val»;
#   · como lengua de la PREGUNTA tampoco, en cuanto el detector pasó a normalizar.
# Dos claves para la misma lengua es lo que estaba roto; no se duplican, se traduce en la
# frontera (`services/language_detector.py`).
_NOMBRE_DE_LA_LENGUA: dict[str, dict[str, str]] = {
    "val": {"val": "valencià", "es": "castellà", "en": "anglès", "fr": "francès"},
    "es": {"val": "valenciano", "es": "castellano", "en": "inglés", "fr": "francés"},
    "en": {"val": "Valencian", "es": "Spanish", "en": "English", "fr": "French"},
}

# Issue #17 — el aviso dice además QUÉ SE ESTÁ LEYENDO, no sólo adónde lleva el enlace.
#
# **Al corpus sólo entran originales**: no se sube ni una traducción. Así que cuando la norma que
# responde a la pregunta sólo existe en la otra lengua, lo que lee quien pregunta no es la norma:
# es una traducción que el modelo acaba de hacer, que nadie ha revisado y que no está publicada en
# ningún sitio. «La normativa citada está en castellano» no dice eso, y era todo lo que decía.
#
# Va aquí y no en el aviso permanente de `chat.json` —que ya advierte de que las respuestas no han
# pasado revisión lingüística— porque es **condicional**: un aviso que sale siempre se aprende a
# ignorar, y en las normas que sólo existen en valencià, preguntadas en valencià, no hay ninguna
# traducción de la que avisar. Afirmarlo sería falso.
_PLANTILLA_DEL_AVISO: dict[str, str] = {
    "val": (
        "⚠️ La normativa citada està en {lengua}. La resposta s'ha generat de manera "
        "automatitzada a partir de l'original, sense revisió humana de la traducció. "
        "L'enllaç porta al document original."
    ),
    "es": (
        "⚠️ La normativa citada está en {lengua}. La respuesta se ha generado de forma "
        "automatizada a partir del original, sin revisión humana de la traducción. "
        "El enlace lleva al documento original."
    ),
    "en": (
        "⚠️ The cited regulation is in {lengua}. This answer was generated automatically "
        "from the original, with no human review of the translation. "
        "The link opens the original document."
    ),
}


def _build_translation_warning(
    lengua_de_la_fuente: str | None, lengua_de_la_pregunta: str | None
) -> str | None:
    """El aviso de que la norma citada está en otra lengua (VIS.5).

    **Sale de la lengua de la FUENTE, no de la de la pregunta.** Antes decía «la pregunta se
    detectó en catalán», que no es información: quien ha escrito en valencià ya sabe en qué
    lengua escribe. Lo que necesita saber es que el enlace le lleva a un documento en castellano.

    Y **se emite en las dos direcciones**. La versión anterior devolvía `None` cuando la pregunta
    era en castellano, que es justo el caso más frecuente de este corpus —195 de 290 normas sólo
    existen en valencià—: el grafo decidía que había que avisar y el texto se descartaba después.

    Sin una de las dos lenguas no se avisa: no se puede afirmar que difieran, y un aviso falso
    sobre el idioma de una norma erosiona la confianza en los que sí son ciertos.
    """
    if not lengua_de_la_fuente or not lengua_de_la_pregunta:
        return None
    if lengua_de_la_fuente == lengua_de_la_pregunta:
        return None

    plantilla = _PLANTILLA_DEL_AVISO.get(lengua_de_la_pregunta, _PLANTILLA_DEL_AVISO["es"])
    nombres = _NOMBRE_DE_LA_LENGUA.get(lengua_de_la_pregunta, _NOMBRE_DE_LA_LENGUA["es"])
    return plantilla.format(lengua=nombres.get(lengua_de_la_fuente, lengua_de_la_fuente))


def _es_citable(source) -> bool:
    """Sólo van al done las evidencias con URL: sin URL no hay cita verificable.

    En modo selector eso descarta además las entradas de índice, que llegan sin haber
    sido leídas.
    """
    if getattr(source, "metadata", None) and source.metadata.get("index_entry"):
        return False
    return bool(getattr(source, "source_url", None) or getattr(source, "url", None))


def _source_to_dict(source) -> dict:
    """Serializa una evidencia al shape del evento done.

    RAG.2 unificó el contrato interno en EvidenceItem (source_id / source_url), pero el
    shape JSON que ve el frontend **no cambia**: document_id, title, url, score. Se acepta
    también el dialecto `Source` (document_id/url) porque los tools y las estrategias de
    `services/retrieval/` siguen hablándolo por debajo de los pipelines.
    """
    from server.app.modules.agents_hub.services.retrieval.citations import (
        etiqueta_de_autoridad,
    )

    document_id = getattr(source, "source_id", None) or getattr(source, "document_id", None)
    url = getattr(source, "source_url", None) or getattr(source, "url", None)
    score = getattr(source, "score", None)
    metadata = getattr(source, "metadata", None) or {}

    salida = {
        "document_id": str(document_id),
        "title": source.title,
        "url": url,
        "score": round(score, 3) if score is not None else None,
    }

    # FAQ.2: la autoridad del texto sale en el JSON para que el frontend pueda pintarla
    # distinta. `None` cuando es normativa, así que el shape de CAL.2 no cambia para lo que
    # ya había: se añaden claves, no se alteran las existentes.
    autoridad = etiqueta_de_autoridad(metadata)
    if autoridad:
        salida["authority"] = autoridad
        respaldo = metadata.get("norma_de_respaldo")
        if respaldo:
            salida["backing_url"] = respaldo

    return salida


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
    session: AsyncSession = Depends(get_async_session),
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

    embedding_service = await resolve_embedding_service(session, chatbot_id)

    # RAG.9: parar antes que responder mal. Si el corpus está embebido con otro modelo, la
    # búsqueda vectorial devuelve las fuentes más parecidas *en un espacio que no es el
    # suyo*: normas que no vienen a cuento sosteniendo una respuesta que suena razonable.
    # No hay error que ver, y en un asistente normativo esa es la avería cara.
    try:
        await assert_embedding_space_matches(session, chatbot_id, embedding_service)
    except EmbeddingSpaceMismatch as desajuste:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(desajuste)
        ) from desajuste

    config_provider = LocalConfigProvider(session)

    router_status_message: str | None = None
    selected_chatbot_id = chatbot_id
    if getattr(chatbot, "kind", "atomic") == "router":
        router_llm = await get_model(chatbot.id, config_provider)
        router_node = build_route_to_subagent_node(
            embedding_service=embedding_service,
            chatbot_provider=_ChatbotChildrenProvider(session),
            llm_fallback=router_llm,
        )
        try:
            routing = await router_node(
                {
                    "messages": [type("M", (), {"content": request.message})()],
                    "chatbot_id": str(chatbot.id),
                }
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        selected_chatbot_id = uuid.UUID(str(routing["selected_child_id"]))
        child_result = await session.execute(
            select(HubChatbot).where(HubChatbot.id == selected_chatbot_id)
        )
        child_chatbot = child_result.scalar_one_or_none()
        if child_chatbot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Child chatbot {selected_chatbot_id} not found",
            )
        chatbot = child_chatbot
        router_status_message = f"Materia detectada: {chatbot.name}"

    llm = await get_model(selected_chatbot_id, config_provider)

    # El grafo lo construye la GraphFactory: resuelve la cascada de config
    # (Plataforma → Organización → Chatbot) y selecciona el perfil y el pipeline de
    # retrieval a partir de cfg.retrieval_mode. El endpoint ya no elige estrategia.
    deps = GraphDeps(session=session, embedder=embedding_service, llm=llm)
    core_graph = await GraphFactory().build(selected_chatbot_id, deps, llm)
    compiled = core_graph.compile()

    initial_state = {
        "query": request.message,
        "chatbot_id": str(selected_chatbot_id),
        "language": None,
        # RAG.10: los turnos previos, ya aplanados a 'rol: texto', que es lo que consume el
        # reescritor. El grafo no necesita objetos de mensaje para esto.
        "history": [f"{t.role}: {t.content}" for t in request.history],
        "rewritten_query": None,
        "debug_bypass": request.debug_bypass,
        "bypass": None,
        "retrieval_output": None,
        "merged_items": [],
        "answer": None,
        "quality_score": 0.0,
        "quality_source": None,
        "fallback_used": False,
        "translation_warning": False,
        "reformulated_query": None,
        "reformulada": False,
        "fallback_reason": None,
        "sources": [],
    }

    if request.debug_bypass:
        # JSON, no SSE: no hay nada que transmitir en trozos —no se genera texto— y quien
        # depura quiere el objeto entero de una vez. Tampoco se persiste `HubInteraction`:
        # esto es inspección, no conversación, y contarla ensuciaría las métricas de uso.
        estado = await compiled.ainvoke(initial_state)
        return estado.get("bypass") or {}

    interaction_id = uuid.uuid4()

    # `user` es `None` en el widget público (SEC.8.5): ahí no hay sesión, solo la
    # credencial de sitio. `actor.subject_id` es lo único identificativo que existe en
    # ese caso -- ya es lo que usa `HubInteraction.user_id` más abajo -- así que es
    # también lo que debe viajar a Langfuse.
    langfuse_handler = create_callback_handler(
        session_id=str(interaction_id), user_id=actor.subject_id
    )
    stream_config = (
        {
            "callbacks": [langfuse_handler],
            "metadata": {
                "langfuse_session_id": str(interaction_id),
                "langfuse_user_id": actor.subject_id,
            },
        }
        if langfuse_handler
        else {}
    )

    async def event_generator() -> AsyncIterator[str]:
        uso = {"prompt": 0, "completion": 0, "source": "estimated"}
        # HIB.I — el reloj arranca aquí, antes del primer evento del grafo: la latencia que
        # importa es la que espera quien pregunta, no la del nodo más lento.
        inicio = perf_counter()
        primer_token_ms: int | None = None
        collected_tokens: list[str] = []
        final_sources: list = []
        language_fallback = False
        detected_language = "es"
        # VIS.5 — `None` hasta que el grafo diga en qué lengua está la evidencia. Sin ella no se
        # avisa: no se puede afirmar que difiera de la de la pregunta.
        lengua_de_la_fuente: str | None = None
        # RES.2 — si la respuesta salió de la segunda pasada. Falso mientras nadie lo diga: el
        # nodo `reformular` sólo se ejecuta cuando la primera pasada no llegó al umbral.
        reformulada = False
        fallback_reason: str | None = None
        fallback_answer: str | None = None
        # HIB.I — lo que la traza necesita y hasta ahora no salía de este generador.
        best_score: float | None = None
        gate_passed: bool | None = None
        consulta_reescrita: str | None = None

        try:
            if router_status_message:
                yield _sse(
                    "status",
                    {"node": "route_to_subagent", "msg": router_status_message},
                )

            async for event in compiled.astream_events(initial_state, stream_config, version="v2"):
                kind = event["event"]
                name = event.get("name", "")

                if kind == "on_chain_start" and name in NODE_STATUS_MESSAGES:
                    yield _sse("status", {"node": name, "msg": NODE_STATUS_MESSAGES[name]})

                elif kind == "on_chat_model_stream":
                    # HIB.B — sólo los tokens de los nodos que producen LA RESPUESTA.
                    #
                    # Antes se emitía cualquier llamada al modelo, y en el grafo hay tres que
                    # no son la respuesta: `rewrite_query` (RAG.10), `reformular` (RES.2) y,
                    # en el modo agéntico, el selector que corre dentro de `retrieve`. Quien
                    # preguntaba veía la consulta reformulada como si fuera la contestación.
                    #
                    # La lista se DERIVA de `_FINAL_NODES`, que ya es la fuente de verdad de
                    # qué nodos producen la respuesta y que el manejador del estado final ya
                    # usa: quien añada un nodo generador tiene que declararlo ahí de todos
                    # modos. Una lista propia aquí divergiría en el primer cambio.
                    nodo = (event.get("metadata") or {}).get("langgraph_node")
                    if nodo is not None and nodo not in _FINAL_NODES:
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    if chunk is not None:
                        # USR.8 — `texto_de` y no `chunk.content` a pelo. Gemini devuelve el
                        # contenido como **lista de bloques** en cuanto la respuesta tiene más
                        # de una parte, y entonces esto guardaba una lista en
                        # `collected_tokens`: el `"".join(...)` de ochenta líneas más abajo
                        # levantaba `TypeError`, y con él se caían el `done`, la interacción y
                        # la contabilidad de la cuota. Medido el 2026-09-03: el asistente
                        # agéntico tenía **0 interacciones** guardadas y 33 el de RAG.
                        #
                        # Es la tercera vez que muerde el mismo problema, y el docstring de
                        # `core/llm_text.py` ya lo decía: quien asume `str` no falla al
                        # recibirlo, falla más tarde y en otro sitio.
                        delta = texto_de(chunk)
                        if delta:
                            if primer_token_ms is None:
                                primer_token_ms = int((perf_counter() - inicio) * 1000)
                            collected_tokens.append(delta)
                            yield _sse("token", {"delta": delta})

                elif kind == "on_chain_end" and name in _FINAL_NODES:
                    output = event.get("data", {}).get("output") or {}
                    raw_sources = output.get("sources", [])
                    final_sources = [
                        _source_to_dict(s) for s in raw_sources if _es_citable(s)
                    ]
                    fallback_reason = output.get("fallback_reason")
                    if output.get("fallback_used"):
                        fallback_answer = output.get("answer")
                    # HIB.I — la nota y la decisión de la puerta, tal como quedaron. Se leen
                    # del nodo final porque es el único punto donde ya están las dos.
                    nota_final = output.get("quality_score")
                    if nota_final is not None:
                        best_score = nota_final
                        gate_passed = nota_final >= getattr(
                            core_graph.cfg, "quality_threshold", 0.0
                        )
                    consulta_reescrita = output.get("rewritten_query") or consulta_reescrita

                elif kind == "on_chain_end" and name == "detect_language":
                    output = event.get("data", {}).get("output") or {}
                    detected_language = output.get("language") or "es"

                elif kind == "on_chain_end" and name == "merge":
                    output = event.get("data", {}).get("output") or {}
                    language_fallback = bool(output.get("translation_warning"))
                    # VIS.5 — la lengua de la fuente, que es con la que se redacta el aviso.
                    lengua_de_la_fuente = output.get("context_source_language")

                elif kind == "on_chain_end" and name == "reformular":
                    # RES.2 — el hecho viaja, el texto de producto no se decide aquí. Una
                    # respuesta rescatada reformulando no se revisa igual que una directa.
                    output = event.get("data", {}).get("output") or {}
                    reformulada = bool(output.get("reformulada"))

                elif kind == "on_chat_model_end":
                    # SEC.4: el uso real, tal como lo declara el proveedor. Se acumula en
                    # vez de asignarse porque un turno puede invocar al modelo más de una
                    # vez —reescritura de consulta, selector de agente—, y todo eso lo paga
                    # la misma persona.
                    entrada, salida = _uso_del_evento(event)
                    if entrada or salida:
                        uso["prompt"] += entrada
                        uso["completion"] += salida
                        uso["source"] = "provider"

        except Exception:  # noqa: BLE001
            # Issue #147: el detalle va al registro, no al cliente. Este manejador ni siquiera
            # registraba, así que el único que no se enteraba de qué había fallado era quien
            # tenía que arreglarlo.
            logger.exception("El turno de chat falló durante el grafo; el cliente recibe `error`.")
            yield _sse("error", {"message": MENSAJE_DE_ERROR})
            return

        # USR.8 — **todo esto va dentro de su propio `try`**, y no es simetría: guardar la
        # interacción, la traza, la cuota, el commit y el propio `done` estaban fuera de
        # cualquier protección. Un fallo aquí no producía ni un evento de error, así que el
        # cliente se quedaba esperando sin poder distinguirlo de una respuesta lenta — que
        # es exactamente lo que pasó con el `TypeError` del contenido en bloques.
        #
        # Se emite `error` y **no** un `done` con datos inventados: si la interacción no se
        # guardó, decir que sí dejaría al cliente con un `interaction_id` que no existe y
        # una valoración que no se puede anclar a nada.
        try:
            # El fallback y el mensaje del validador de citas no pasan por el stream de tokens
            # del LLM, así que hay que emitirlos aquí para que el usuario vea una respuesta.
            #
            # HIB.B — se emite SIEMPRE que haya rendición, no sólo cuando no llegó nada. La
            # condición `and not collected_tokens` era el segundo defecto: el contrato de citas
            # corre *dentro* de `generate_answer`, después de generar, así que cuando rechaza los
            # tokens ya han salido — y entonces el mensaje de rendición no se mostraba nunca y el
            # usuario se quedaba con la respuesta que el contrato acababa de descartar.
            #
            # Por SSE no se retira lo ya enviado, así que se le dice al cliente que lo descarte.
            # La alternativa —retener los tokens hasta validar— costaría el streaming en todas
            # las respuestas: medido en HIB.I, el primer token pasaría de 780 ms a 2.140 ms, y el
            # contrato rechaza en torno al 4 % de las consultas. Decisión del usuario, 2026-08-26.
            if fallback_answer:
                if collected_tokens:
                    yield _sse("discard", {"reason": fallback_reason or "fallback"})
                    collected_tokens.clear()
                collected_tokens.append(fallback_answer)
                yield _sse("token", {"delta": fallback_answer})

            # HIB.B — lo que se guarda es lo que el usuario vio. Antes guardaba la reformulación,
            # así que quien revisaba juzgaba una respuesta que nadie recibió.
            assistant_message = "".join(collected_tokens)

            # SEC.4: si el proveedor no declaró uso, se estima por longitud y **se marca**. Una
            # cuota apoyada en una estimación silenciosa no se puede defender ante quien la
            # sufre; con la marca, al menos se sabe qué número se está discutiendo.
            if uso["source"] == "estimated":
                uso["prompt"] = _tokens_estimados(request.message)
                uso["completion"] = _tokens_estimados(assistant_message)

            total_tokens = uso["prompt"] + uso["completion"]
            interaction = HubInteraction(
                id=interaction_id,
                chatbot_id=selected_chatbot_id,
                user_id=actor.subject_id,
                user_message=request.message,
                assistant_message=assistant_message,
                run_id=interaction_id,
                fallback_reason=fallback_reason,
                prompt_tokens=uso["prompt"] or None,
                completion_tokens=uso["completion"] or None,
                # HIB.I — la traza de diagnóstico. Con el piloto en marcha ya es tarde para los
                # datos que no se guardaron: sin los identificadores y las puntuaciones de lo
                # recuperado no se puede saber, meses después, si una respuesta mala fue de
                # recuperación o de redacción, ni re-ejecutar una ablación sobre las mismas
                # consultas sin volver a pedir trabajo a los informadores.
                interaction_metadata=construye_traza(
                    cfg=core_graph.cfg,
                    fuentes=final_sources,
                    usage_source=uso["source"],
                    best_score=best_score,
                    gate_passed=gate_passed,
                    language=detected_language,
                    source_language=lengua_de_la_fuente,
                    translation_warning=language_fallback,
                    # El turno que se está respondiendo, contando desde 1. Es lo que permite
                    # separar «falla la primera pregunta» de «falla el seguimiento», que es
                    # justo la distinción que HIB.C viene a arreglar.
                    turn_index=len(request.history) + 1,
                    rewritten_query=consulta_reescrita,
                    reformulada=reformulada,
                    latency_ms=int((perf_counter() - inicio) * 1000),
                    first_token_ms=primer_token_ms,
                ),
            )
            session.add(interaction)
            # El consumo va en el MISMO commit que la interacción, no en un segundo write: si
            # se separaran, un fallo entre los dos dejaría respuestas servidas sin contabilizar
            # —o al revés— y la cuota dejaría de cuadrar con lo que el usuario ha recibido.
            await contabilizar_interaccion(
                session,
                actor,
                chatbot,
                total_tokens,
                ip=ip_del_visitante if es_widget else None,
            )
            await session.commit()

            translation_warning = (
                _build_translation_warning(lengua_de_la_fuente, detected_language)
                if language_fallback
                else None
            )
            yield _sse(
                "done",
                {
                    "interaction_id": str(interaction_id),
                    "sources": final_sources,
                    "language_fallback": language_fallback,
                    "translation_warning": translation_warning,
                    "reformulada": reformulada,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "El turno de chat falló después del grafo; el cliente recibe `error`."
            )
            yield _sse("error", {"message": MENSAJE_DE_ERROR})
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
