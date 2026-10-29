"""El corpus de un chatbot: estadísticas, regenerar fragmentos y recalcular (#298).

Deploy: edge
Módulo: chatbots — a nivel de router, como en `hub_chatbots_router`.

Estaban en `hub_chatbots_router`, que es cloud, y leen y escriben `HubDocument`, que es dato del
cliente. Se parte como `agentes` y `agentes_catalogo`: mismo prefijo y misma etiqueta, así que las
rutas y el cliente generado no cambian. La lógica vive en `services/corpus_del_chatbot.py`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from server.app.api.deps import get_session, require_module, require_role, require_scopes
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import assert_chatbot_org_access
from server.app.modules.agents_hub.services import corpus_del_chatbot
from server.app.modules.agents_hub.services.corpus_recommender import recommend_retrieval_mode
from server.app.modules.agents_hub.services.embedding_space import EmbeddingSpaceMismatch
from server.app.modules.agents_hub.services.retrieval.long_context_strategy import (
    LONG_CONTEXT_TOKEN_LIMIT,
)

router = APIRouter(
    prefix="/hub/chatbots",
    tags=["hub-chatbots"],
    dependencies=[Depends(require_module("chatbots"))],
)

_require_admin = require_role("superadmin", "admin")


class CorpusStatsOut(BaseModel):
    total_documents: int
    total_tokens: int
    by_language: dict[str, int]
    recommended_mode: str
    recommendation_reason: str
    #: #277 — el límite del modo MD_LONG_CONTEXT y si el corpus cabe. El formulario los comparaba
    #: con el límite escrito en el cliente; si el límite cambia, cambia aquí y en ningún sitio más.
    limite_contexto_largo: int
    cabe_en_contexto_largo: bool


class RegenerateChunksOut(BaseModel):
    task_id: str
    message: str
    documents_processed: int
    chunks_created: int


class RecalculateCorpusOut(BaseModel):
    task_id: str
    message: str
    documents_queued: int
    chunks_created: int
    chunks_deleted: int


@router.get(
    "/{chatbot_id}/corpus-stats",
    response_model=CorpusStatsOut,
    dependencies=[Depends(require_scopes("chatbots:read"))],
)
async def get_corpus_stats(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    await assert_chatbot_org_access(session, chatbot_id, user)
    stats = await corpus_del_chatbot.estadisticas(session, chatbot_id)
    recommended_mode, recommendation_reason = recommend_retrieval_mode(
        total_tokens=stats.total_tokens,
        context_window=LONG_CONTEXT_TOKEN_LIMIT,
    )
    return CorpusStatsOut(
        total_documents=stats.total_documents,
        total_tokens=stats.total_tokens,
        by_language=stats.by_language,
        recommended_mode=recommended_mode,
        recommendation_reason=recommendation_reason,
        limite_contexto_largo=LONG_CONTEXT_TOKEN_LIMIT,
        cabe_en_contexto_largo=stats.total_tokens <= LONG_CONTEXT_TOKEN_LIMIT,
    )


@router.post("/{chatbot_id}/regenerate-chunks", response_model=RegenerateChunksOut)
async def regenerate_chunks(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    chatbot = await assert_chatbot_org_access(session, chatbot_id, user)
    if chatbot.retrieval_mode != "RAG":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede regenerar chunks cuando retrieval_mode == 'RAG'.",
        )
    documentos, creados = await corpus_del_chatbot.regenerar_fragmentos(session, chatbot_id)
    return RegenerateChunksOut(
        task_id=str(uuid.uuid4()),
        message="Regeneración completada",
        documents_processed=documentos,
        chunks_created=creados,
    )


@router.post(
    "/{chatbot_id}/recalculate-corpus",
    response_model=RecalculateCorpusOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recalculate_corpus_endpoint(
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(_require_admin),
    session=Depends(get_session),
):
    chatbot = await assert_chatbot_org_access(session, chatbot_id, user)
    try:
        procesados, creados, borrados = await corpus_del_chatbot.recalcular(
            session, chatbot_id, chatbot.retrieval_mode
        )
    except EmbeddingSpaceMismatch as desajuste:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(desajuste)) from desajuste
    return RecalculateCorpusOut(
        task_id=str(uuid.uuid4()),
        message=f"Recálculo completado. {procesados} documentos procesados.",
        documents_queued=procesados,
        chunks_created=creados,
        chunks_deleted=borrados,
    )
