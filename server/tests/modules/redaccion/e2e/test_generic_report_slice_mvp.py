"""Tests 9R.10.1 (RED) — Vertical slice acceptance: GENERIC_REPORT MVP.

These tests MUST FAIL in the RED phase. Failure modes:

  1. test_user_can_create_generic_report_from_natural_language
     → AssertionError: workspace.status is "draft", graph never triggered.

  2. test_user_can_upload_excel_and_pdf_to_workspace
     → HTTP 404: POST /redaccion/workspaces/{id}/inputs/{slot_id} not wired yet.

  3. test_required_inputs_are_validated
     → ModuleNotFoundError: WorkspaceRunService does not exist yet.

  4. test_excel_data_is_extracted_before_ai_drafting
     → ModuleNotFoundError: WorkspaceRunService does not exist yet.

  5. test_ai_block_requires_review
     → ModuleNotFoundError: WorkspaceRunService does not exist yet.

  6. test_final_document_contains_only_approved_blocks
     → HTTP 404: POST /redaccion/workspaces/{id}/run not wired yet.

  7. test_run_manifest_is_generated_at_end_of_slice
     → ModuleNotFoundError: WorkspaceRunService does not exist yet.

Wire-up needed: see slice_mvp_status.md.
GREEN phase: 9R.10.2 (Opus recommended).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.modules.redaccion.contracts.blocks import AIAssistedTextBlock, ReviewGateBlock, StaticTextBlock
from server.app.modules.redaccion.contracts.drafts import ReportTemplateDraft
from server.app.modules.redaccion.contracts.inputs import InputContract, InputSlot
from server.app.modules.redaccion.contracts.template import SectionContract
from server.app.modules.redaccion.database.models import HubWorkspace

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_OWNER_ID = uuid.uuid4()


def _make_token(user_id: str, role: str = "user") -> str:
    import jwt

    return jwt.encode(
        {"sub": user_id, "role": role, "workspace_id": str(uuid.uuid4())},
        "test-secret",
        algorithm="HS256",
    )


def _auth(role: str = "user") -> dict:
    return {"Authorization": f"Bearer {_make_token(str(_OWNER_ID), role)}"}


def _minimal_generic_report_draft() -> ReportTemplateDraft:
    """Minimal valid GENERIC_REPORT draft that passes DraftValidator."""
    return ReportTemplateDraft(
        proposed_profile="GENERIC_REPORT",
        proposed_sections=[
            # SEG.5 — la sección enumera lo que se imprime. Sin `block_ids`, el informe salía
            # con la introducción vacía y el análisis en ninguna parte.
            SectionContract(id="s_intro", title="Introducción", order=0,
                            block_ids=["b_intro", "b_analysis"])
        ],
        proposed_blocks=[
            StaticTextBlock(id="b_intro", title="Texto inicial", order=0),
            AIAssistedTextBlock(
                id="b_analysis",
                title="Análisis IA",
                ai_prompt_template_id="tpl_analysis_v1",
                review_policy_id="policy_human_review",
                required=True,
                order=1,
            ),
            ReviewGateBlock(
                id="b_review",
                title="Revisión humana",
                review_policy_id="policy_human_review",
                order=2,
            ),
        ],
        proposed_inputs=InputContract(
            required_slots=[
                InputSlot(
                    slot_id="slot_excel",
                    kind="excel",
                    label={"es": "Datos Excel", "ca": "Dades Excel", "en": "Excel Data"},
                )
            ]
        ),
        rationale="Informe genérico con datos Excel y análisis IA.",
        model_used="claude-sonnet-4-6",
        prompt_version="v1",
    )


def _make_workspace_orm(workspace_id: uuid.UUID, status: str = "draft") -> MagicMock:
    ws = MagicMock(spec=HubWorkspace)
    ws.id = workspace_id
    ws.owner_id = _OWNER_ID
    ws.status = status
    ws.template_version_id = uuid.uuid4()
    return ws


def _build_app_with_mocked_session(session_mock: AsyncMock) -> FastAPI:
    """App with llm_drafts and workspaces routers; session dependency overridden."""
    from server.app.api.deps import get_current_user, get_session
    from server.app.core.auth.models import UserInfo
    from server.app.routers.redaccion.llm_drafts_router import router as llm_drafts_router
    from server.app.routers.redaccion.workspaces_router import router as workspaces_router

    async def _override_session():
        yield session_mock

    async def _override_user():
        return UserInfo(user_id=str(_OWNER_ID), email="test@example.com", role="user")

    app = FastAPI()
    app.include_router(llm_drafts_router, prefix="/api/v1")
    app.include_router(workspaces_router, prefix="/api/v1")
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    return app


# ---------------------------------------------------------------------------
# Test 1 — After approve-as-workspace, workspace status must auto-advance
#           (fails: status stays "draft", graph not triggered)
# ---------------------------------------------------------------------------

def test_user_can_create_generic_report_from_natural_language():
    """Approval of a GENERIC_REPORT draft must kick off the drafting pipeline.

    RED: approve-as-workspace creates the workspace in status='draft' and stops.
    GREEN: it must transition to 'drafting' (graph started) or 'in_review'
           once the pipeline completes synchronously / async notification.
    """
    saved_objects: list = []

    async def _fake_add(obj):
        # capture whatever workspace-like object is persisted
        saved_objects.append(obj)

    session_mock = AsyncMock()
    session_mock.add = MagicMock(side_effect=_fake_add)
    session_mock.commit = AsyncMock()

    # Use execute to return empty scalars (no uniqueness conflicts)
    session_mock.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    app = _build_app_with_mocked_session(session_mock)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/redaccion/llm-drafts/approve-as-workspace",
            json={
                "draft": _minimal_generic_report_draft().model_dump(mode="json"),
                "name": "Informe Genérico Test",
            },
            headers=_auth(),
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # RED ASSERTION: status MUST NOT stay "draft" after approval;
    # the pipeline should have been triggered and status should be
    # "drafting" or further along.
    assert body["status"] != "draft", (
        "RED (expected): workspace was created but graph was never triggered. "
        "status is still 'draft'. Wire up WorkspaceRunService in GREEN."
    )


# ---------------------------------------------------------------------------
# Test 2 — User uploads Excel file to workspace slot
#           (fails: POST /inputs/{slot_id} endpoint does not exist → 404)
# ---------------------------------------------------------------------------

def test_user_can_upload_excel_and_pdf_to_workspace():
    """Upload endpoint for input slots must exist and accept files.

    RED: the endpoint POST /redaccion/workspaces/{id}/inputs/{slot_id}
         is not wired, so the router returns 404.
    """
    workspace_id = uuid.uuid4()
    session_mock = AsyncMock()
    workspace_mock = _make_workspace_orm(workspace_id, status="draft")
    session_mock.get = AsyncMock(return_value=workspace_mock)
    session_mock.commit = AsyncMock()

    app = _build_app_with_mocked_session(session_mock)

    with TestClient(app) as client:
        # Upload Excel to slot_excel
        resp_excel = client.post(
            f"/api/v1/redaccion/workspaces/{workspace_id}/inputs/slot_excel",
            files={"file": ("datos.xlsx", b"PK\x03\x04fake-xlsx-content", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=_auth(),
        )
        # Upload PDF to slot_pdf
        resp_pdf = client.post(
            f"/api/v1/redaccion/workspaces/{workspace_id}/inputs/slot_pdf",
            files={"file": ("memoria.pdf", b"%PDF-1.4 fake", "application/pdf")},
            headers=_auth(),
        )

    assert resp_excel.status_code != 404, (
        f"RED (expected): upload endpoint missing for slot_excel — got {resp_excel.status_code}. "
        "Implement POST /redaccion/workspaces/{id}/inputs/{slot_id} in GREEN."
    )
    assert resp_pdf.status_code != 404, (
        f"RED (expected): upload endpoint missing for slot_pdf — got {resp_pdf.status_code}. "
        "Implement POST /redaccion/workspaces/{id}/inputs/{slot_id} in GREEN."
    )


# ---------------------------------------------------------------------------
# Test 3 — Input contract is validated before graph starts
#           (fails: WorkspaceRunService does not exist → ModuleNotFoundError)
# ---------------------------------------------------------------------------

def test_required_inputs_are_validated():
    """WorkspaceRunService must reject a workspace with missing required slots.

    RED: ModuleNotFoundError because the service module does not exist yet.
    """
    # This import is the RED gate — it MUST raise ModuleNotFoundError.
    from server.app.modules.redaccion.services.workspace_run_service import (
        WorkspaceRunService,
    )

    svc = WorkspaceRunService()
    workspace_id = uuid.uuid4()

    # A workspace with no uploaded files yet must raise InputsNotReadyError
    # (or similar) when validate_inputs() is called before run().
    with pytest.raises(Exception, match="missing"):
        svc.validate_inputs(workspace_id=workspace_id, uploaded_slots=[])


# ---------------------------------------------------------------------------
# Test 4 — Excel data is extracted before AI drafting
#           (fails: WorkspaceRunService does not exist → ModuleNotFoundError)
# ---------------------------------------------------------------------------

def test_excel_data_is_extracted_before_ai_drafting():
    """DeterministicExtractionNode must run before AIAssistDraftNode.

    RED: ModuleNotFoundError because WorkspaceRunService does not exist yet.
    GREEN: run() must return a WorkspaceRunResult with
           extraction_completed=True and ai_drafting_started=True.
    """
    from server.app.modules.redaccion.services.workspace_run_service import (
        WorkspaceRunService,
    )

    svc = WorkspaceRunService()
    result = svc.run_sync(workspace_id=uuid.uuid4(), dry_run=True)

    # Extraction must precede AI drafting in the graph execution order
    assert result.extraction_completed is True
    assert result.ai_drafting_started is True
    assert result.extraction_completed_at < result.ai_drafting_started_at


# ---------------------------------------------------------------------------
# Test 5 — AI block lands in needs_review after draft generation
#           (fails: WorkspaceRunService does not exist → ModuleNotFoundError)
# ---------------------------------------------------------------------------

def test_ai_block_requires_review():
    """After graph run, AI_ASSISTED_TEXT blocks must be in status='needs_review'.

    RED: ModuleNotFoundError because WorkspaceRunService does not exist yet.
    GREEN: run() must produce blocks in the expected HITL state.
    """
    from server.app.modules.redaccion.services.workspace_run_service import (
        WorkspaceRunService,
    )

    svc = WorkspaceRunService()
    result = svc.run_sync(workspace_id=uuid.uuid4(), dry_run=True)

    ai_blocks = [b for b in result.blocks if b.kind == "AI_ASSISTED_TEXT"]
    assert len(ai_blocks) > 0, "Expected at least one AI_ASSISTED_TEXT block"
    for block in ai_blocks:
        assert block.status == "needs_review", (
            f"Block {block.block_id!r} has status={block.status!r}, expected 'needs_review'"
        )


# ---------------------------------------------------------------------------
# Test 6 — POST /run triggers the full pipeline and returns a run summary
#           (fails: endpoint not wired yet → 404)
# ---------------------------------------------------------------------------

def test_final_document_contains_only_approved_blocks():
    """POST /workspaces/{id}/run must trigger the graph and return a run summary.

    RED: the endpoint is not wired, so the router returns 404.
    GREEN: 202 Accepted (or 200) with a run_id and initial status.
    """
    workspace_id = uuid.uuid4()
    session_mock = AsyncMock()
    workspace_mock = _make_workspace_orm(workspace_id, status="draft")
    session_mock.get = AsyncMock(return_value=workspace_mock)
    session_mock.commit = AsyncMock()

    app = _build_app_with_mocked_session(session_mock)

    with TestClient(app) as client:
        resp = client.post(
            f"/api/v1/redaccion/workspaces/{workspace_id}/run",
            headers=_auth(),
        )

    assert resp.status_code != 404, (
        f"RED (expected): /run endpoint missing — got {resp.status_code}. "
        "Wire POST /redaccion/workspaces/{id}/run → WorkspaceRunService in GREEN."
    )
    body = resp.json()
    assert "run_id" in body, "Response must include a run_id for polling"
    assert body.get("status") in {"queued", "running", "completed"}


# ---------------------------------------------------------------------------
# Test 7 — RunManifest is emitted and persisted at end of slice
#           (fails: WorkspaceRunService does not exist → ModuleNotFoundError)
# ---------------------------------------------------------------------------

def test_run_manifest_is_generated_at_end_of_slice():
    """After successful run, a DraftingRunManifest must be persisted.

    RED: ModuleNotFoundError because WorkspaceRunService does not exist yet.
    GREEN: run() must return a result with manifest_id set and a
           DraftingRunManifest retrievable via GET /redaccion/workspaces/{id}/manifest.
    """
    from server.app.modules.redaccion.services.workspace_run_service import (
        WorkspaceRunService,
    )

    svc = WorkspaceRunService()
    result = svc.run_sync(workspace_id=uuid.uuid4(), dry_run=True)

    assert result.manifest_id is not None, (
        "run_sync() must emit and persist a DraftingRunManifest; manifest_id was None"
    )
    assert result.manifest.final_document_hash is not None, (
        "DraftingRunManifest must include final_document_hash after pipeline completes"
    )
