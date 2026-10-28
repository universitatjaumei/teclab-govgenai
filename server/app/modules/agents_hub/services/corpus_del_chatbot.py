"""Las operaciones sobre el corpus de un chatbot que pide el panel. Deploy: edge (#298).

Vivían en `hub_chatbots_router`, que es cloud: estadísticas, regenerar fragmentos y recalcular el
corpus leen y escriben `HubDocument`, que es dato del cliente. Ahora las sirve
`hub_chatbots_corpus_router`, con las mismas rutas, y la lógica está aquí y no en el handler
(#274).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import HubDocument
from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
from server.app.modules.agents_hub.services.corpus_recalculator import recalculate_corpus
from server.app.modules.agents_hub.services.embedding_resolver import resolve_embedding_service
from server.app.modules.agents_hub.services.embedding_space import assert_embedding_space_matches


@dataclass(frozen=True)
class EstadisticasDelCorpus:
    total_documents: int
    total_tokens: int
    by_language: dict[str, int]


async def estadisticas(session: AsyncSession, chatbot_id: uuid.UUID) -> EstadisticasDelCorpus:
    del_chatbot = HubDocument.chatbot_id == chatbot_id
    total_documents = int(
        (await session.execute(select(func.count(HubDocument.id)).where(del_chatbot))).scalar_one() or 0
    )
    total_tokens = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(HubDocument.token_count), 0)).where(del_chatbot)
            )
        ).scalar_one()
        or 0
    )
    por_lengua = await session.execute(
        select(HubDocument.language, func.coalesce(func.sum(HubDocument.token_count), 0))
        .where(del_chatbot)
        .group_by(HubDocument.language)
    )
    return EstadisticasDelCorpus(
        total_documents=total_documents,
        total_tokens=total_tokens,
        by_language={str(lengua): int(tokens or 0) for lengua, tokens in por_lengua.all()},
    )


async def regenerar_fragmentos(session: AsyncSession, chatbot_id: uuid.UUID) -> tuple[int, int]:
    """Rehace los fragmentos de cada documento. Devuelve (documentos, fragmentos creados)."""
    documentos = list(
        (await session.execute(select(HubDocument).where(HubDocument.chatbot_id == chatbot_id)))
        .scalars()
        .all()
    )
    watcher = IngestionWatcher(
        session=session,
        embedding_service=await resolve_embedding_service(session, chatbot_id),
    )
    creados = 0
    for documento in documentos:
        creados += await watcher._regenerate_chunks_for_document(documento)
    return len(documentos), creados


async def recalcular(
    session: AsyncSession, chatbot_id: uuid.UUID, retrieval_mode: str
) -> tuple[int, int, int]:
    """Recalcula el corpus con el modelo de embeddings activo. (procesados, creados, borrados).

    MOD.1: antes compara el espacio vectorial REAL del corpus con el del modelo activo, y lanza
    `EmbeddingSpaceMismatch` si no casan: misma dimensión no significa mismo espacio.
    """
    embedding_service = await resolve_embedding_service(session, chatbot_id)
    await assert_embedding_space_matches(session, chatbot_id, embedding_service)
    resultado = await recalculate_corpus(
        session=session,
        chatbot_id=chatbot_id,
        retrieval_mode=retrieval_mode,
        embedding_service=embedding_service,
    )
    await session.commit()
    return resultado
