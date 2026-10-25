"""Tests FAQ.2 — una FAQ se cita como FAQ, nunca como norma.

Una respuesta sugerida **no es una norma**. Si se cita con la misma forma que un artículo, se
habrá publicado una respuesta no revisada con la autoridad de la normativa — y eso no se ve al
leer la respuesta, que es lo que lo hace peligroso.

`content_class` ya modela la diferencia (`regulation | faq | generic`) y el CHECK de la tabla
la impone. Lo que faltaba es que llegara hasta la salida: hoy el `content_class` se queda en
`HubDocument` y **no viaja al fragmento**, así que cuando la evidencia llega al grafo nadie
sabe ya si aquello era un artículo o una respuesta orientativa.

El camino es el que ya usan `estat` y `classes` desde el contrato de consolidación:
documento → metadatos del fragmento → `Source.metadata` → `EvidenceItem.metadata` → la cita.
"""
from __future__ import annotations



class TestLaAutoridadViajaConElFragmento:

    def test_should_carry_content_class_from_document_to_chunk_metadata(self):
        """Sin esto, la distinción existe en la base de datos y se pierde por el camino."""
        from server.app.modules.agents_hub.ingestion.chunker import MarkdownChunker

        cuerpo = (
            "# Preguntas frecuentes\n\n"
            "##### ¿Cómo se justifica una dieta? {#faq-1}\n\n"
            "Con el formulario de la unidad.\n"
        )
        chunks = MarkdownChunker().split(
            cuerpo, metadata={"document_id": "d1", "content_class": "faq"}
        )

        assert chunks
        assert all(c.metadata.get("content_class") == "faq" for c in chunks)

    def test_should_not_put_content_class_in_the_embedded_text(self):
        """La taxonomía NUNCA entra en el texto que se embebe (regla del proyecto): si
        entrara, reclasificar obligaría a re-embeber."""
        from server.app.modules.agents_hub.ingestion.chunker import MarkdownChunker

        cuerpo = "##### ¿Una pregunta? {#faq-1}\n\nUna respuesta.\n"
        chunks = MarkdownChunker().split(
            cuerpo, metadata={"document_id": "d1", "content_class": "faq"}
        )

        assert all("faq" not in c.embedding_text.lower() for c in chunks)


class TestLaCitaDistingueLaAutoridad:

    def _fuente(self, content_class: str, **extra):
        from types import SimpleNamespace

        metadata = {"content_class": content_class, "ancora": "faq-1"}
        metadata.update(extra)
        return SimpleNamespace(
            source_id="d1",
            title="Preguntas frecuentes de la UGITJ",
            source_url="https://ejemplo.test/faq",
            score=0.8,
            metadata=metadata,
        )

    def test_should_label_a_faq_source_as_orientative(self):
        from server.app.modules.agents_hub.services.retrieval.citations import (
            etiqueta_de_autoridad,
        )

        assert etiqueta_de_autoridad({"content_class": "faq"}) == "orientativa"

    def test_should_not_label_a_regulation_as_orientative(self):
        from server.app.modules.agents_hub.services.retrieval.citations import (
            etiqueta_de_autoridad,
        )

        assert etiqueta_de_autoridad({"content_class": "regulation"}) is None
        assert etiqueta_de_autoridad({}) is None

    def test_should_expose_the_label_in_the_serialized_source(self):
        """El frontend tiene que poder pintarlo distinto, así que el dato sale en el JSON
        del evento `done` — no solo en el prompt del modelo."""
        from server.app.modules.agents_hub.services.turno_de_chat import _source_to_dict

        serializada = _source_to_dict(self._fuente("faq"))

        assert serializada.get("authority") == "orientativa"

    def test_should_keep_the_existing_shape_for_a_regulation(self):
        """Contrato de CAL.2: el shape que ve el frontend no cambia para lo que ya había."""
        from server.app.modules.agents_hub.services.turno_de_chat import _source_to_dict

        serializada = _source_to_dict(self._fuente("regulation"))

        assert set(serializada) >= {"document_id", "title", "url", "score"}
        assert serializada.get("authority") is None

    def test_should_link_to_the_backing_regulation_when_the_faq_declares_one(self):
        """Lo que hace defendible una respuesta orientativa es poder ir al artículo."""
        from server.app.modules.agents_hub.services.turno_de_chat import _source_to_dict

        serializada = _source_to_dict(
            self._fuente("faq", norma_de_respaldo="https://boe.es/ley#art-5")
        )

        assert serializada.get("backing_url") == "https://boe.es/ley#art-5"


class TestElPromptLoDiceTambien:
    """Que el JSON lo lleve no basta: quien lee la respuesta tiene que enterarse leyéndola,
    no inspeccionando la carga útil."""

    def test_should_mark_faq_evidence_in_the_packed_context(self):
        from server.app.modules.agents_hub.services.retrieval.citations import (
            marcar_autoridad,
        )

        texto = marcar_autoridad(
            "Se justifica con el formulario.", {"content_class": "faq"}
        )

        assert "orientativa" in texto.lower()
        assert "Se justifica con el formulario." in texto

    def test_should_leave_a_regulation_excerpt_untouched(self):
        from server.app.modules.agents_hub.services.retrieval.citations import (
            marcar_autoridad,
        )

        original = "El mandato será de seis años."
        assert marcar_autoridad(original, {"content_class": "regulation"}) == original


class TestTodoEstoEstaEnchufado:
    """Los helpers de arriba no valen de nada si nadie los llama. Estos tests recorren los
    dos puntos del camino real: la ingesta, que es quien pone el metadato, y la construcción
    de la evidencia, que es quien lo convierte en algo que el modelo lee."""

    def test_ingestion_should_put_content_class_in_the_chunk_metadata(self):
        from pathlib import Path

        watcher = Path("app/modules/agents_hub/ingestion/watcher.py").read_text(
            encoding="utf-8"
        )
        assert '"content_class": doc.content_class' in watcher, (
            "la ingesta no pasa content_class al fragmento, así que la distinción se "
            "pierde entre el documento y la evidencia"
        )

    def test_evidence_from_a_faq_source_should_carry_the_warning(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.rag_vector_pipeline import (  # noqa: E501
            _source_to_evidence,
        )
        from server.app.modules.agents_hub.services.retrieval.types import Source
        import uuid

        evidencia = _source_to_evidence(
            Source(
                document_id=uuid.uuid4(),
                title="FAQ",
                url="https://ejemplo.test/faq",
                excerpt="Se justifica con el formulario.",
                score=0.9,
                metadata={"content_class": "faq"},
            )
        )

        assert "orientativa" in evidencia.content.lower()
        assert "Se justifica con el formulario." in evidencia.content

    def test_evidence_from_a_regulation_should_be_untouched(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.rag_vector_pipeline import (  # noqa: E501
            _source_to_evidence,
        )
        from server.app.modules.agents_hub.services.retrieval.types import Source
        import uuid

        evidencia = _source_to_evidence(
            Source(
                document_id=uuid.uuid4(),
                title="Reglamento",
                url="https://ejemplo.test/reg",
                excerpt="El mandato será de seis años.",
                score=0.9,
                metadata={"content_class": "regulation"},
            )
        )

        assert evidencia.content == "El mandato será de seis años."
