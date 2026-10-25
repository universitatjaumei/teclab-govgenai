"""Tests de la nueva logica de ingestión: IngestionWatcher crea HubDocument.

Verifica el contrato del Prompt 9CBis.8:
  - process_source crea/actualiza HubDocument (unidad citable)
  - en modo vector genera chunks; en long_context/agentic no
  - idempotencia por content_hash
  - re-ingestión con contenido diferente reemplaza doc y chunks
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_session_for_new_doc() -> AsyncMock:
    """Sesión que devuelve None en el query de idempotencia (doc nuevo)."""
    session = AsyncMock()
    # Primera execute → HubDocument idempotency check (scalar_one_or_none=None)
    # Segunda execute → old docs by canonical_url (scalars=[])
    first_exec = MagicMock()
    first_exec.scalar_one_or_none = MagicMock(return_value=None)
    second_exec = MagicMock()
    second_exec.scalars = MagicMock(return_value=iter([]))
    third_exec = MagicMock()  # DELETE chunks
    # Aquí había un `fourth_exec` para «DELETE old chunks» que nadie usaba: el
    # `side_effect` de abajo sólo lista tres respuestas. No era una aserción perdida,
    # era el doble de un cuarto `execute` que el código dejó de hacer.
    session.begin_nested = MagicMock(return_value=AsyncMock())
    # RAG.8: el watcher consulta la config de troceado; sin chatbot en BD, la cascada
    # devuelve los defaults de plataforma, que es el camino realista para estos tests.
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock(side_effect=[first_exec, second_exec, third_exec])
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_session_for_existing_doc(existing_doc) -> AsyncMock:
    """Sesión que devuelve un HubDocument existente (mismo hash)."""
    session = AsyncMock()
    first_exec = MagicMock()
    first_exec.scalar_one_or_none = MagicMock(return_value=existing_doc)
    second_exec = MagicMock()  # DELETE chunks for vector
    session.execute = AsyncMock(side_effect=[first_exec, second_exec])
    session.begin_nested = MagicMock(return_value=AsyncMock())
    # RAG.8: el watcher consulta la config de troceado; sin chatbot en BD, la cascada
    # devuelve los defaults de plataforma, que es el camino realista para estos tests.
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_chatbot_provider(retrieval_mode: str = "RAG") -> AsyncMock:
    provider = AsyncMock()
    provider.get_retrieval_mode = AsyncMock(return_value=retrieval_mode)
    return provider


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestIngestionCreatesDocuments:

    async def test_upload_creates_hub_document_with_extracted_title(self):
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        session = _make_session_for_new_doc()
        chatbot_provider = _make_chatbot_provider("RAG")
        embedding_svc = AsyncMock()
        embedding_svc.embed = AsyncMock(return_value=[0.1] * 1024)
        # RAG.7: explícito, porque un AsyncMock pelado fabrica embed_batch y devuelve algo
        # que no es una lista de vectores (el watcher no crearía ningún chunk).
        embedding_svc.embed_batch = AsyncMock(side_effect=lambda ts: [[0.1] * 1024] * len(ts))

        watcher = IngestionWatcher(
            session=session,
            embedding_service=embedding_svc,
            chatbot_provider=chatbot_provider,
        )

        doc, _ = await watcher.process_source(
            source_url="https://ej.com/norma.pdf",
            chatbot_id=uuid.uuid4(),
            prefetched_content="# Norma Municipal\n\nArticulo 1. El plazo es 30 dias.",
        )

        assert isinstance(doc, HubDocument)
        assert doc.title == "Norma Municipal"

    async def test_upload_in_vector_mode_creates_chunks(self):
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        session = _make_session_for_new_doc()
        chatbot_provider = _make_chatbot_provider("RAG")
        embedding_svc = AsyncMock()
        embedding_svc.embed = AsyncMock(return_value=[0.1] * 1024)
        # RAG.7: explícito, porque un AsyncMock pelado fabrica embed_batch y devuelve algo
        # que no es una lista de vectores (el watcher no crearía ningún chunk).
        embedding_svc.embed_batch = AsyncMock(side_effect=lambda ts: [[0.1] * 1024] * len(ts))

        watcher = IngestionWatcher(
            session=session,
            embedding_service=embedding_svc,
            chatbot_provider=chatbot_provider,
        )

        _, n_chunks = await watcher.process_source(
            source_url="https://ej.com/norma.pdf",
            chatbot_id=uuid.uuid4(),
            prefetched_content="# Norma\n\n" + "Texto. " * 100,
        )

        assert n_chunks >= 1
        session.add.assert_called()

    async def test_upload_in_long_context_mode_skips_chunks(self):
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        session = _make_session_for_new_doc()
        chatbot_provider = _make_chatbot_provider("MD_LONG_CONTEXT")
        embedding_svc = AsyncMock()

        watcher = IngestionWatcher(
            session=session,
            embedding_service=embedding_svc,
            chatbot_provider=chatbot_provider,
        )

        _, n_chunks = await watcher.process_source(
            source_url="https://ej.com/norma.pdf",
            chatbot_id=uuid.uuid4(),
            prefetched_content="# Norma\n\nTexto completo.",
        )

        assert n_chunks == 0
        embedding_svc.embed.assert_not_called()

    async def test_upload_in_agentic_mode_also_chunks(self):
        """ACT.8 — era `..._skips_chunks`, y ese «skip» era el defecto.

        El agentico busca por fragmentos con `search_knowledge`, asi que saltarselos dejaba su
        indice ciego a todo lo que se ingiriera. Y como la rama que no trocea BORRA, se habria
        ido vaciando norma a norma segun se actualizaran.
        """
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        session = _make_session_for_new_doc()
        chatbot_provider = _make_chatbot_provider("MD_AGENT_SELECTOR")
        embedding_svc = AsyncMock()
        # Un vector por texto: con el lote que fabrica un `AsyncMock` pelado, el `zip` del watcher
        # truncaba a cero y el test pasaba sin guardar un solo fragmento (#275, `strict=True`).
        embedding_svc.embed_batch = AsyncMock(
            side_effect=lambda textos, **_: [[0.1] * 1024 for _ in textos]
        )

        watcher = IngestionWatcher(
            session=session,
            embedding_service=embedding_svc,
            chatbot_provider=chatbot_provider,
        )

        _, n_chunks = await watcher.process_source(
            source_url="https://ej.com/norma.pdf",
            chatbot_id=uuid.uuid4(),
            prefetched_content="# Norma\n\nTexto.",
        )

        # Se afirma sobre los fragmentos y no sobre `embed`: el watcher embebe por lote
        # (`embed_para_indexar`), y un `AsyncMock` fabrica el metodo que se le pida, asi que
        # exigir `embed` seria afirmar un detalle de implementacion que hoy no es cierto.
        assert n_chunks > 0

    async def test_re_upload_same_content_is_idempotent(self):
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        existing_doc = MagicMock(spec=HubDocument)
        existing_doc.id = uuid.uuid4()
        existing_doc.chatbot_id = uuid.uuid4()
        existing_doc.markdown_content = "# Norma\n\nTexto."
        existing_doc.canonical_url = "https://ej.com/norma.pdf"
        existing_doc.language = "es"

        session = _make_session_for_existing_doc(existing_doc)
        chatbot_provider = _make_chatbot_provider("RAG")
        embedding_svc = AsyncMock()
        embedding_svc.embed = AsyncMock(return_value=[0.1] * 1024)
        # RAG.7: explícito, porque un AsyncMock pelado fabrica embed_batch y devuelve algo
        # que no es una lista de vectores (el watcher no crearía ningún chunk).
        embedding_svc.embed_batch = AsyncMock(side_effect=lambda ts: [[0.1] * 1024] * len(ts))

        watcher = IngestionWatcher(
            session=session,
            embedding_service=embedding_svc,
            chatbot_provider=chatbot_provider,
        )

        doc, _ = await watcher.process_source(
            source_url="https://ej.com/norma.pdf",
            chatbot_id=existing_doc.chatbot_id,
            prefetched_content="# Norma\n\nTexto.",
        )

        # Returns existing doc, does not create new one
        assert doc is existing_doc

    async def test_process_source_returns_hub_document_instance(self):
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        session = _make_session_for_new_doc()
        watcher = IngestionWatcher(
            session=session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )
        result = await watcher.process_source(
            source_url="https://ej.com/doc.pdf",
            chatbot_id=uuid.uuid4(),
            prefetched_content="# Doc\n\nContenido.",
        )
        doc, n_chunks = result
        assert isinstance(doc, HubDocument)

    async def test_process_source_without_provider_defaults_to_rag(self):
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        session = _make_session_for_new_doc()
        embedding_svc = AsyncMock()
        embedding_svc.embed = AsyncMock(return_value=[0.1] * 1024)
        # RAG.7: explícito, porque un AsyncMock pelado fabrica embed_batch y devuelve algo
        # que no es una lista de vectores (el watcher no crearía ningún chunk).
        embedding_svc.embed_batch = AsyncMock(side_effect=lambda ts: [[0.1] * 1024] * len(ts))

        watcher = IngestionWatcher(
            session=session,
            embedding_service=embedding_svc,
            # No chatbot_provider
        )

        _, n_chunks = await watcher.process_source(
            source_url="https://ej.com/doc.pdf",
            chatbot_id=uuid.uuid4(),
            prefetched_content="# Doc\n\nContenido largo. " * 20,
        )

        assert n_chunks >= 1


@pytest.mark.asyncio
class TestMarkdownUtils:

    def test_extract_title_returns_first_h1(self):
        from server.app.modules.agents_hub.ingestion.markdown_utils import extract_title_from_markdown
        content = "# Norma Municipal\n\nArt 1. Texto."
        assert extract_title_from_markdown(content) == "Norma Municipal"

    def test_extract_title_returns_none_when_no_h1(self):
        from server.app.modules.agents_hub.ingestion.markdown_utils import extract_title_from_markdown
        content = "Texto sin titulo de nivel 1."
        assert extract_title_from_markdown(content) is None

    def test_estimate_tokens_is_positive(self):
        from server.app.modules.agents_hub.ingestion.markdown_utils import estimate_tokens
        assert estimate_tokens("Texto de prueba") > 0

    def test_estimate_tokens_is_length_over_four(self):
        from server.app.modules.agents_hub.ingestion.markdown_utils import estimate_tokens
        content = "A" * 400
        assert estimate_tokens(content) == 100


@pytest.mark.asyncio
class TestPuenteBilingueEnLaIngesta:
    """RAG.4: el puente léxico lo copia la ingesta del documento al chunk.

    Se prueba aparte del `tsvector` porque son dos fallos distintos y con síntomas
    distintos: si el puente no se copia, la búsqueda no revienta — deja de encontrar
    'despesa' en silencio, que es la peor forma de fallar.
    """

    async def test_should_derive_bilingual_terms_from_document_metadata(self):
        from server.app.modules.agents_hub.ingestion.bilingual_bridge import (
            terminos_bilingues,
        )

        doc = SimpleNamespace(
            doc_metadata={"termes_bilingues": ["despesa/gasto", "dieta"]}
        )

        # La barra no la entiende el parser de full-text: lo que hace de puente es que
        # ambas formas queden indexadas como palabras sueltas.
        assert terminos_bilingues(doc) == "despesa gasto dieta"

    async def test_should_return_none_when_document_declares_no_pairs(self):
        from server.app.modules.agents_hub.ingestion.bilingual_bridge import (
            terminos_bilingues,
        )

        assert terminos_bilingues(SimpleNamespace(doc_metadata={})) is None
        assert terminos_bilingues(SimpleNamespace(doc_metadata=None)) is None
        assert terminos_bilingues(
            SimpleNamespace(doc_metadata={"termes_bilingues": "no-es-una-lista"})
        ) is None

    async def test_should_write_bilingual_terms_when_chunking_a_labelled_document(self):
        """Reingesta de un documento que YA tiene los pares: el chunk nace con el puente."""
        from server.app.modules.agents_hub.database.operational_models import (
            HubDocument,
            HubDocumentChunk,
        )
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        session = _make_session_for_new_doc()
        embedding_svc = AsyncMock()
        embedding_svc.embed = AsyncMock(return_value=[0.1] * 1024)
        # RAG.7: explícito, porque un AsyncMock pelado fabrica embed_batch y devuelve algo
        # que no es una lista de vectores (el watcher no crearía ningún chunk).
        embedding_svc.embed_batch = AsyncMock(side_effect=lambda ts: [[0.1] * 1024] * len(ts))
        watcher = IngestionWatcher(
            session=session,
            embedding_service=embedding_svc,
            chatbot_provider=_make_chatbot_provider("RAG"),
        )

        doc = HubDocument(
            id=uuid.uuid4(),
            chatbot_id=uuid.uuid4(),
            title="Norma",
            canonical_url="https://ej.com/norma.pdf",
            markdown_content="# Norma\n\nLa ejecucion del gasto se autoriza.",
            content_hash="h" * 64,
            language="es",
            source_kind="publicacio",
            doc_metadata={"termes_bilingues": ["despesa/gasto"]},
        )

        await watcher._regenerate_chunks_for_document(doc)

        chunks = [
            c.args[0]
            for c in session.add.call_args_list
            if isinstance(c.args[0], HubDocumentChunk)
        ]
        assert chunks, "no se creo ningun chunk"
        assert all(c.bilingual_terms == "despesa gasto" for c in chunks)
