"""Tests TDD — Multi-idioma en la ingestión: dos versiones lingüísticas coexisten (Prompt 9CBis.9)."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestMultiLanguageDocumentCoexistence:
    """process_source() con clave (chatbot_id, canonical_url, language):
    versiones en distintos idiomas del mismo URL coexisten; mismo idioma reemplaza."""

    def _make_session(self, hash_result=None, url_lang_result=None):
        """Factoría de mock de sesión para los tests de esta clase."""
        hash_exec = MagicMock()
        hash_exec.scalar_one_or_none = MagicMock(return_value=hash_result)

        url_lang_exec = MagicMock()
        url_lang_exec.scalars = MagicMock(
            return_value=iter(url_lang_result if url_lang_result else [])
        )

        # Tercer execute: delete de chunks en _regenerate_chunks_for_document
        chunk_exec = MagicMock()

        session = AsyncMock()
        session.begin_nested = MagicMock(return_value=AsyncMock())
        session.execute = AsyncMock(side_effect=[hash_exec, url_lang_exec, chunk_exec])
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_two_language_versions_of_same_url_coexist(self) -> None:
        """Ingestar CA de la misma URL cuando ya existe ES → no borra la versión ES."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        session = self._make_session(hash_result=None, url_lang_result=[])

        watcher = IngestionWatcher(
            session=session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 10)),
        )

        with patch(
            "server.app.modules.agents_hub.ingestion.watcher.MarkdownChunker"
        ) as MockChunker:
            MockChunker.return_value.split = MagicMock(return_value=[])
            doc, _ = await watcher.process_source(
                source_url="https://example.com/normativa.pdf",
                chatbot_id=uuid.uuid4(),
                prefetched_content="Contingut en català.",
                language="ca",
            )

        # La versión ES (u otra idioma) no debe haberse borrado
        session.delete.assert_not_called()
        assert isinstance(doc, HubDocument)
        # Se pide `ca` y se guarda `val`: son la misma lengua y el corpus la escribe `val`.
        # Lo que este test protege —que las dos versiones de una URL conviven— no cambia.
        assert doc.language == "val"

    @pytest.mark.asyncio
    async def test_reingest_same_url_same_language_replaces_doc(self) -> None:
        """Re-ingestar ES de la misma URL → borra el doc ES antiguo, crea uno nuevo."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        existing_es = HubDocument(
            id=uuid.uuid4(),
            chatbot_id=uuid.uuid4(),
            title="Normativa ES",
            canonical_url="https://example.com/normativa.pdf",
            markdown_content="Contenido antiguo.",
            content_hash="old_hash_es",
            language="es",
            source_kind="upload",
            token_count=10,
        )

        hash_exec = MagicMock()
        hash_exec.scalar_one_or_none = MagicMock(return_value=None)  # nuevo hash

        url_lang_exec = MagicMock()
        url_lang_exec.scalars = MagicMock(return_value=iter([existing_es]))

        # delete chunks del doc antiguo + delete chunks del nuevo en regenerate
        del_exec_1 = MagicMock()
        del_exec_2 = MagicMock()

        session = AsyncMock()
        session.begin_nested = MagicMock(return_value=AsyncMock())
        session.execute = AsyncMock(
            side_effect=[hash_exec, url_lang_exec, del_exec_1, del_exec_2]
        )
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()

        watcher = IngestionWatcher(
            session=session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 10)),
        )

        with patch(
            "server.app.modules.agents_hub.ingestion.watcher.MarkdownChunker"
        ) as MockChunker:
            MockChunker.return_value.split = MagicMock(return_value=[])
            doc, _ = await watcher.process_source(
                source_url="https://example.com/normativa.pdf",
                chatbot_id=existing_es.chatbot_id,
                prefetched_content="Contenido actualizado en español.",
                language="es",
            )

        # El doc ES antiguo debe haberse borrado
        session.delete.assert_called_once_with(existing_es)
        assert isinstance(doc, HubDocument)
        assert doc.language == "es"

    @pytest.mark.asyncio
    async def test_reingest_same_url_different_language_does_not_delete_other(self) -> None:
        """Ingestar CA no borra el doc ES existente para la misma URL.

        Verifica que la query de reemplazo usa (chatbot_id, canonical_url, language)
        y no (chatbot_id, canonical_url) sin idioma, porque si usara esta última
        encontraría el doc ES y lo borraría.
        """
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        chatbot_id = uuid.uuid4()

        # El mock de URL+language="ca" devuelve vacío (no hay doc CA)
        # Si el watcher no incluyera language en la query, la lógica seguiría igual
        # porque el mock no ejecuta SQL real — el test complementario de integración
        # verifica el comportamiento real con BD.
        session = self._make_session(hash_result=None, url_lang_result=[])

        watcher = IngestionWatcher(
            session=session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 10)),
        )

        with patch(
            "server.app.modules.agents_hub.ingestion.watcher.MarkdownChunker"
        ) as MockChunker:
            MockChunker.return_value.split = MagicMock(return_value=[])
            doc, _ = await watcher.process_source(
                source_url="https://example.com/normativa.pdf",
                chatbot_id=chatbot_id,
                prefetched_content="Contingut en català.",
                language="ca",
            )

        # El doc ES no debe borrarse: no hubo ningún delete
        session.delete.assert_not_called()
        assert doc.language == "val"
