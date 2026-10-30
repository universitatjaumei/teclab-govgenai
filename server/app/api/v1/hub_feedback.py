"""Endpoint de feedback para interacciones del Hub.

POST /api/v1/hub/feedback/{interaction_id}
  Registra la valoración del usuario (1-5 estrellas + comentario opcional).
  Sincroniza automáticamente con LangFuse si está configurado.

GET /api/v1/hub/feedback/{chatbot_id}/review
  Devuelve interacciones para revisión humana (solo admin).


Deploy: edge
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_current_user_optional
from server.app.core.auth import UserInfo
from server.app.core.auth.chatbot_access import VIA_WIDGET, assert_chatbot_access
from server.app.core.auth.widget_key import (
    CABECERA as CABECERA_WIDGET,
    actor_anonimo_de_widget,
    resolver_widget_key,
)
from server.app.core.auth.tenancy import assert_chatbot_org_access, assert_org_access
from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.app.api.deps import get_session
from server.app.modules.agents_hub.database.operational_models import HubInteraction
# HIB.H — el mismo modelo que valida el lote de evaluación valida lo que anota el informador.
# Dos formas para la misma idea divergen, y con ellas se cae el instrumental que cruza
# conversaciones reales con escenarios de prueba.
from server.app.modules.agents_hub.evaluation.escenario_contrato import ExpectedSources
from server.app.modules.agents_hub.services.feedback_service import FeedbackService

router = APIRouter(prefix="/hub/feedback", tags=["hub-feedback"])


class FeedbackRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)
    comment: str | None = Field(None, max_length=2000)


class ReviewVerdictRequest(BaseModel):
    """Veredicto de quien revisa (REV.1).

    Mismos tres valores que `HubTestRun.verdict`, a propósito: dos vocabularios distintos
    para la misma idea acabarían divergiendo.
    """

    verdict: Literal["good", "bad", "mixed"]
    note: str | None = Field(None, max_length=2000)
    # HIB.H — la solución, no sólo el veredicto. Opcionales porque se piden de distintas
    # cosas: el veredicto de TODAS las conversaciones (es la métrica primaria y tiene que ser
    # rápido), la fuente esperada sólo de las únicas tras deduplicar. Exigirlas siempre
    # convertiría la revisión en un formulario y nadie la completaría.
    #
    # El tipo es el MISMO que valida el lote de evaluación (HIB.G): un solo esquema para las
    # conversaciones reales y para los escenarios de prueba.
    expected_sources: ExpectedSources | None = None
    reference_answer: str | None = Field(None, max_length=4000)

    @model_validator(mode="after")
    def _exigir_motivo_cuando_es_malo(self) -> "ReviewVerdictRequest":
        """Un «mal» sin motivo no reformula nada.

        El propósito entero de la revisión es saber **qué** había que cambiar. Un veredicto
        negativo sin texto deja a quien reescribe la FAQ exactamente donde estaba, y encima
        con la apariencia de que el trabajo está hecho.
        """
        if self.verdict == "bad" and not (self.note or "").strip():
            raise ValueError(
                "Un veredicto 'bad' necesita una nota que diga qué había que cambiar"
            )
        return self


class InteractionReviewOut(BaseModel):
    """Interacción servida a la revisión humana (CAL.2).

    El endpoint devolvía `list[dict]`, que en el contrato es una lista de objetos sin
    forma; `RevisionInteraccionesPage` se veía obligada a redeclarar los siete campos a mano. Lo que
    la pantalla tabula y exporta a CSV sale de aquí.
    """

    id: uuid.UUID
    user_message: str
    assistant_message: str
    feedback_score: int | None = None
    feedback_text: str | None = None
    run_id: str | None = None
    created_at: datetime
    # REV.1. Distinto de `feedback_*`, que es la valoración del usuario final.
    review_verdict: str | None = None
    review_note: str | None = None
    review_by: str | None = None
    review_at: datetime | None = None
    # HIB.H — se devuelven para que la pantalla pueda mostrar lo ya anotado sin una segunda
    # llamada, y para que la exportación las lleve.
    review_expected_sources: dict | None = None
    review_reference_answer: str | None = None


async def _exigir_el_publico_del_widget(session, cabecera_widget, interaccion) -> None:
    """403 salvo que la credencial sea del chatbot de la interacción, el chatbot sea
    `public_anon` y la interacción sea del público de ese widget (#340).

    Son las condiciones del chat, más la última: el público valora lo que preguntó por el
    widget, no la conversación que alguien tuvo con sesión. Quien valora no se identifica —es
    el sitio, no una persona—, así que lo que lo acota es el identificador de la interacción, que
    sólo recibe quien hizo la pregunta.
    """
    clave = await resolver_widget_key(session, cabecera_widget)
    chatbot = await session.get(HubChatbot, interaccion.chatbot_id)
    publico = actor_anonimo_de_widget(interaccion.chatbot_id)
    if (
        clave is None
        or chatbot is None
        or clave.chatbot_id != interaccion.chatbot_id
        or interaccion.user_id != publico.subject_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCESS_MODE_FORBIDDEN",
                "reason": "the widget credential cannot rate this interaction",
            },
        )
    assert_chatbot_access(None, chatbot, via=VIA_WIDGET)


def get_feedback_service(session: AsyncSession = Depends(get_session)) -> FeedbackService:
    """Las valoraciones y la revisión de interacciones (#274)."""
    return FeedbackService(session)


@router.post("/{interaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def submit_feedback(
    interaction_id: uuid.UUID,
    request: FeedbackRequest,
    http_request: Request,
    user: UserInfo | None = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_session),
    service: FeedbackService = Depends(get_feedback_service),
) -> None:
    # #340 — el público de un widget es anónimo: conversa con la credencial de sitio y con ella
    # tiene que poder valorar. Sin sesión ni credencial, 401 ANTES de buscar la interacción, como
    # el chat (SEC.8.5): si no, el 404 diría cuáles existen.
    cabecera_widget = http_request.headers.get(CABECERA_WIDGET)
    if user is None and not cabecera_widget:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # SEC.8.1: el GET de revisión comprobaba la organización desde SEC.2; este POST no
    # comprobaba nada y el servicio hace `UPDATE ... WHERE id = :id` a ciegas, así que
    # cualquier usuario autenticado —de cualquier organización— escribía sobre la
    # valoración de una conversación ajena, y de ahí pasaba a LangFuse.
    interaccion = await session.get(HubInteraction, interaction_id)
    if interaccion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Interaction not found"
        )
    if user is None:
        await _exigir_el_publico_del_widget(session, cabecera_widget, interaccion)
    elif interaccion.user_id != user.user_id:
        await assert_chatbot_org_access(session, interaccion.chatbot_id, user)

    await service.submit_feedback(
        interaction_id=interaction_id,
        score=request.score,
        comment=request.comment,
    )


