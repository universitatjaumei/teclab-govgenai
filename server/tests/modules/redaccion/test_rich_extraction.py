"""Extracción enriquecida de PDF — 9R.5.9 (RED → GREEN), sobre pdfplumber desde EXT.2.

Cubre:
  1-4.  Nuevos modelos ExtractedCell / ExtractedTableRich / ExtractedPage / ExtractedDocument.
  5.    ExtractionResult ahora tiene campo `document`.
  6-9.  PDFTextExtractionPipeline produce ExtractedDocument con páginas, tablas ricas,
        heurística extraction_strategy y coordenadas bbox.
  10.   DeterministicExtractionNode envuelve pipeline.extract() con asyncio.to_thread y
        serializa `document` en block.content.
  11-12.AIAssistDraftNode prefiere document.markdown y añade tables_json en complex_tables.
  13.   CitationAndTraceabilityNode rellena Citation.page desde el documento enriquecido.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from server.app.modules.redaccion.contracts.runtime import (
    BlockState,
    WorkspaceState,
)
from server.app.modules.redaccion.graph.nodes.ai_assist_draft import AIAssistDraftNode
from server.app.modules.redaccion.graph.nodes.citation_traceability import (
    CitationAndTraceabilityNode,
)
from server.app.modules.redaccion.graph.nodes.deterministic_extraction import (
    DeterministicExtractionNode,
)
from server.app.modules.redaccion.pipelines.contracts import (
    ExtractedCell,
    ExtractedDocument,
    ExtractedPage,
    ExtractedTableRich,
    ExtractionInput,
    ExtractionProvenance,
    ExtractionResult,
    StorageRef,
)
from server.app.modules.redaccion.pipelines.pdf_text_pipeline import (
    PDFTextExtractionPipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_cell_mock(
    text: str,
    # Las cuatro coordenadas de la caja. Se renombran las cuatro y no sólo la `l` —que es la
    # que `E741` señala por confundirse con un `1`— porque una firma con tres letras y una
    # palabra se lee peor que cuatro palabras. El `.l` de la biblioteca sigue llamándose `.l`,
    # y eso se ve en la línea de asignación de abajo, que es donde hace falta saberlo.
    izquierda: float = 10.0,
    arriba: float = 20.0,
    derecha: float = 110.0,
    abajo: float = 40.0,
    col_span: int = 1,
    row_span: int = 1,
) -> MagicMock:
    cell = MagicMock()
    cell.text = text
    cell.col_span = col_span
    cell.row_span = row_span
    bbox = MagicMock()
    bbox.l, bbox.t, bbox.r, bbox.b = izquierda, arriba, derecha, abajo
    cell.bbox = bbox
    return cell


def _make_table_mock(
    page_no: int,
    grid: list[list[Any]],
    izquierda: float = 0.0,
    arriba: float = 0.0,
    derecha: float = 500.0,
    abajo: float = 200.0,
) -> MagicMock:
    tbl = MagicMock()
    prov = MagicMock()
    prov.page_no = page_no
    bbox = MagicMock()
    bbox.l, bbox.t, bbox.r, bbox.b = izquierda, arriba, derecha, abajo
    prov.bbox = bbox
    tbl.prov = [prov]
    data = MagicMock()
    data.grid = grid
    tbl.data = data
    return tbl


def _make_conv_result(
    num_pages: int = 1,
    markdown: str = "Some **text** content.",
    tables: list | None = None,
) -> MagicMock:
    conv = MagicMock()
    doc = MagicMock()
    doc.num_pages.return_value = num_pages
    doc.export_to_markdown.return_value = markdown
    doc.tables = tables or []
    conv.document = doc
    return conv


def _block_state(block_id: str, kind: str = "DETERMINISTIC_DATA", status: str = "draft") -> BlockState:
    return BlockState(
        block_id=block_id,
        kind=kind,
        status=status,
        last_updated_by="system",
        updated_at=_now(),
    )



# ---------------------------------------------------------------------------
# 1. ExtractedCell model
# ---------------------------------------------------------------------------

def test_extracted_cell_defaults():
    cell = ExtractedCell(text="hello")
    assert cell.text == "hello"
    assert cell.bbox is None
    assert cell.col_span == 1
    assert cell.row_span == 1


def test_extracted_cell_with_bbox():
    cell = ExtractedCell(text="val", bbox=(10.0, 20.0, 110.0, 40.0), col_span=2, row_span=1)
    assert cell.bbox == (10.0, 20.0, 110.0, 40.0)
    assert cell.col_span == 2


# ---------------------------------------------------------------------------
# 2. ExtractedTableRich model
# ---------------------------------------------------------------------------

def test_extracted_table_rich_structure():
    rich_tbl = ExtractedTableRich(
        name="table_1",
        headers=["A", "B"],
        rows=[[ExtractedCell(text="x"), ExtractedCell(text="y")]],
        source_page=2,
        bbox=(0.0, 0.0, 500.0, 200.0),
    )
    assert rich_tbl.source_page == 2
    assert len(rich_tbl.rows[0]) == 2
    assert rich_tbl.rows[0][0].text == "x"


# ---------------------------------------------------------------------------
# 3. ExtractedPage model
# ---------------------------------------------------------------------------

def test_extracted_page_model():
    page = ExtractedPage(page_num=1, markdown="# Page 1")
    assert page.page_num == 1
    assert page.markdown == "# Page 1"
    assert page.tables == []


# ---------------------------------------------------------------------------
# 4. ExtractedDocument model
# ---------------------------------------------------------------------------

def test_extracted_document_defaults():
    doc = ExtractedDocument()
    assert doc.pages == []
    assert doc.markdown == ""
    assert doc.extraction_strategy == "text_linear"


def test_extracted_document_complex_strategy():
    doc = ExtractedDocument(markdown="big table doc", extraction_strategy="complex_tables")
    assert doc.extraction_strategy == "complex_tables"


# ---------------------------------------------------------------------------
# 5. ExtractionResult has document field
# ---------------------------------------------------------------------------

def test_extraction_result_document_field_defaults_none():
    result = ExtractionResult(
        provenance=ExtractionProvenance(
            pipeline_id="test",
            source_ref="bucket/key.pdf",
            extracted_at=_now(),
        )
    )
    assert result.document is None


def test_extraction_result_document_roundtrip():
    doc = ExtractedDocument(
        markdown="# Report",
        extraction_strategy="text_linear",
        pages=[ExtractedPage(page_num=1, markdown="# Report")],
    )
    result = ExtractionResult(
        free_text="Report",
        provenance=ExtractionProvenance(
            pipeline_id="test",
            source_ref="bucket/key.pdf",
            extracted_at=_now(),
        ),
        document=doc,
    )
    dumped = result.model_dump()
    assert dumped["document"]["extraction_strategy"] == "text_linear"
    assert dumped["document"]["pages"][0]["page_num"] == 1
# ---------------------------------------------------------------------------
# 6-9. PDFTextExtractionPipeline sobre PDFs REALES (EXT.2)
# ---------------------------------------------------------------------------
#
# Estos cuatro tests doblaban el `DocumentConverter` de Docling y le hacian devolver un
# documento inventado: lo que comprobaban, en realidad, era el doble. Al pasar el pipeline a
# pdfplumber (EXT.2) el doble dejo de tener sentido, y la sustitucion honesta es ejercitar el
# pipeline contra PDFs de verdad — que ademas es lo unico que puede cazar un cambio de
# comportamiento de la libreria.


def _pdf(texto: str, paginas: int = 1) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    import io as _io

    buffer = _io.BytesIO()
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


def _extraer(datos: bytes, tmp_path):
    fichero = tmp_path / "report.pdf"
    fichero.write_bytes(datos)
    pipeline = PDFTextExtractionPipeline()
    return pipeline.extract(
        ExtractionInput(
            source_kind="pdf_text",
            file_ref=StorageRef(bucket=str(tmp_path), key="report.pdf"),
        )
    )


def test_pdf_pipeline_builds_extracted_document(tmp_path):
    result = _extraer(_pdf("Informe de prueba. " * 20, paginas=2), tmp_path)

    assert result.document is not None
    assert "Informe de prueba" in result.document.markdown
    assert len(result.document.pages) == 2
    assert result.document.pages[0].page_num == 1


def test_pdf_pipeline_strategy_text_linear(tmp_path):
    """Sin tablas, la estrategia es lineal: es lo que orienta al AIAssistDraftNode."""
    result = _extraer(_pdf("Texto corrido sin tablas. " * 20), tmp_path)

    assert result.document.extraction_strategy == "text_linear"


def test_pdf_pipeline_reports_provenance_pages(tmp_path):
    result = _extraer(_pdf("Contenido. " * 20, paginas=3), tmp_path)

    assert result.provenance.pages == [1, 2, 3]
    assert result.provenance.pipeline_id == "pdf_text_pipeline_v1"


def test_pdf_pipeline_warns_on_a_pdf_without_text_layer(tmp_path):
    """El pipeline AVISA en vez de lanzar: un informe puede tener otras fuentes, y quien lo
    revisa necesita ver cual fallo en lugar de perder la ejecucion entera."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    import io as _io

    buffer = _io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.showPage()
    c.save()

    result = _extraer(buffer.getvalue(), tmp_path)

    assert [w.code for w in result.warnings] == ["NON_EXTRACTABLE_PDF"]
    assert result.free_text is None



