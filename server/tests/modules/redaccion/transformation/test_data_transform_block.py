"""Tests del DataTransformBlock (contract + handler + manifest) — 9R.5.8 (RED → GREEN)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from server.app.modules.redaccion.contracts.block_io import BlockReference
from server.app.modules.redaccion.contracts.blocks import (
    DataTransformBlock,
    DataTransformBlockConfig,
)
from server.app.modules.redaccion.contracts.runtime import BlockState, WorkspaceState
from server.app.modules.redaccion.services.transformation.operations import (
    FilterOp,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _block_state(block_id: str, kind: str, status: str = "draft", content: dict | None = None) -> BlockState:
    return BlockState(
        block_id=block_id,
        kind=kind,
        status=status,
        content=content,
        last_updated_by="system",
        updated_at=_now(),
    )


def _state_with_source_rows(rows: list[dict]) -> WorkspaceState:
    return WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks={
            "b_data": _block_state("b_data", kind="DETERMINISTIC_DATA", status="extracted",
                                   content={"rows": rows}),
            "b_dt":   _block_state("b_dt",   kind="DATA_TRANSFORM",     status="draft"),
        },
        block_outputs={"b_data": {"rows": rows}},
        status="drafting",
        warnings=[],
    )


# ---------------------------------------------------------------------------
# DataTransformBlockConfig contract
# ---------------------------------------------------------------------------

class TestDataTransformContract:

    def test_deterministic_requires_operations(self):
        with pytest.raises(Exception):
            DataTransformBlockConfig(
                mode="deterministic",
                source_block_ref=BlockReference(block_id="b_data"),
                operations=None,
            )

    def test_ai_requires_nl_instruction(self):
        with pytest.raises(Exception):
            DataTransformBlockConfig(
                mode="ai",
                source_block_ref=BlockReference(block_id="b_data"),
                nl_instruction=None,
            )

    def test_data_transform_block_is_in_discriminated_union(self):
        cfg = DataTransformBlockConfig(
            mode="deterministic",
            source_block_ref=BlockReference(block_id="b_data"),
            operations=[FilterOp(col="x", comparator=">", value=0)],
        )
        block = DataTransformBlock(id="b_dt", title="t", config=cfg)
        assert block.kind == "DATA_TRANSFORM"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
# Issue #180 — aquí había tres tests sobre `DataTransformHandler`, que **nadie ejecutaba**: lo
# que transforma un bloque DATA_TRANSFORM es `DataTransformationNode`.
#
# Las tres garantías siguen cubiertas, y sobre el camino que de verdad corre, en
# `test_el_bloque_de_transformacion_transforma.py`: transformar la tabla del bloque de
# extracción, fallar con su motivo cuando la columna no existe y usar el modelo inyectado en
# modo IA. La cuarta —`to_manifest`— se fue con el handler: el manifiesto de la ejecución lo
# construye `audit_log` a partir del estado.
# ---------------------------------------------------------------------------
