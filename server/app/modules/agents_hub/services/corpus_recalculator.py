"""Recálculo de corpus según retrieval_mode del chatbot."""

from __future__ import annotations

from sqlalchemy import delete as sql_delete
from sqlalchemy import select

from server.app.modules.agents_hub.database.operational_models import (
    HubDocument,
    HubDocumentChunk,
)
from server.app.modules.agents_hub.agent.public_graphs.validacion import (
    MODOS_QUE_BUSCAN_POR_FRAGMENTOS,
)
from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher


async def recalculate_corpus(
    *,
    session,
    chatbot_id,
    retrieval_mode: str,
    embedding_service,
) -> tuple[int, int, int]:
    """Recalcula el corpus completo del chatbot.

    Returns:
        (documents_processed, chunks_created, chunks_deleted)
    """
    docs_result = await session.execute(
        select(HubDocument).where(HubDocument.chatbot_id == chatbot_id)
    )
    docs = list(docs_result.scalars().all())

    if retrieval_mode in MODOS_QUE_BUSCAN_POR_FRAGMENTOS:
        watcher = IngestionWatcher(
            session=session,
            embedding_service=embedding_service,
        )
        chunks_created = 0
        for doc in docs:
            chunks_created += await watcher._regenerate_chunks_for_document(doc)
        return (len(docs), chunks_created, 0)

    delete_result = await session.execute(
        sql_delete(HubDocumentChunk).where(HubDocumentChunk.chatbot_id == chatbot_id)
    )
    chunks_deleted = int(getattr(delete_result, "rowcount", 0) or 0)
    return (len(docs), 0, chunks_deleted)