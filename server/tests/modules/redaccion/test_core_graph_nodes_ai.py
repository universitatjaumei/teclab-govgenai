"""Tests 9R.6.3 — AIAssistDraftNode / CitationAndTraceabilityNode (RED → GREEN)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.redaccion.contracts.block_io import BlockReference
from server.app.modules.redaccion.contracts.blocks import (
    AIAssistedTextBlock,
    DeterministicDataBlock,
)
from server.app.modules.redaccion.contracts.inputs import InputContract
from server.app.modules.redaccion.contracts.runtime import BlockState, WorkspaceState
from server.app.modules.redaccion.contracts.template import (
    AIBlockPolicy,
    ExportPolicy,
    ReportTemplateSpec,
    ReviewPolicy,
)
from server.app.modules.redaccion.contracts.ui import ReportUIContract
from server.tests.dobles import modelo_de_chat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _block_state(
    block_id: str,
    kind: str = "AI_ASSISTED_TEXT",
    status: str = "draft",
    content: dict | None = None,
) -> BlockState:
    return BlockState(
        block_id=block_id,
        kind=kind,
        status=status,
        content=content,
        last_updated_by="system",
        updated_at=_now(),
    )


def _make_spec(extra_blocks=None) -> ReportTemplateSpec:
    blocks = [
        DeterministicDataBlock(id="b_data", title="Datos", source_pipeline="excel"),
        AIAssistedTextBlock(
            id="b_ai",
            title="Resumen ejecutivo",
            ai_prompt_template_id="resumen_v1",
            review_policy_id="required",
            depends_on=[BlockReference(block_id="b_data")],
        ),
    ]
    if extra_blocks:
        blocks.extend(extra_blocks)
    return ReportTemplateSpec(
        sections=[],
        blocks=blocks,
        input_contract=InputContract(),
        ui_contract=ReportUIContract(
            wizard_steps=[], dropzones=[], manual_fields=[],
            block_editor_enabled=False, ai_review_panel_enabled=False,
            preview_layout="markdown",
        ),
        ai_block_policy=AIBlockPolicy.ALLOWED,
        review_policy=ReviewPolicy.NONE,
        export_policy=ExportPolicy.DOCX,
    )


def _make_state(**overrides) -> WorkspaceState:
    defaults = dict(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks={
            "b_data": _block_state("b_data", kind="DETERMINISTIC_DATA", status="extracted",
                                   content={"tables": [], "metrics": [{"name": "total", "value": 100}]}),
            "b_ai":   _block_state("b_ai",  kind="AI_ASSISTED_TEXT",   status="draft"),
        },
        status="drafting",
        warnings=[],
        spec=_make_spec(),
        artifacts_normalized={},
    )
    defaults.update(overrides)
    return WorkspaceState(**defaults)


def _mock_llm(return_text: str = "Generated text.", model: str = "claude-test") -> MagicMock:
    llm = modelo_de_chat()
    llm.model_name = model
    llm.generate = AsyncMock(return_value=return_text)
    return llm


# ---------------------------------------------------------------------------
# AIAssistDraftNode
# ---------------------------------------------------------------------------

class TestAIAssistDraftNode:

    @pytest.mark.asyncio
    async def test_ai_node_receives_only_validated_data_context(self) -> None:
        from server.app.modules.redaccion.graph.nodes.ai_assist_draft import AIAssistDraftNode

        # Hay un bloque extra en "draft" — NO debe aparecer en el contexto
        draft_block = _block_state("b_draft", kind="DETERMINISTIC_DATA", status="draft",
                                   content={"tables": [], "metrics": []})
        state = _make_state(blocks={
            "b_data":  _block_state("b_data", kind="DETERMINISTIC_DATA", status="extracted",
                                    content={"value": "extracted_content"}),
            "b_draft": draft_block,
            "b_ai":    _block_state("b_ai",  kind="AI_ASSISTED_TEXT",  status="draft"),
        })

        llm = _mock_llm()
        node = AIAssistDraftNode(llm)
        await node(state)

        _, kwargs = llm.generate.call_args
        context = kwargs["context"]
        assert "b_data" in context
        assert "b_draft" not in context

    @pytest.mark.asyncio
    async def test_ai_node_records_model_and_prompt_version(self) -> None:
        from server.app.modules.redaccion.graph.nodes.ai_assist_draft import AIAssistDraftNode

        llm = _mock_llm(return_text="Texto generado.", model="claude-sonnet-4-6")
        state = _make_state()
        node = AIAssistDraftNode(llm)

        patch = await node(state)

        b_ai = patch["blocks"]["b_ai"]
        assert b_ai.content["model_used"] == "claude-sonnet-4-6"
        assert b_ai.content["prompt_version"] == "resumen_v1"
        assert b_ai.content["text"] == "Texto generado."
        assert b_ai.status == "ai_generated"

    @pytest.mark.asyncio
    async def test_ai_node_skipped_if_block_already_approved_or_locked(self) -> None:
        from server.app.modules.redaccion.graph.nodes.ai_assist_draft import AIAssistDraftNode

        # Bloque b_ai ya está aprobado
        state = _make_state(blocks={
            "b_data": _block_state("b_data", kind="DETERMINISTIC_DATA", status="extracted",
                                   content={"value": "x"}),
            "b_ai":  _block_state("b_ai",  kind="AI_ASSISTED_TEXT",   status="approved",
                                   content={"text": "previous", "model_used": "old", "prompt_version": "v0"}),
        })

        llm = _mock_llm()
        node = AIAssistDraftNode(llm)
        await node(state)

        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_ai_node_handles_llm_error_gracefully(self) -> None:
        from server.app.modules.redaccion.graph.nodes.ai_assist_draft import AIAssistDraftNode

        llm = modelo_de_chat()
        llm.model_name = "claude-test"
        llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        original_content = {"tables": [], "metrics": []}
        state = _make_state(blocks={
            "b_data": _block_state("b_data", kind="DETERMINISTIC_DATA", status="extracted",
                                   content=original_content),
            "b_ai":  _block_state("b_ai",  kind="AI_ASSISTED_TEXT",   status="draft"),
        })

        node = AIAssistDraftNode(llm)
        patch = await node(state)

        # 9R.6.6: per-block failure — marks block failed(ai_failed), continues with others
        assert patch["blocks"]["b_ai"].status == "failed"
        assert patch["blocks"]["b_ai"].failure_kind == "ai_failed"
        assert "LLM unavailable" in (patch["blocks"]["b_ai"].last_error_message or "")


# ---------------------------------------------------------------------------
# CitationAndTraceabilityNode
# ---------------------------------------------------------------------------

class TestCitationAndTraceabilityNode:

    @pytest.mark.asyncio
    async def test_citation_node_attaches_provenance_to_ai_block(self) -> None:
        from server.app.modules.redaccion.graph.nodes.citation_traceability import CitationAndTraceabilityNode

        state = _make_state(blocks={
            "b_data": _block_state("b_data", kind="DETERMINISTIC_DATA", status="extracted",
                                   content={"free_text": "Datos del año 2025"}),
            "b_ai":  _block_state("b_ai",  kind="AI_ASSISTED_TEXT",   status="ai_generated",
                                   content={"text": "Resumen generado"}),
        })

        node = CitationAndTraceabilityNode()
        patch = await node(state)

        b_ai = patch["blocks"]["b_ai"]
        assert b_ai.citations is not None
        assert len(b_ai.citations) == 1
        assert b_ai.citations[0].source_document == "b_data"