# ---------------------------------------------------------------------------
# 10. DeterministicExtractionNode wraps extract() with asyncio.to_thread
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deterministic_node_serializes_document_in_content():
    """DeterministicExtractionNode serializes ExtractionResult.document into block content."""
    from server.app.modules.redaccion.contracts.blocks import DeterministicDataBlock
    from server.app.modules.redaccion.contracts.inputs import InputContract, InputSlot
    from server.app.modules.redaccion.contracts.template import (
        AIBlockPolicy,
        ExportPolicy,
        ReportTemplateSpec,
        ReviewPolicy,
    )
    from server.app.modules.redaccion.contracts.ui import ReportUIContract

    rich_doc = ExtractedDocument(
        markdown="# Report",
        extraction_strategy="text_linear",
        pages=[ExtractedPage(page_num=1, markdown="# Report")],
    )
    mock_pipeline = MagicMock()
    mock_pipeline.extract.return_value = ExtractionResult(
        free_text="Report",
        provenance=ExtractionProvenance(
            pipeline_id="pdf_text_pipeline_v1",
            source_ref="bucket/file.pdf",
            extracted_at=_now(),
        ),
        document=rich_doc,
    )
    mock_factory = MagicMock()
    mock_factory.get.return_value = mock_pipeline

    block_contract = DeterministicDataBlock(
        id="b1",
        title="PDF Block",
        source_pipeline="pdf_text",
        depends_on=[],
    )
    spec = ReportTemplateSpec(
        sections=[],
        blocks=[block_contract],
        input_contract=InputContract(
            required_slots=[InputSlot(slot_id="pdf_slot", kind="pdf", label={"es": "PDF"})],
            optional_slots=[],
        ),
        ui_contract=ReportUIContract(
            wizard_steps=[], dropzones=[], manual_fields=[],
            block_editor_enabled=False, ai_review_panel_enabled=False,
            preview_layout="markdown",
        ),
        ai_block_policy=AIBlockPolicy.ALLOWED,
        review_policy=ReviewPolicy.NONE,
        export_policy=ExportPolicy.DOCX,
    )

    blocks = {"b1": _block_state("b1", "DETERMINISTIC_DATA")}
    state = WorkspaceState(
        workspace_id=uuid4(),
        template_version_id=uuid4(),
        report_profile="ANNUAL_REPORT",
        inputs={},
        blocks=blocks,
        status="extracting",
        warnings=[],
        spec=spec,
        artifacts_normalized={"pdf_slot": "bucket/file.pdf"},
    )

    node = DeterministicExtractionNode(mock_factory)
    result = await node(state)

    assert result["blocks"]["b1"].status == "extracted"
    content = result["blocks"]["b1"].content
    assert content is not None
    assert content.get("document") is not None
    assert content["document"]["extraction_strategy"] == "text_linear"
    assert content["document"]["pages"][0]["page_num"] == 1


