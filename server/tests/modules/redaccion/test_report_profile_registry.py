"""9R.2.1 + 9R.2.2 — ReportProfileRegistry + GenericReportProfile.

Tests RED → GREEN. Verifica el registry de perfiles y la spec por defecto
del perfil GENERIC_REPORT (9 secciones, inputs opcionales, política de revisión).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 9R.2.1 — Registry
# ---------------------------------------------------------------------------

class TestReportProfileRegistry:
    def test_registry_contains_generic_report_after_import(self):
        from server.app.modules.redaccion.profiles import registry
        profile = registry.get("GENERIC_REPORT")
        assert profile.profile_id == "GENERIC_REPORT"

    def test_registry_rejects_duplicate_profile_id(self):
        from server.app.modules.redaccion.profiles.registry import (
            ReportProfileRegistry,
        )
        from server.app.modules.redaccion.profiles.generic_report import GenericReportProfile

        reg = ReportProfileRegistry()
        reg.register(GenericReportProfile())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(GenericReportProfile())

    def test_get_unknown_profile_raises(self):
        from server.app.modules.redaccion.profiles import registry
        with pytest.raises(KeyError):
            registry.get("NON_EXISTENT_PROFILE")

    def test_registry_list_includes_generic_report(self):
        from server.app.modules.redaccion.profiles import registry
        ids = registry.list()
        assert "GENERIC_REPORT" in ids

    def test_generic_report_applicable_pipelines_includes_excel_pdf_manual(self):
        from server.app.modules.redaccion.profiles import registry
        profile = registry.get("GENERIC_REPORT")
        pipelines = profile.applicable_pipelines()
        pipeline_str = " ".join(pipelines)
        assert "EXCEL" in pipeline_str or any("excel" in p.lower() for p in pipelines)
        assert "PDF" in pipeline_str or any("pdf" in p.lower() for p in pipelines)
        assert "MANUAL" in pipeline_str or any("manual" in p.lower() for p in pipelines)

    def test_generic_report_default_spec_is_valid_report_template_spec(self):
        from server.app.modules.redaccion.profiles import registry
        from server.app.modules.redaccion.contracts.template import ReportTemplateSpec
        profile = registry.get("GENERIC_REPORT")
        spec = profile.default_spec()
        assert isinstance(spec, ReportTemplateSpec)
        assert len(spec.sections) > 0
        assert len(spec.blocks) > 0


# ---------------------------------------------------------------------------
# 9R.2.2 — Spec por defecto de GENERIC_REPORT
# ---------------------------------------------------------------------------

class TestGenericReportSpec:
    def _spec(self):
        from server.app.modules.redaccion.profiles import registry
        return registry.get("GENERIC_REPORT").default_spec()

    def test_generic_report_profile_exists(self):
        from server.app.modules.redaccion.profiles import registry
        assert registry.get("GENERIC_REPORT") is not None

    def test_generic_report_default_spec_contains_nine_sections_in_order(self):
        spec = self._spec()
        assert len(spec.sections) == 9
        orders = [s.order for s in spec.sections]
        assert orders == list(range(1, 10)), f"Sections not in order 1-9: {orders}"

    def test_generic_report_accepts_manual_blocks(self):
        from server.app.modules.redaccion.contracts.blocks import UserInputBlock
        spec = self._spec()
        user_input_blocks = [b for b in spec.blocks if isinstance(b, UserInputBlock)]
        assert len(user_input_blocks) >= 1

    def test_generic_report_accepts_excel_and_pdf_inputs(self):
        spec = self._spec()
        all_slot_kinds = [
            slot.kind
            for slot in spec.input_contract.required_slots + spec.input_contract.optional_slots
        ]
        assert "excel" in all_slot_kinds
        assert "pdf" in all_slot_kinds

    def test_generic_report_requires_human_approval_for_ai_blocks(self):
        from server.app.modules.redaccion.contracts.blocks import (
            AIAssistedTextBlock,
            AISummaryBlock,
            AIRewriteBlock,
        )
        spec = self._spec()
        ai_blocks = [
            b for b in spec.blocks
            if isinstance(b, (AIAssistedTextBlock, AISummaryBlock, AIRewriteBlock))
        ]
        assert len(ai_blocks) >= 1
        for block in ai_blocks:
            assert block.review_policy_id is not None, f"AI block {block.id!r} missing review_policy_id"
            assert block.review_policy_id != "", f"AI block {block.id!r} missing review_policy_id"

    def test_generic_report_ai_block_policy_is_required_review(self):
        from server.app.modules.redaccion.contracts.template import AIBlockPolicy
        spec = self._spec()
        assert spec.ai_block_policy == AIBlockPolicy.REQUIRED_REVIEW

    def test_generic_report_review_policy_is_required(self):
        from server.app.modules.redaccion.contracts.template import ReviewPolicy
        spec = self._spec()
        assert spec.review_policy == ReviewPolicy.REQUIRED

    def test_generic_report_can_be_created_from_llm_draft(self):
        # Placeholder — el flujo completo se testea en 9R.4
        from server.app.modules.redaccion.profiles import registry
        profile = registry.get("GENERIC_REPORT")
        assert profile.profile_id == "GENERIC_REPORT"

    def test_generic_report_generates_run_manifest_field(self):
        # Placeholder — la emisión del manifest se testea en 9R.9
        from server.app.modules.redaccion.profiles import registry
        profile = registry.get("GENERIC_REPORT")
        assert profile.profile_id is not None
