"""Tests 9R.6.1 — LoadTemplateNode / ValidateInputContractNode / FileNormalizationNode (RED→GREEN)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.redaccion.contracts.inputs import InputContract, InputSlot
from server.app.modules.redaccion.contracts.runtime import (
    InputArtifact,
    WorkspaceState,
)
from server.app.modules.redaccion.contracts.template import (
    AIBlockPolicy,
    ExportPolicy,
    ReportTemplateSpec,
    ReviewPolicy,
)
from server.app.modules.redaccion.contracts.ui import ReportUIContract
from server.tests.dobles import almacenamiento


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_spec(required_slots: list[InputSlot] | None = None) -> ReportTemplateSpec:
    return ReportTemplateSpec(
        sections=[],
        blocks=[],
        input_contract=InputContract(
            required_slots=required_slots or [],
            optional_slots=[],
        ),
        ui_contract=ReportUIContract(
            wizard_steps=[],
            dropzones=[],
            manual_fields=[],
            block_editor_enabled=False,
            ai_review_panel_enabled=False,
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
        blocks={},
        status="draft",
        warnings=[],
    )
    defaults.update(overrides)
    return WorkspaceState(**defaults)


def _make_artifact(storage_path: str = "bucket/key.pdf") -> InputArtifact:
    return InputArtifact(
        slot_id="doc_principal",
        filename="report.pdf",
        storage_path=storage_path,
        size_bytes=1024,
        uploaded_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# LoadTemplateNode
# ---------------------------------------------------------------------------

class TestLoadTemplateNode:

    @pytest.mark.asyncio
    async def test_loads_spec_from_repo(self) -> None:
        from server.app.modules.redaccion.graph.nodes.load_template import LoadTemplateNode

        spec = _minimal_spec()
        orm = MagicMock()
        orm.spec_json = spec.model_dump()

        repo = AsyncMock()
        repo.get.return_value = orm

        state = _make_state()
        node = LoadTemplateNode(repo)
        patch = await node(state)

        assert "spec" in patch
        result_spec: ReportTemplateSpec = patch["spec"]
        assert isinstance(result_spec, ReportTemplateSpec)
        assert result_spec.ai_block_policy == AIBlockPolicy.ALLOWED

    @pytest.mark.asyncio
    async def test_raises_when_version_not_found(self) -> None:
        from server.app.modules.redaccion.graph.nodes.load_template import (
            LoadTemplateNode,
            TemplateVersionNotFoundError,
        )

        repo = AsyncMock()
        repo.get.return_value = None

        state = _make_state()
        node = LoadTemplateNode(repo)

        with pytest.raises(TemplateVersionNotFoundError) as exc_info:
            await node(state)

        assert exc_info.value.version_id == state.template_version_id


# ---------------------------------------------------------------------------
# ValidateInputContractNode
# ---------------------------------------------------------------------------

class TestValidateInputContractNode:

    @pytest.mark.asyncio
    async def test_emits_warning_for_missing_required_slot(self) -> None:
        from server.app.modules.redaccion.graph.nodes.validate_inputs import ValidateInputContractNode

        slot = InputSlot(
            slot_id="doc_principal",
            kind="pdf",
            label={"es": "Documento principal"},
        )
        spec = _minimal_spec(required_slots=[slot])
        state = _make_state(spec=spec, inputs={})  # slot missing

        node = ValidateInputContractNode()
        patch = await node(state)

        warnings = patch["warnings"]
        assert any(
            w.kind == "missing_input" and "doc_principal" in w.message
            for w in warnings
        )

    @pytest.mark.asyncio
    async def test_no_warning_when_all_required_slots_present(self) -> None:
        from server.app.modules.redaccion.graph.nodes.validate_inputs import ValidateInputContractNode

        slot = InputSlot(
            slot_id="doc_principal",
            kind="pdf",
            label={"es": "Documento principal"},
        )
        spec = _minimal_spec(required_slots=[slot])
        artifact = _make_artifact()
        state = _make_state(spec=spec, inputs={"doc_principal": artifact})

        node = ValidateInputContractNode()
        patch = await node(state)

        assert not any(w.kind == "missing_input" for w in patch.get("warnings", []))


# ---------------------------------------------------------------------------
# FileNormalizationNode
# ---------------------------------------------------------------------------

class TestFileNormalizationNode:

    @pytest.mark.asyncio
    async def test_maps_slot_ids_to_local_paths(self) -> None:
        """Desde VER.4 el nodo **materializa** el artefacto: publica la ruta del fichero
        local que acaba de escribir, no el `storage_path`. Los pipelines de extracción abren
        una ruta del sistema de archivos, y con el almacén en GCS no habría nada que abrir.
        """
        from pathlib import Path

        from server.app.modules.redaccion.graph.nodes.file_normalization import FileNormalizationNode

        storage = almacenamiento()
        storage.get = AsyncMock(return_value=b"%PDF-1.4 contenido")
        artifact = _make_artifact(storage_path="bucket/reports/2026/report.pdf")
        state = _make_state(inputs={"doc_principal": artifact})

        node = FileNormalizationNode(storage)
        patch = await node(state)

        ruta = Path(patch["artifacts_normalized"]["doc_principal"])
        storage.get.assert_awaited_once_with("bucket/reports/2026/report.pdf")
        assert ruta.exists()
        assert ruta.read_bytes() == b"%PDF-1.4 contenido"
