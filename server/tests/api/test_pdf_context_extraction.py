"""Tests EXT.2 — el contexto temporal se extrae con pdfplumber, y un escaneado falla en alto.

Las dos vías de **contexto** —el PDF que una persona sube para preguntarle cosas y el que
entra como fuente de un informe de redacción— convertían con Docling. `pdfplumber` ya es
dependencia directa (`pyproject.toml:44`), así que el cambio no añade nada y retira los
modelos de layout y RapidOCR.

Aquí sí se puede: la persona tiene el documento delante y ve en la respuesta si la extracción
salió regular. En el corpus no, y por eso EXT.1 cerró esa puerta.

**Lo que hace aceptable perder OCR** es la guarda: sin capa de texto, pdfplumber devuelve
poco o nada, y eso NO puede ingerirse en silencio. Un documento vacío que nadie ve es la
avería muda que esta auditoría ya encontró tres veces. El umbral es **por página**: un PDF de
80 páginas con 200 caracteres está tan vacío como uno de 1 con 0.
"""
from __future__ import annotations

import io

import pytest


def _pdf_con_texto(paginas: int = 1, texto: str = "Contenido de prueba " * 30) -> bytes:
    """PDF digital mínimo, generado con reportlab (ya es dependencia: lo usa hub_tasks)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    for _ in range(paginas):
        y = 800
        for trozo in [texto[i : i + 90] for i in range(0, len(texto), 90)]:
            c.drawString(50, y, trozo)
            y -= 14
            if y < 50:
                break
        c.showPage()
    c.save()
    return buffer.getvalue()


def _pdf_sin_texto(paginas: int = 1) -> bytes:
    """PDF con páginas en blanco: lo que produce un escaneado sin OCR."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    for _ in range(paginas):
        c.showPage()
    c.save()
    return buffer.getvalue()


class TestElExtractorCompartido:
    """Uno solo, no dos copias: el umbral y el aviso tienen que ser los mismos para las dos
    vías, y dos implementaciones acaban divergiendo justo en el caso raro."""

    def test_should_extract_text_from_a_digital_pdf(self):
        from server.app.core.pdf_text import extraer_texto_de_pdf

        texto = extraer_texto_de_pdf(_pdf_con_texto())

        assert "Contenido de prueba" in texto

    def test_should_reject_a_scanned_pdf(self):
        from server.app.core.pdf_text import PdfSinCapaDeTexto, extraer_texto_de_pdf

        with pytest.raises(PdfSinCapaDeTexto):
            extraer_texto_de_pdf(_pdf_sin_texto())

    def test_should_use_a_per_page_threshold_not_an_absolute_one(self):
        """Un PDF largo con una frase suelta está tan vacío como uno corto sin nada. Con un
        umbral absoluto, ese caso —el escaneado con una marca de agua reconocible— pasaría."""
        from server.app.core.pdf_text import PdfSinCapaDeTexto, extraer_texto_de_pdf

        casi_vacio = _pdf_con_texto(paginas=40, texto="Sello registro")

        with pytest.raises(PdfSinCapaDeTexto):
            extraer_texto_de_pdf(casi_vacio)

    def test_should_accept_a_short_but_genuinely_textual_document(self):
        """La guarda no puede rechazar un documento corto legítimo: una diligencia de una
        página con un par de párrafos es exactamente lo que la gente sube."""
        from server.app.core.pdf_text import extraer_texto_de_pdf

        texto = extraer_texto_de_pdf(_pdf_con_texto(paginas=1))

        assert len(texto) > 0

    def test_should_say_what_to_do_not_just_that_it_failed(self):
        """El mensaje lo lee una persona: «extraction failed» no le dice nada."""
        from server.app.core.pdf_text import PdfSinCapaDeTexto, extraer_texto_de_pdf

        with pytest.raises(PdfSinCapaDeTexto) as exc:
            extraer_texto_de_pdf(_pdf_sin_texto())

        mensaje = str(exc.value).lower()
        assert "escane" in mensaje or "capa de texto" in mensaje


class TestNadieConvierteConDocling:

    def test_user_upload_path_should_not_import_docling(self):
        from pathlib import Path

        watcher = Path("app/modules/agents_hub/ingestion/watcher.py").read_text(
            encoding="utf-8"
        )
        assert "DoclingProcessor" not in watcher, (
            "el contexto temporal del usuario sigue convirtiendo con Docling"
        )

    def test_redaccion_pipeline_should_not_import_docling(self):
        from pathlib import Path

        pipeline = Path(
            "app/modules/redaccion/pipelines/pdf_text_pipeline.py"
        ).read_text(encoding="utf-8")
        assert "import docling" not in pipeline, "el pipeline de PDF de redacción sigue usando Docling"
        assert "from docling" not in pipeline, "el pipeline de PDF de redacción sigue usando Docling"


class TestElContratoDeRedaccionNoCambia:
    """Docling se usaba SIN OCR, así que lo que produce el pipeline no debe cambiar de
    forma: mismo `ExtractionResult`, mismo aviso cuando no hay capa de texto."""

    def _extraer(self, datos: bytes, tmp_path):
        from server.app.modules.redaccion.pipelines.contracts import ExtractionInput
        from server.app.modules.redaccion.pipelines.pdf_text_pipeline import (
            PDFTextExtractionPipeline,
        )
        from server.app.modules.redaccion.pipelines.contracts import StorageRef

        fichero = tmp_path / "doc.pdf"
        fichero.write_bytes(datos)

        pipeline = PDFTextExtractionPipeline()
        return pipeline.extract(
            ExtractionInput(
                source_kind="pdf_text",
                file_ref=StorageRef(bucket=str(tmp_path), key="doc.pdf"),
            )
        )

    def test_should_return_free_text_and_pages_for_a_digital_pdf(self, tmp_path):
        resultado = self._extraer(_pdf_con_texto(paginas=2), tmp_path)

        assert resultado.free_text
        assert resultado.document is not None
        assert len(resultado.document.pages) == 2
        assert resultado.provenance.pipeline_id == "pdf_text_pipeline_v1"

    def test_should_emit_non_extractable_warning_for_a_scanned_pdf(self, tmp_path):
        """El pipeline avisa en vez de lanzar: el informe puede tener otras fuentes, y
        quien lo revisa necesita ver cuál falló, no perder la ejecución entera."""
        resultado = self._extraer(_pdf_sin_texto(paginas=2), tmp_path)

        codigos = [w.code for w in resultado.warnings]
        assert "NON_EXTRACTABLE_PDF" in codigos
        assert resultado.free_text is None

    def test_should_keep_the_extraction_strategy_field(self, tmp_path):
        resultado = self._extraer(_pdf_con_texto(), tmp_path)

        assert resultado.document.extraction_strategy in (
            "text_linear",
            "complex_tables",
        )
