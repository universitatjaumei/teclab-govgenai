"""Tests 9R.5.4 — ExtractionPipelineFactory + AdminScriptExtractionPipeline (RED → GREEN)."""
from __future__ import annotations

import pytest

from server.app.modules.redaccion.pipelines.contracts import ExtractionPipeline


# ---------------------------------------------------------------------------
# Stub ligero para no cargar Docling ni camelot en los tests del factory
# ---------------------------------------------------------------------------

class _StubPipeline:
    """Pipeline stub que soporta un único source_kind."""

    def __init__(self, kind: str, pid: str) -> None:
        self._kind = kind
        self.pipeline_id = pid

    def supports(self, source_kind: str) -> bool:
        return source_kind == self._kind

    def extract(self, inp):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Tests del factory
# ---------------------------------------------------------------------------

class TestExtractionPipelineFactory:

    def _make_factory(self):
        from server.app.modules.redaccion.pipelines.factory import ExtractionPipelineFactory

        factory = ExtractionPipelineFactory()
        for kind, pid in [
            ("excel",        "excel_pipeline_v1"),
            ("pdf_text",     "pdf_text_pipeline_v1"),
            ("pdf_table",    "pdf_table_pipeline_v1"),
            ("manual",       "manual_pipeline_v1"),
            ("admin_script", "admin_script_pipeline_v1"),
        ]:
            factory.register(_StubPipeline(kind, pid))
        return factory

    def test_factory_returns_pipeline_for_excel(self) -> None:
        factory = self._make_factory()
        pipeline = factory.get("excel")
        assert isinstance(pipeline, ExtractionPipeline)
        assert pipeline.pipeline_id == "excel_pipeline_v1"

    def test_factory_returns_pipeline_for_pdf_text(self) -> None:
        factory = self._make_factory()
        pipeline = factory.get("pdf_text")
        assert isinstance(pipeline, ExtractionPipeline)
        assert pipeline.pipeline_id == "pdf_text_pipeline_v1"

    def test_factory_returns_pipeline_for_pdf_table(self) -> None:
        factory = self._make_factory()
        pipeline = factory.get("pdf_table")
        assert isinstance(pipeline, ExtractionPipeline)
        assert pipeline.pipeline_id == "pdf_table_pipeline_v1"

    def test_factory_returns_pipeline_for_manual(self) -> None:
        factory = self._make_factory()
        pipeline = factory.get("manual")
        assert isinstance(pipeline, ExtractionPipeline)
        assert pipeline.pipeline_id == "manual_pipeline_v1"

    def test_factory_returns_pipeline_for_admin_script(self) -> None:
        factory = self._make_factory()
        pipeline = factory.get("admin_script")
        assert isinstance(pipeline, ExtractionPipeline)
        assert pipeline.pipeline_id == "admin_script_pipeline_v1"

    def test_factory_rejects_unknown_source_type(self) -> None:
        from server.app.modules.redaccion.pipelines.factory import UnknownSourceKindError

        factory = self._make_factory()
        with pytest.raises(UnknownSourceKindError, match="source_kind='csv'"):
            factory.get("csv")


# ---------------------------------------------------------------------------
# Tests de AdminScriptExtractionPipeline
# ---------------------------------------------------------------------------

class TestAdminScriptExtractionPipeline:

    async def test_admin_script_pipeline_only_runs_approved_code(self) -> None:
        from server.app.modules.redaccion.pipelines.admin_script_pipeline import (
            AdminScriptExtractionPipeline,
        )
        from server.app.modules.redaccion.pipelines.contracts import ExtractionInput

        pipeline = AdminScriptExtractionPipeline()

        # Sin aprobación → error SCRIPT_NOT_APPROVED
        inp_not_approved = ExtractionInput(
            source_kind="admin_script",
            raw_text="",
            options={"approved": False, "code": "result = {'metrics': []}"},
        )
        result = await pipeline.extract_async(inp_not_approved)
        warning_codes = [w.code for w in result.warnings]
        assert "SCRIPT_NOT_APPROVED" in warning_codes
        assert result.warnings[0].severity == "error"

        # Con aprobación y script seguro → ejecuta y devuelve métricas
        safe_code = "result = {'metrics': [{'name': 'total', 'value': 42}]}"
        inp_approved = ExtractionInput(
            source_kind="admin_script",
            raw_text="",
            options={"approved": True, "code": safe_code},
        )
        result_ok = await pipeline.extract_async(inp_approved)
        assert not result_ok.warnings
        assert len(result_ok.metrics) == 1
        assert result_ok.metrics[0].name == "total"
        assert float(result_ok.metrics[0].value) == pytest.approx(42.0)

    async def test_admin_script_pipeline_blocks_unsafe_imports(self) -> None:
        from server.app.modules.redaccion.pipelines.admin_script_pipeline import (
            AdminScriptExtractionPipeline,
        )
        from server.app.modules.redaccion.pipelines.contracts import ExtractionInput

        pipeline = AdminScriptExtractionPipeline()

        unsafe_code = "import os\nresult = {'free_text': os.getcwd()}"
        inp = ExtractionInput(
            source_kind="admin_script",
            raw_text="",
            options={"approved": True, "code": unsafe_code},
        )

        result = await pipeline.extract_async(inp)

        warning_codes = [w.code for w in result.warnings]
        assert "SCRIPT_SECURITY_VIOLATION" in warning_codes
        violation = next(w for w in result.warnings if w.code == "SCRIPT_SECURITY_VIOLATION")
        assert violation.severity == "error"
        assert len(result.metrics) == 0
        assert result.free_text is None
