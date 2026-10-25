"""Tests para el watcher de ingestión."""
import uuid
import pytest
from unittest.mock import AsyncMock, Mock, MagicMock


class TestIngestionWatcher:

    @pytest.mark.asyncio
    async def test_process_source_returns_document_and_chunk_count(self) -> None:
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        first_exec = Mock()
        first_exec.scalar_one_or_none = Mock(return_value=None)
        second_exec = Mock()
        second_exec.scalars = Mock(return_value=iter([]))
        mock_session = AsyncMock()
        mock_session.begin_nested = MagicMock(return_value=AsyncMock())
        mock_session.execute = AsyncMock(side_effect=[first_exec, second_exec, Mock()])
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = Mock()

        # EXT.1: `process_source` ya no convierte nada. Al corpus entra Markdown que ya
        # produjo el pipeline de curación, así que el contenido se le pasa — no había que
        # doblar el conversor porque no hay conversor al que llamar.
        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )

        doc, n_chunks = await watcher.process_source(
            source_url="https://example.com",
            chatbot_id=uuid.uuid4(),
            prefetched_content="# Test\n\nContent",
        )

        assert isinstance(doc, HubDocument)
        assert n_chunks >= 1

    @pytest.mark.asyncio
    async def test_process_returns_existing_doc_for_same_content(self) -> None:
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        existing_doc = MagicMock()
        existing_doc.id = uuid.uuid4()
        existing_doc.chatbot_id = uuid.uuid4()
        existing_doc.markdown_content = "# Test\n\nContent"
        existing_doc.canonical_url = "https://example.com"
        existing_doc.language = "es"

        first_exec = Mock()
        first_exec.scalar_one_or_none = Mock(return_value=existing_doc)
        mock_session = AsyncMock()
        mock_session.begin_nested = MagicMock(return_value=AsyncMock())
        mock_session.execute = AsyncMock(side_effect=[first_exec, Mock()])
        mock_session.commit = AsyncMock()
        mock_session.add = Mock()

        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )

        doc, _ = await watcher.process_source(
            source_url="https://example.com",
            chatbot_id=uuid.uuid4(),
            prefetched_content="# Test\n\nContent",
        )

        assert doc is existing_doc