@router.patch(
    "/interactions/{interaction_id}/review", response_model=InteractionReviewOut
)
async def review_interaction(
    interaction_id: uuid.UUID,
    request: ReviewVerdictRequest,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    service: FeedbackService = Depends(get_feedback_service),
) -> InteractionReviewOut:
    """Anota el veredicto de quien revisa sobre una conversación real (REV.1).

    Deploy: edge.
    """
    interaccion = await session.get(HubInteraction, interaction_id)
    if interaccion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Interaction not found"
        )
    # SEC.8.1: estas conversaciones llevan preguntas de personas identificadas. Leerlas sin
    # ser de su organización ya era el caso más grave del hallazgo A2; anotarlas lo es igual,
    # y además deja rastro atribuido a alguien que no debería estar ahí.
    await assert_chatbot_org_access(session, interaccion.chatbot_id, user)

    revisada = await service.record_review(
        interaction=interaccion,
        verdict=request.verdict,
        note=request.note,
        reviewer=user.email,
        # HIB.H — `None` viaja como `None` y no como `{}`: el servicio distingue «no anotado»
        # de «anotado sin fuentes», y esa distinción es el denominador de las cifras.
        expected_sources=(
            request.expected_sources.model_dump(exclude_none=True)
            if request.expected_sources is not None
            else None
        ),
        reference_answer=request.reference_answer,
    )
    # `run_id` es UUID en la fila y `str` en el contrato (mismo shape que el GET de más
    # abajo): devolver la fila del ORM tal cual dejaba que FastAPI intentara servir un UUID
    # donde el contrato promete un string, y la respuesta reventaba en 500 -- después de
    # escribir ya el veredicto, así que quien revisaba veía un error por una conversación
    # que sí había quedado anotada.
    return InteractionReviewOut(
        id=revisada.id,
        user_message=revisada.user_message,
        assistant_message=revisada.assistant_message,
        feedback_score=revisada.feedback_score,
        feedback_text=revisada.feedback_text,
        run_id=str(revisada.run_id) if revisada.run_id else None,
        created_at=revisada.created_at,
        review_verdict=revisada.review_verdict,
        review_note=revisada.review_note,
        review_by=revisada.review_by,
        review_at=revisada.review_at,
        review_expected_sources=revisada.review_expected_sources,
        review_reference_answer=revisada.review_reference_answer,
    )


@router.get("/{chatbot_id}/review", response_model=list[InteractionReviewOut])
async def get_interactions_for_review(
    chatbot_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    only_low_scores: bool = Query(False),
    review_status: Literal["pending", "reviewed", "all"] = Query("pending"),
    verdict: Literal["good", "bad", "mixed"] | None = Query(None),
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    service: FeedbackService = Depends(get_feedback_service),
) -> list[dict]:
    if user.role not in ("superadmin", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or superadmin can access interaction reviews",
        )
    # SEC.2: tener rol de admin no basta. Estas interacciones son conversaciones de
    # ciudadanos con el asistente de OTRA administración; leerlas sin ser de su organización
    # es el caso más grave del hallazgo A2, porque el dato es personal y de un tercero.
    chatbot = await session.get(HubChatbot, chatbot_id)
    if chatbot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")
    assert_org_access(user, chatbot.organizacion_id)

    interactions = await service.get_interactions_for_review(
        chatbot_id=chatbot_id,
        limit=limit,
        only_low_scores=only_low_scores,
        review_status=review_status,
        verdict=verdict,
    )
    return [
        {
            "id": str(i.id),
            "user_message": i.user_message,
            "assistant_message": i.assistant_message,
            "feedback_score": i.feedback_score,
            "feedback_text": i.feedback_text,
            "run_id": str(i.run_id) if i.run_id else None,
            "created_at": i.created_at.isoformat(),
            "review_verdict": i.review_verdict,
            "review_note": i.review_note,
            "review_by": i.review_by,
            "review_at": i.review_at.isoformat() if i.review_at else None,
        }
        for i in interactions
    ]
