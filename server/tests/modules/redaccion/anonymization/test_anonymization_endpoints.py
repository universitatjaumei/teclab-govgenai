"""Tests 13.2 — Endpoints REST de auditoría NER y toggle per-workspace.

Deploy: edge
Cubre los 6 tests de backend especificados en el prompt 13.2.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.api.deps import get_session
from server.app.modules.redaccion.database.models import (
    HubRunManifest,
    HubWorkspace,
    HubWorkspaceAuditEvent,
)
from server.app.modules.redaccion.services.anonymization.run_context import (
    AnonymizationMode,
    AnonymizationSummary,
)

# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}


def _make_token(role: str = "user", user_id: str | None = None) -> str:
    import os

    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token

    return create_token(
        UserInfo(
            user_id=user_id or str(uuid.uuid4()),
            email="user@test.com",
            role=role,
        )
    )


def _auth(role: str = "user", user_id: str | None = None) -> dict:
    return {"Authorization": f"Bearer {_make_token(role, user_id)}"}


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_workspace(
    *,
    owner_id: uuid.UUID | None = None,
    status: str = "draft",
    anonymization_mode: str = "replace",
) -> MagicMock:
    ws = MagicMock(spec=HubWorkspace)
    ws.id = uuid.uuid4()
    ws.owner_id = owner_id or uuid.uuid4()
    ws.status = status
    ws.anonymization_mode = anonymization_mode
    ws.inputs_json = {}
    ws.template_version_id = uuid.uuid4()
    return ws


def _make_run_manifest_orm(
    *,
    workspace_id: uuid.UUID,
    summary: AnonymizationSummary | None = None,
) -> MagicMock:
    manifest_id = uuid.uuid4()
    payload: dict = {
        "id": str(manifest_id),
        "workspace_id": str(workspace_id),
        "template_version_id": str(uuid.uuid4()),
        "report_profile": "GENERIC_REPORT",
        "status_at_close": "assembled",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if summary:
        payload["anonymization_summary"] = summary.model_dump(mode="json")

    orm = MagicMock(spec=HubRunManifest)
    orm.id = manifest_id
    orm.workspace_id = workspace_id
    orm.payload_json = payload
    orm.created_at = datetime.now(timezone.utc)
    return orm


def _make_session(
    *,
    workspace: MagicMock | None = None,
    run_manifest: MagicMock | None = None,
) -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def _get(model, pk):
        if model is HubWorkspace:
            return workspace
        if model is HubRunManifest:
            return run_manifest
        return None

    session.get = AsyncMock(side_effect=_get)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = run_manifest
    session.execute = AsyncMock(return_value=result_mock)

    return session


def _build_app(session_mock: AsyncMock) -> FastAPI:
    from server.app.routers.redaccion.anonymization_router import router

    async def _override():
        yield session_mock

    app = FastAPI()
    app.dependency_overrides[get_session] = _override
    app.include_router(router, prefix="/api/v1")
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_summary_returns_metadata_without_originals() -> None:
    """GET anonymization-summary devuelve mode, counts_by_type, total_spans sin originales."""
    owner_id = uuid.uuid4()
    workspace = _make_workspace(
        owner_id=owner_id, status="assembled", anonymization_mode="replace"
    )
    summary = AnonymizationSummary(
        mode=AnonymizationMode.REPLACE,
        counts_by_type={"PERSON": 5, "IBAN": 2, "EMAIL": 1},
        total_spans=8,
        detected_at=datetime.now(timezone.utc),
    )
    manifest_orm = _make_run_manifest_orm(workspace_id=workspace.id, summary=summary)
    session = _make_session(workspace=workspace, run_manifest=manifest_orm)

    client = TestClient(_build_app(session))
    resp = client.get(
        f"/api/v1/redaccion/workspaces/{workspace.id}/anonymization-summary",
        headers=_auth(user_id=str(owner_id)),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "replace"
    assert data["counts_by_type"] == {"PERSON": 5, "IBAN": 2, "EMAIL": 1}
    assert data["total_spans"] == 8
    assert data["current_workspace_mode"] == "replace"
    assert "last_run_at" in data
    # Ningún original ni sintético como campo JSON en la respuesta (comprobación de clave)
    for forbidden_key in ("forward_map", "reverse_map", "originals", "synthetic"):
        assert f'"{forbidden_key}"' not in json.dumps(data), \
            f"{forbidden_key!r} no debe ser clave en la respuesta del summary"
    # "spans" como lista de PII no debe aparecer (total_spans es metadata, no lista de spans)
    assert "spans" not in data, "'spans' no debe ser campo directo de la respuesta"


def test_summary_returns_404_when_no_run_executed() -> None:
    """GET anonymization-summary devuelve 404 si no hay run manifest para el workspace."""
    owner_id = uuid.uuid4()
    workspace = _make_workspace(owner_id=owner_id, status="draft")
    session = _make_session(workspace=workspace, run_manifest=None)

    client = TestClient(_build_app(session))
    resp = client.get(
        f"/api/v1/redaccion/workspaces/{workspace.id}/anonymization-summary",
        headers=_auth(user_id=str(owner_id)),
    )

    assert resp.status_code == 404


def test_summary_forbidden_for_non_owner_non_admin() -> None:
    """GET anonymization-summary devuelve 403 para user que no es owner ni admin/partner."""
    workspace = _make_workspace(owner_id=uuid.uuid4(), status="assembled")
    summary = AnonymizationSummary(
        mode=AnonymizationMode.REPLACE,
        counts_by_type={"PERSON": 2},
        total_spans=2,
        detected_at=datetime.now(timezone.utc),
    )
    manifest_orm = _make_run_manifest_orm(workspace_id=workspace.id, summary=summary)
    session = _make_session(workspace=workspace, run_manifest=manifest_orm)

    # user_id diferente al owner_id del workspace
    client = TestClient(_build_app(session))
    resp = client.get(
        f"/api/v1/redaccion/workspaces/{workspace.id}/anonymization-summary",
        headers=_auth(role="user", user_id=str(uuid.uuid4())),
    )

    assert resp.status_code == 403


def test_patch_mode_rejects_during_drafting_status() -> None:
    """PATCH anonymization-mode devuelve 422 si workspace está en ejecución."""
    owner_id = uuid.uuid4()
    for locked_status in ("drafting", "in_review", "assembled", "exported"):
        workspace = _make_workspace(owner_id=owner_id, status=locked_status)
        session = _make_session(workspace=workspace)

        client = TestClient(_build_app(session))
        resp = client.patch(
            f"/api/v1/redaccion/workspaces/{workspace.id}/anonymization-mode",
            json={"mode": "off"},
            headers=_auth(user_id=str(owner_id)),
        )

        assert resp.status_code == 422, f"Expected 422 for status={locked_status}"
        assert "MODE_LOCKED_DURING_EXECUTION" in resp.json().get("detail", ""), \
            f"Expected MODE_LOCKED_DURING_EXECUTION in detail for status={locked_status}"


def test_patch_mode_records_audit_event() -> None:
    """PATCH anonymization-mode actualiza el modo y persiste un audit event."""
    owner_id = uuid.uuid4()
    workspace = _make_workspace(
        owner_id=owner_id, status="draft", anonymization_mode="replace"
    )
    session = _make_session(workspace=workspace)

    client = TestClient(_build_app(session))
    resp = client.patch(
        f"/api/v1/redaccion/workspaces/{workspace.id}/anonymization-mode",
        json={"mode": "detect_only"},
        headers=_auth(user_id=str(owner_id)),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "detect_only"

    # Audit event añadido con el evento correcto
    session.add.assert_called_once()
    audit_arg = session.add.call_args[0][0]
    assert isinstance(audit_arg, HubWorkspaceAuditEvent)
    assert audit_arg.event == "anonymization_mode_changed"
    session.commit.assert_called_once()


# `test_re_analyze_triggers_init_node_without_llm` vivia aqui y se retiro con su endpoint
# (issue #169). Se llamaba «dispara el nodo de inicializacion» y lo unico que comprobaba era que
# la respuesta traia 202 y `"queued"`: fijaba la FORMA de una promesa que no se cumplia, porque
# no habia ni cola ni nodo. Lo que el boton si hacia falta que hiciera —ensenar el resultado— lo
# sirve el `GET` de aqui arriba, y eso ya tiene sus tests.
