"""Tests RAG.7 — contexto jerárquico en el texto que se embebe.

Un fragmento del artículo 14 dice «L'import és de 53,34 euros» y no dice de qué es el
importe, ni de qué norma sale. Embebido así, compite en el espacio vectorial contra
cualquier otro importe del corpus. Con su jerarquía delante —documento › capítulo › artículo—
el mismo fragmento queda anclado a su contexto sin cambiar ni una letra de lo que se muestra
como evidencia.

**La regla dura de este prompt**: en `embedding_text` solo entra contexto **estructural**.
Nunca taxonomía —`ambit_principal`, `submateries`— ni el ancla. Motivo, de CLAUDE.md §5: el
vocabulario está pendiente de validar por Secretaría General y tiene que seguir siendo
revisable; taxonomía embebida significa que cada revisión cuesta un re-embedding del corpus
entero. El ancla, además, es ruido puro para el vector.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

DOCUMENTO = """# Reglament d'indemnitzacions

## Capitol II. Dietes

##### Article 14. Import de la dieta {#art-14 .modificat}

L'import de la dieta es de 53,34 euros per dia complet.
"""


def _chunks(contenido: str = DOCUMENTO, **kwargs):
    from server.app.modules.agents_hub.ingestion.chunker import MarkdownChunker

    return MarkdownChunker().split(contenido, **kwargs)


class TestTextoEmbebido:

    def test_should_build_embedding_text_with_title_and_header_hierarchy(self):
        chunks = _chunks(document_title="Reglament d'indemnitzacions per rao del servei")

        texto = chunks[-1].embedding_text
        assert "Reglament d'indemnitzacions per rao del servei" in texto
        assert "Capitol II. Dietes" in texto
        assert "Article 14" in texto
        # El contenido va detrás de la jerarquía, no mezclado con ella
        assert texto.index("Capitol II") < texto.index("53,34")

    def test_should_not_include_taxonomy_or_anchor_in_embedding_text(self):
        """Lo que sostiene que reclasificar cueste un UPDATE y no un re-embedding."""
        chunks = _chunks(
            document_title="Reglament",
            metadata={
                "document_id": "abc",
                "ambit_principal": "administracio",
                "submateries": ["indemnitzacions-i-dietes"],
            },
        )

        texto = chunks[-1].embedding_text
        assert "administracio" not in texto
        assert "indemnitzacions-i-dietes" not in texto
        assert "art-14" not in texto
        assert "{#" not in texto

    def test_should_not_duplicate_header_when_content_starts_with_it(self):
        """Si el fragmento ya trae sus encabezados, no se le prefijan otra vez.

        Es el caso del PRIMER fragmento de cada sección: desde ING.0.4 el contenido conserva
        sus encabezados, así que repetirlos delante solo sesgaría el vector hacia ellos. Los
        que ganan contexto son los fragmentos siguientes de una sección larga, que sí se
        quedaron sin encabezado al trocear —eso lo cubre el test de la jerarquía.

        Lo que se cuenta es que RAG.7 no AÑADE repeticiones; las que trae el documento
        fuente (`## Article 3` y luego «Article 3. El termini…») no son cosa suya.
        """
        contenido = """# Norma

## Article 3

