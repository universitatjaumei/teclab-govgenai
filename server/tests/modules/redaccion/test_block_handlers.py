"""9R.3.1 + 9R.3.2 — BlockHandlers + BlockStateMachine.

Tests RED → GREEN.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers para BlockState
# ---------------------------------------------------------------------------

def _make_state(status: str = "draft", block_id: str = "b1"):
    from server.app.modules.redaccion.contracts.runtime import BlockState
    return BlockState(
        block_id=block_id,
        kind="STATIC_TEXT",
        status=status,
        content=None,
        citations=None,
        last_updated_by="system",
        updated_at=_now(),
        approval=None,
    )


def _make_workspace(blocks: dict | None = None):
    from server.app.modules.redaccion.contracts.runtime import WorkspaceState
    return WorkspaceState(
        workspace_id=uuid4(),
        template_version_id=uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks=blocks or {},
        status="draft",
        warnings=[],
        run_manifest_id=None,
    )


# ---------------------------------------------------------------------------
# 9R.3.1 — El handler que queda montado
#
# Issue #180 — aquí había ocho tests sobre diez clases que **nadie ejecutaba**, y son los que
# se fueron con ellas: banderas `uses_ai`/`requires_approval` que sólo leían estos asserts, y
# `to_manifest` de clases cuyo manifiesto construye `audit_log` a partir del estado.
#
# Dos garantías merecían quedarse y **no se han perdido**: la puerta de revisión la comprueba
# `test_final_assembler_blocks_when_required_block_not_approved`, más abajo en este fichero,
# sobre el camino que de verdad corre; y quién atiende a cada tipo de bloque lo fija la tabla
# de `test_issue180_los_handlers_que_nadie_montaba.py`.
# ---------------------------------------------------------------------------

class TestChartHandler:
    """El único con consumidor vivo: `ChartRenderNode._dibujar`."""

    def test_chart_block_depends_on_data_block(self):
        from server.app.modules.redaccion.blocks.handlers import ChartHandler
        from server.app.modules.redaccion.contracts.blocks import ChartBlock
        handler = ChartHandler()
        block = ChartBlock(id="b_chart", title="Gràfic", data_block_ref="b_data")
        assert block.data_block_ref == "b_data"
        handler.validate(block)

    def test_chart_handler_rejects_missing_data_block_ref(self):
        """ChartHandler.validate_in_context raises if data_block_ref is not in the workspace."""
        from server.app.modules.redaccion.blocks.handlers import (
            ChartHandler,
            BlockHandlerValidationError,
        )
        from server.app.modules.redaccion.contracts.blocks import ChartBlock
        handler = ChartHandler()
        block = ChartBlock(id="b_chart", title="Gràfic", data_block_ref="b_missing")
        ws = _make_workspace(blocks={})  # b_missing not in workspace
        with pytest.raises(BlockHandlerValidationError, match="data_block_ref"):
            handler.validate_in_context(block, ws)


# ---------------------------------------------------------------------------
# 9R.3.2 — BlockStateMachine
# ---------------------------------------------------------------------------

class TestBlockStateMachine:
    def test_block_state_machine_allows_extract_from_draft(self):
        from server.app.modules.redaccion.services.block_state_machine import (
            BlockStateMachine,
            BlockTransitionEvent,
        )
        machine = BlockStateMachine()
        block = _make_state("draft")
        new_block, audit = machine.transition(block, BlockTransitionEvent.EXTRACT)
        assert new_block.status == "extracted"
        assert audit.from_status == "draft"
        assert audit.to_status == "extracted"

    def test_block_state_machine_blocks_direct_ai_to_approved(self):
        from server.app.modules.redaccion.services.block_state_machine import (
            BlockStateMachine,
            BlockTransitionEvent,
        )
        from server.app.modules.redaccion.contracts.runtime import InvalidBlockTransitionError
        machine = BlockStateMachine()
        block = _make_state("ai_generated")
        with pytest.raises(InvalidBlockTransitionError):
            machine.transition(block, BlockTransitionEvent.APPROVE)

    def test_block_state_machine_locked_block_is_terminal(self):
        from server.app.modules.redaccion.services.block_state_machine import (
            BlockStateMachine,
            BlockTransitionEvent,
        )
        from server.app.modules.redaccion.contracts.runtime import InvalidBlockTransitionError
        machine = BlockStateMachine()
        block = _make_state("locked")
        with pytest.raises(InvalidBlockTransitionError):
            machine.transition(block, BlockTransitionEvent.EXTRACT)

    def test_block_state_machine_rejected_block_can_regenerate(self):
        from server.app.modules.redaccion.services.block_state_machine import (
            BlockStateMachine,
            BlockTransitionEvent,
        )
        machine = BlockStateMachine()
        block = _make_state("rejected")
        new_block, audit = machine.transition(block, BlockTransitionEvent.REGENERATE)
        assert new_block.status == "ai_generated"

    def test_final_assembler_blocks_when_required_block_not_approved(self):
        from server.app.modules.redaccion.services.block_state_machine import (
            check_assembly_readiness,
        )
        blocks = {
            "b1": _make_state("approved", "b1"),
            "b2": _make_state("needs_review", "b2"),
        }
        from server.app.modules.redaccion.contracts.blocks import (
            StaticTextBlock,
            AIAssistedTextBlock,
        )
        contracts = [
            StaticTextBlock(id="b1", title="T1", required=True),
            AIAssistedTextBlock(
                id="b2", title="T2", required=True,
                ai_prompt_template_id="p1", review_policy_id="r1",
            ),
        ]
        blocking = check_assembly_readiness(blocks, contracts)
        assert "b2" in blocking
        assert "b1" not in blocking

    def test_block_transition_emits_audit_event(self):
        from server.app.modules.redaccion.services.block_state_machine import (
            BlockStateMachine,
            BlockTransitionEvent,
        )
        machine = BlockStateMachine()
        block = _make_state("needs_review")
        _, audit = machine.transition(block, BlockTransitionEvent.APPROVE)
        assert audit.event == BlockTransitionEvent.APPROVE.value
        assert audit.from_status == "needs_review"
        assert audit.to_status == "approved"
        assert audit.timestamp is not None