# ---------------------------------------------------------------------------
# 11. AIAssistDraftNode prefers document.markdown over free_text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_assist_prefers_document_markdown():
    received_contexts: list[str] = []

    class FakeLLM:
        model_name = "test-model"

        async def generate(self, prompt: str, context: str) -> str:
            received_contexts.append(context)
            return "AI output"

    from server.app.modules.redaccion.contracts.blocks import AIAssistedTextBlock

    ai_block_contract = AIAssistedTextBlock(
        id="ai_b1",
        title="AI Block",
        ai_prompt_template_id="tmpl_v1",
        review_policy_id="policy_default",
        depends_on=[],
    )
    spec_obj = MagicMock()
    spec_obj.blocks = [ai_block_contract]

    doc_markdown = "# Rich Document Markdown\n\nThis is the document content from docling."
    source_block = _block_state("src_b1", "DETERMINISTIC_DATA", "extracted")
    source_block = source_block.model_copy(update={
        "content": {
            "free_text": "plain fallback text",
            "document": {
                "markdown": doc_markdown,
                "extraction_strategy": "text_linear",
                "pages": [],
            },
        }
    })

    ai_block = _block_state("ai_b1", "AI_ASSISTED_TEXT", "draft")

    blocks = {"src_b1": source_block, "ai_b1": ai_block}
    state = WorkspaceState.model_construct(
        workspace_id=uuid4(),
        template_version_id=uuid4(),
        report_profile="ANNUAL_REPORT",
        inputs={},
        blocks=blocks,
        block_outputs={},
        status="drafting",
        warnings=[],
        spec=spec_obj,
        artifacts_normalized={},
        user_edits={},
        regenerate_blocks=set(),
        skip_blocks=set(),
    )

    node = AIAssistDraftNode(FakeLLM())
    result = await node(state)

    assert result["blocks"]["ai_b1"].status == "ai_generated"
    assert len(received_contexts) == 1
    assert doc_markdown[:200] in received_contexts[0]
    assert "plain fallback text" not in received_contexts[0]


