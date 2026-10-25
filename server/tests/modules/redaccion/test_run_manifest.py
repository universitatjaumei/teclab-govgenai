"""Tests 9R.9.1 — DraftingRunManifest modelo + repo + endpoint (RED → GREEN).

Deploy: edge
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.modules.redaccion.contracts.manifest import (
    AIBlockSummary,
    DraftingRunManifest,
    ExtractedBlockSummary,
    UploadedDocumentInfo,
)
from server.app.modules.redaccion.contracts.runtime import ApprovalRecord
from server.app.modules.redaccion.database.models import HubRunManifest, HubWorkspace
from server.app.api.deps import get_session

# SEC.8.1: el manifest solo se sirve a quien es dueño del workspace, así que el usuario del
# token y el `owner_id` del workspace tienen que ser el mismo; antes el token llevaba un
# uuid nuevo en cada llamada porque a nadie le importaba quién preguntaba.
_USER_ID = uuid.uuid4()

# ---------------------------------------------------------------------------
# JWT helpers (shared pattern)
# ---------------------------------------------------------------------------

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}


def _make_token(role: str = "user") -> str:
    import os
    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token
    return create_token(UserInfo(
        user_id=str(_USER_ID),
        email="user@test.com",
        role=role,
    ))


def _auth(role: str = "user") -> dict:
    return {"Authorization": f"Bearer {_make_token(role)}"}


# ---------------------------------------------------------------------------
# Manifest factories
# ---------------------------------------------------------------------------

def _make_manifest(**kwargs) -> DraftingRunManifest:
    defaults = dict(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        status_at_close="assembled",
    )
    defaults.update(kwargs)
    return DraftingRunManifest(**defaults)


def _make_orm_manifest(manifest: DraftingRunManifest) -> HubRunManifest:
    orm = MagicMock(spec=HubRunManifest)
    orm.id = manifest.id
    orm.workspace_id = manifest.workspace_id
    orm.payload_json = manifest.model_dump(mode="json")
    orm.created_at = manifest.created_at
    return orm


# ---------------------------------------------------------------------------
# App builder for endpoint tests
# ---------------------------------------------------------------------------

def _build_app(session_mock) -> FastAPI:
    from server.app.routers.redaccion.manifests_router import router

    async def _override():
        yield session_mock

    app = FastAPI()
    app.dependency_overrides[get_session] = _override
    app.include_router(router, prefix="/api/v1")
    return app


def _make_session(
    *,
    by_id: HubRunManifest | None = None,
    by_workspace: HubRunManifest | None = None,
    owner_id: uuid.UUID | None = None,
) -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()

    workspace = MagicMock(spec=HubWorkspace)
    workspace.owner_id = _USER_ID if owner_id is None else owner_id

    async def _get(model, pk):
        if model is HubRunManifest:
            return by_id
        if model is HubWorkspace:
            return workspace
        return None

    session.get = AsyncMock(side_effect=_get)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = by_workspace
    session.execute = AsyncMock(return_value=result_mock)

    return session


# ---------------------------------------------------------------------------
# Tests — Pydantic model
# ---------------------------------------------------------------------------

def test_run_manifest_created_for_each_drafting_run():
    manifest = _make_manifest()

    assert manifest.id is not None
    assert manifest.workspace_id is not None
    assert manifest.report_profile == "GENERIC_REPORT"
    assert manifest.status_at_close == "assembled"
    assert manifest.final_document_hash is None
    # Serializes and round-trips cleanly
    payload = manifest.model_dump(mode="json")
    restored = DraftingRunManifest.model_validate(payload)
    assert restored.id == manifest.id
    assert restored.workspace_id == manifest.workspace_id


def test_run_manifest_records_uploaded_documents():
    doc = UploadedDocumentInfo(
        slot_id="slot_excel",
        filename="informe_2026.xlsx",
        storage_path="ingestion/ws-1/informe_2026.xlsx",
        size_bytes=48200,
        uploaded_at=datetime.now(timezone.utc),
    )
    manifest = _make_manifest(uploaded_documents=[doc])

    assert len(manifest.uploaded_documents) == 1
    assert manifest.uploaded_documents[0].slot_id == "slot_excel"
    assert manifest.uploaded_documents[0].filename == "informe_2026.xlsx"
    assert manifest.uploaded_documents[0].size_bytes == 48200


def test_run_manifest_records_extracted_blocks():
    blocks = [
        ExtractedBlockSummary(
            block_id="b_data",
            kind="DETERMINISTIC_DATA",
            status="extracted",
            extraction_strategy="excel",
            warning_count=0,
        ),
        ExtractedBlockSummary(
            block_id="b_table",
            kind="TABLE",
            status="extracted",
            extraction_strategy="pdf_table",
            warning_count=2,
        ),
    ]
    manifest = _make_manifest(extracted_blocks=blocks)

    assert len(manifest.extracted_blocks) == 2
    assert manifest.extracted_blocks[0].block_id == "b_data"
    assert manifest.extracted_blocks[0].extraction_strategy == "excel"
    assert manifest.extracted_blocks[1].warning_count == 2


def test_run_manifest_records_ai_blocks_and_model():
    ai_blocks = [
        AIBlockSummary(
            block_id="b_intro",
            kind="AI_ASSISTED_TEXT",
            status="approved",
            model_used="claude-opus-4-7",
            prompt_version="v2",
        )
    ]
    manifest = _make_manifest(
        ai_blocks=ai_blocks,
        model_used="claude-opus-4-7",
        prompt_versions=["v2"],
    )

    assert len(manifest.ai_blocks) == 1
    assert manifest.ai_blocks[0].model_used == "claude-opus-4-7"
    assert manifest.ai_blocks[0].prompt_version == "v2"
    assert manifest.model_used == "claude-opus-4-7"
    assert "v2" in manifest.prompt_versions


def test_run_manifest_records_user_approvals():
    approvals = [
        ApprovalRecord(
            approved_by=uuid.uuid4(),
            approved_at=datetime.now(timezone.utc),
            note="Revisado y conforme",
        ),
        ApprovalRecord(
            approved_by=uuid.uuid4(),
            approved_at=datetime.now(timezone.utc),
        ),
    ]
    manifest = _make_manifest(user_approvals=approvals)

    assert len(manifest.user_approvals) == 2
    assert manifest.user_approvals[0].note == "Revisado y conforme"
    assert manifest.user_approvals[1].note is None


# ---------------------------------------------------------------------------
# Tests — Endpoint
# ---------------------------------------------------------------------------

def test_run_manifest_endpoint_returns_full_payload():
    workspace_id = uuid.uuid4()
    manifest = _make_manifest(
        workspace_id=workspace_id,
        uploaded_documents=[
            UploadedDocumentInfo(
                slot_id="slot_1",
                filename="doc.xlsx",
                storage_path="s/doc.xlsx",
                size_bytes=1000,
                uploaded_at=datetime.now(timezone.utc),
            )
        ],
        final_document_hash="abc123",
    )
    orm = _make_orm_manifest(manifest)
    session = _make_session(by_id=orm, by_workspace=orm)

    client = TestClient(_build_app(session))

    # GET by workspace
    resp = client.get(
        f"/api/v1/redaccion/workspaces/{workspace_id}/manifest",
        headers=_auth(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["workspace_id"] == str(workspace_id)
    assert data["report_profile"] == "GENERIC_REPORT"
    assert data["final_document_hash"] == "abc123"
    assert len(data["uploaded_documents"]) == 1
    assert data["uploaded_documents"][0]["filename"] == "doc.xlsx"

    # GET by manifest ID
    resp = client.get(
        f"/api/v1/redaccion/manifests/{manifest.id}",
        headers=_auth(),
    )
    assert resp.status_code == 200
    data2 = resp.json()
    assert data2["workspace_id"] == str(workspace_id)


def test_run_manifest_is_denied_to_a_non_owner():
    """SEC.8.1: el `payload_json` lleva lo extraído del expediente, así que leerlo por
    UUID sin ser el dueño era una fuga de contenido, no un detalle de permisos."""
    workspace_id = uuid.uuid4()
    manifest = _make_manifest(workspace_id=workspace_id)
    orm = _make_orm_manifest(manifest)
    session = _make_session(by_id=orm, by_workspace=orm, owner_id=uuid.uuid4())

    client = TestClient(_build_app(session))

    por_workspace = client.get(
        f"/api/v1/redaccion/workspaces/{workspace_id}/manifest", headers=_auth()
    )
    por_id = client.get(f"/api/v1/redaccion/manifests/{manifest.id}", headers=_auth())

    assert por_workspace.status_code == 403
    assert por_id.status_code == 403


def test_run_manifest_is_immutable():
    manifest = _make_manifest(final_document_hash="original-hash")

    # DraftingRunManifest is frozen — attribute assignment must fail
    with pytest.raises(ValueError, match="frozen"):
        manifest.final_document_hash = "tampered-hash"  # type: ignore[misc]

    # No PUT/PATCH endpoints exposed
    session = _make_session()
    client = TestClient(_build_app(session))
    resp = client.patch(
        f"/api/v1/redaccion/manifests/{manifest.id}",
        json={"final_document_hash": "tampered"},
        headers=_auth(),
    )
    # 405 Method Not Allowed or 404 — no update endpoint
    assert resp.status_code in (404, 405)
