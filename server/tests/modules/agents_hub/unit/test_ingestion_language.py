"""Tests TDD — Etiquetado de idioma en la ingestión (Prompt 9.8.1)."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestProcessSourceLanguageDetection:
    """process_source() debe auto-detectar idioma cuando language=None
    y respetar el idioma explícito cuando se proporciona."""

    @pytest.mark.asyncio
    async def test_process_source_auto_detects_catalan_content(self) -> None:
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        catalan_content = "# Documentació\n\nAquest és un text en català sobre normativa universitària."

        first_exec = MagicMock()
        first_exec.scalar_one_or_none = MagicMock(return_value=None)
        second_exec = MagicMock()
        second_exec.scalars = MagicMock(return_value=iter([]))
        mock_session = AsyncMock()
        mock_session.begin_nested = MagicMock(return_value=AsyncMock())
        mock_session.execute = AsyncMock(side_effect=[first_exec, second_exec, MagicMock()])
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )

        with patch(
            "server.app.modules.agents_hub.ingestion.watcher.detect_language",
            return_value="ca",
        ) as mock_detect:
            doc, _ = await watcher.process_source(
                source_url="https://example.com/doc",
                chatbot_id=uuid.uuid4(),
                prefetched_content=catalan_content,
                language=None,  # debe auto-detectar
            )

        mock_detect.assert_called_once_with(catalan_content)
        assert isinstance(doc, HubDocument)
        assert doc.language == "ca"

    @pytest.mark.asyncio
    async def test_process_source_respects_explicit_language(self) -> None:
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        content = "Some English content about regulations."

        first_exec = MagicMock()
        first_exec.scalar_one_or_none = MagicMock(return_value=None)
        second_exec = MagicMock()
        second_exec.scalars = MagicMock(return_value=iter([]))
        mock_session = AsyncMock()
        mock_session.begin_nested = MagicMock(return_value=AsyncMock())
        mock_session.execute = AsyncMock(side_effect=[first_exec, second_exec, MagicMock()])
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )

        with patch(
            "server.app.modules.agents_hub.ingestion.watcher.detect_language"
        ) as mock_detect:
            doc, _ = await watcher.process_source(
                source_url="https://example.com/doc",
                chatbot_id=uuid.uuid4(),
                prefetched_content=content,
                language="en",  # idioma explícito — NO debe llamar a detect_language
            )

        mock_detect.assert_not_called()
        assert isinstance(doc, HubDocument)
        assert doc.language == "en"

    @pytest.mark.asyncio
    async def test_process_user_upload_auto_detects_language(self) -> None:
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        english_content = "# Report\n\nThis document describes the annual budget allocation."

        mock_session = AsyncMock()
        mock_session.begin_nested = MagicMock(return_value=AsyncMock())

        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )

        with patch(
            "server.app.modules.agents_hub.ingestion.watcher.asyncio.to_thread",
            return_value=english_content,
        ):
            with patch(
                "server.app.modules.agents_hub.ingestion.watcher.detect_language",
                return_value="en",
            ) as mock_detect:
                chunks = await watcher.process_user_upload(
                    source_url="/tmp/report.pdf",
                    chatbot_id=uuid.uuid4(),
                    owner_id=uuid.uuid4(),
                )

        mock_detect.assert_called_once_with(english_content)
        assert all(c.language == "en" for c in chunks)