# ---------------------------------------------------------------------------
# 12. AIAssistDraftNode includes tables_json for complex_tables strategy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_assist_includes_tables_json_for_complex_tables():
    received_contexts: list[str] = []

    class FakeLLM:
        model_name = "test-model"

        async def generate(self, prompt: str, context: str) -> str:
            received_contexts.append(context)
            return "AI output"

    from server.app.modules.redaccion.contracts.blocks import AIAssistedTextBlock

    ai_block_contract = AIAssistedTextBlock(
        id="ai_b1",
        title="AI Block",
        ai_prompt_template_id="tmpl_v1",
        review_policy_id="policy_default",
        depends_on=[],
    )
    spec_obj = MagicMock()
    spec_obj.blocks = [ai_block_contract]

    tables_data = [
        {
            "name": "table_1",
            "headers": ["Col A", "Col B"],
            "rows": [[{"text": "1", "bbox": None, "col_span": 1, "row_span": 1}]],
            "source_page": 1,
            "bbox": None,
        }
    ]
    source_block = _block_state("src_b1", "DETERMINISTIC_DATA", "extracted")
    source_block = source_block.model_copy(update={
        "content": {
            "free_text": "text",
            "document": {
                "markdown": "# Table heavy doc",
                "extraction_strategy": "complex_tables",
                "pages": [{"page_num": 1, "markdown": "", "tables": tables_data}],
            },
        }
    })

    ai_block = _block_state("ai_b1", "AI_ASSISTED_TEXT", "draft")

    blocks = {"src_b1": source_block, "ai_b1": ai_block}
    state = WorkspaceState.model_construct(
        workspace_id=uuid4(),
        template_version_id=uuid4(),
        report_profile="ANNUAL_REPORT",
        inputs={},
        blocks=blocks,
        block_outputs={},
        status="drafting",
        warnings=[],
        spec=spec_obj,
        artifacts_normalized={},
        user_edits={},
        regenerate_blocks=set(),
        skip_blocks=set(),
    )

    node = AIAssistDraftNode(FakeLLM())
    result = await node(state)

    assert result["blocks"]["ai_b1"].status == "ai_generated"
    assert len(received_contexts) == 1
    assert "tables_json" in received_contexts[0] or "Col A" in received_contexts[0]


# ---------------------------------------------------------------------------
# 13. CitationAndTraceabilityNode populates Citation.page from rich document
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_citation_node_populates_page_from_rich_doc():
    from server.app.modules.redaccion.contracts.blocks import AIAssistedTextBlock
    from server.app.modules.redaccion.contracts.block_io import BlockReference

    ai_contract = AIAssistedTextBlock(
        id="ai_b1",
        title="AI Block",
        ai_prompt_template_id="tmpl_v1",
        review_policy_id="policy_default",
        depends_on=[BlockReference(block_id="src_b1", projection="summary")],
    )
    spec_obj = MagicMock()
    spec_obj.blocks = [ai_contract]

    source_block = _block_state("src_b1", "DETERMINISTIC_DATA", "extracted")
    source_block = source_block.model_copy(update={
        "content": {
            "free_text": "text",
            "document": {
                "markdown": "# Doc",
                "extraction_strategy": "text_linear",
                "pages": [{"page_num": 3, "markdown": "content", "tables": []}],
            },
        }
    })

    ai_block = _block_state("ai_b1", "AI_ASSISTED_TEXT", "ai_generated")
    ai_block = ai_block.model_copy(update={"content": {"text": "generated"}})

    blocks = {"src_b1": source_block, "ai_b1": ai_block}
    state = WorkspaceState.model_construct(
        workspace_id=uuid4(),
        template_version_id=uuid4(),
        report_profile="ANNUAL_REPORT",
        inputs={},
        blocks=blocks,
        block_outputs={},
        status="drafting",
        warnings=[],
        spec=spec_obj,
        artifacts_normalized={},
        user_edits={},
        regenerate_blocks=set(),
        skip_blocks=set(),
    )

    node = CitationAndTraceabilityNode()
    result = await node(state)

    citations = result["blocks"]["ai_b1"].citations
    assert citations is not None
    assert len(citations) >= 1
    assert citations[0].page == 3