Article 3. El termini es de 10 dies.
"""
        chunk = _chunks(contenido, document_title="Norma")[-1]

        assert chunk.embedding_text == chunk.content
        assert chunk.embedding_text.count("Article 3") == chunk.content.count("Article 3")

    def test_should_keep_stored_content_unchanged(self):
        """La evidencia que ve el usuario no cambia: `embedding_text` no se persiste.

        Ojo con lo que «no cambia» significa aquí: el contenido **ya incluía sus propios
        encabezados** desde ING.0.4 (`strip_headers=False`). Lo que RAG.7 añade es el título
        del documento y la jerarquía completa, y solo en el texto que se embebe.
        """
        chunks = _chunks(document_title="Reglament d'indemnitzacions per rao del servei")

        ultimo = chunks[-1]
        assert "53,34" in ultimo.content
        assert "per rao del servei" not in ultimo.content, "el título se coló en el contenido"
        assert "embedding_text" not in ultimo.metadata
        assert ultimo.embedding_text != ultimo.content
        assert ultimo.embedding_text.endswith(ultimo.content)

    def test_should_fall_back_to_content_without_hierarchy(self):
        """Sin título ni encabezados no hay contexto que añadir, y no se inventa."""
        texto = _chunks("Texto suelto sin encabezados.")[0].embedding_text

        assert texto.strip() == "Texto suelto sin encabezados."


class TestIngesta:

    @pytest.mark.asyncio
    async def test_should_embed_enriched_text_not_raw_content(self):
        from server.app.modules.agents_hub.database.operational_models import HubDocument
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        session = AsyncMock()
        session.add = MagicMock()

        # Servicio SIN `embed_batch`, que es un caso real (un adaptador que no lo exponga).
        # Con un AsyncMock pelado no valdría: fabrica `embed_batch` sola, el watcher tomaría
        # la vía del lote y este test no comprobaría nada — pasando en verde.
        class _SinLote:
            model_name = "BAAI/bge-m3"
            dimensions = 1024

            def __init__(self) -> None:
                self.textos: list[str] = []

            async def embed(self, text: str) -> list[float]:
                self.textos.append(text)
                return [0.1] * 1024

        embedding = _SinLote()
        watcher = IngestionWatcher(
            session=session, embedding_service=embedding, chatbot_provider=AsyncMock()
        )
        doc = HubDocument(
            id=__import__("uuid").uuid4(), chatbot_id=__import__("uuid").uuid4(),
            title="Reglament d'indemnitzacions", canonical_url="https://uji.es/r",
            markdown_content=DOCUMENTO, content_hash="h" * 64, language="ca",
            source_kind="publicacio",
        )

        await watcher._regenerate_chunks_for_document(doc)

        embebidos = embedding.textos
        assert embebidos, "no se embebio nada"
        assert any("Reglament d'indemnitzacions" in t for t in embebidos), (
            "se embebio el contenido crudo, sin la jerarquia"
        )

    @pytest.mark.asyncio
    async def test_should_embed_chunks_in_batches_when_the_service_supports_it(self):
        """El watcher embebía chunk a chunk. Con lote, una llamada por documento."""
        from server.app.modules.agents_hub.database.operational_models import HubDocument
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        session = AsyncMock()
        session.add = MagicMock()
        embedding = AsyncMock()
        embedding.embed = AsyncMock(return_value=[0.1] * 1024)
        # Un vector por texto, como el servicio de verdad: con un número fijo, el `zip` del
        # watcher truncaba en silencio y se guardaban menos fragmentos de los troceados.
        embedding.embed_batch = AsyncMock(side_effect=lambda textos, **_: [[0.1] * 1024 for _ in textos])
        embedding.model_name = "BAAI/bge-m3"
        embedding.dimensions = 1024

        watcher = IngestionWatcher(
            session=session, embedding_service=embedding, chatbot_provider=AsyncMock()
        )
        doc = HubDocument(
            id=__import__("uuid").uuid4(), chatbot_id=__import__("uuid").uuid4(),
            title="Norma", canonical_url="https://uji.es/n",
            markdown_content=DOCUMENTO, content_hash="h" * 64, language="ca",
            source_kind="publicacio",
        )

        await watcher._regenerate_chunks_for_document(doc)

        assert embedding.embed_batch.await_count == 1
        assert embedding.embed.await_count == 0

    def test_should_expose_batch_embedding_on_the_local_service(self):
        from server.app.modules.agents_hub.services.embedding_service import (
            LocalEmbeddingService,
        )

        assert hasattr(LocalEmbeddingService(), "embed_batch")


class TestHookDeEnriquecimiento:
    """Nivel 2 de contextual retrieval: se define el protocolo, no se implementa."""

    def test_should_use_a_noop_enricher_by_default(self):
        from server.app.modules.agents_hub.ingestion.chunker import (
            ContextEnricher,
            NoopEnricher,
        )

        enricher = NoopEnricher()
        assert isinstance(enricher, ContextEnricher)
        assert enricher.enrich("cualquier documento", "un chunk") == ""

    def test_should_prepend_the_enricher_output_when_it_returns_something(self):
        """Sin esto, el hook sería decorado: hay que poder comprobar que se consume."""
        from server.app.modules.agents_hub.ingestion.chunker import MarkdownChunker

        class _Enricher:
            def enrich(self, document: str, chunk: str) -> str:
                return "Este fragmento trata de dietas."

        chunks = MarkdownChunker(enricher=_Enricher()).split(
            DOCUMENTO, document_title="Reglament"
        )

        assert "Este fragmento trata de dietas." in chunks[-1].embedding_text
        assert "Este fragmento trata de dietas." not in chunks[-1].content
