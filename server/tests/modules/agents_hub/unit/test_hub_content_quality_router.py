"""Tests TDD — hub_content_quality_router (Prompt 9Q.8).

Endpoints de cola de revisión, transición de estado, informe y export.
Usa FastAPI TestClient con dependencias sobreescritas.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-chars-long")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRATION_MINUTES", "60")

NOW = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)


# SEC.8.1: los endpoints resuelven el sitio (o el chatbot) a su organización antes de
# operar. `analyze_content_gaps` es el caso que lo motiva: lee las conversaciones de
# ciudadanos del chatbot, así que el rol de admin no basta — hay que ser de su organización.
ORG = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


def _make_token(role: str = "admin") -> str:
    from server.app.core.auth import UserInfo, create_token
    return create_token(
        UserInfo(
            user_id="admin-1",
            email="admin@test.com",
            role=role,
            organizacion_ids=(str(ORG),),
        )
    )


def _duenio_de_la_org():
    """Lo que devuelve `session.get` al resolver el dueño del recurso."""
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.uuid4(), organizacion_id=ORG)


def _fake_orm_finding(**kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.site_id = kw.get("site_id", uuid.uuid4())
    m.finding_type = kw.get("finding_type", "stale")
    m.severity = kw.get("severity", "info")
    m.status = kw.get("status", "new")
    m.confidence = kw.get("confidence", 1.0)
    m.page_id = kw.get("page_id", uuid.uuid4())
    m.related_page_id = kw.get("related_page_id", None)
    m.source_url = kw.get("source_url", "https://ej.es/p")
    m.signal_json = kw.get("signal_json", {})
    m.detected_at = kw.get("detected_at", NOW)
    m.reviewed_at = None
    m.reviewed_by = None
    m.resolution_note = None
    m.created_at = NOW
    return m


def _build_app_with_session(session_mock):
    from server.app.routers.hub_content_quality_router import router
    from server.app.modules.agents_hub.database.connection import get_async_session

    session_mock.get = AsyncMock(return_value=_duenio_de_la_org())

    async def _session_override():
        yield session_mock

    app = FastAPI()
    app.dependency_overrides[get_async_session] = _session_override
    app.include_router(router, prefix="/api/v1")
    return app


def _build_app_with_overrides(session_mock=None, findings_repo_mock=None, report_builder_mock=None):
    from server.app.routers.hub_content_quality_router import (
        router,
        get_findings_repo,
        get_report_builder,
    )
    from server.app.modules.agents_hub.database.connection import get_async_session

    _session = session_mock or AsyncMock()
    _session.get = AsyncMock(return_value=_duenio_de_la_org())

    async def _session_override():
        yield _session

    app = FastAPI()
    app.dependency_overrides[get_async_session] = _session_override

    if findings_repo_mock is not None:
        app.dependency_overrides[get_findings_repo] = lambda: findings_repo_mock
    if report_builder_mock is not None:
        app.dependency_overrides[get_report_builder] = lambda: report_builder_mock

    app.include_router(router, prefix="/api/v1")
    return app


# ───────────────────────── Tests de findings (cola de revisión) ─────────────────────────


def test_list_findings_returns_200():
    """GET /hub/sites/{id}/findings → 200 con la lista de hallazgos."""
    site_id = uuid.uuid4()
    finding = _fake_orm_finding(site_id=site_id)

    findings_repo = MagicMock()
    findings_repo.list_by_site = AsyncMock(return_value=[finding])

    app = _build_app_with_overrides(findings_repo_mock=findings_repo)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/hub/sites/{site_id}/findings",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_findings_401_without_token():
    """GET /hub/sites/{id}/findings sin JWT → 401/403."""
    site_id = uuid.uuid4()
    findings_repo = MagicMock()
    findings_repo.list_by_site = AsyncMock(return_value=[])

    app = _build_app_with_overrides(findings_repo_mock=findings_repo)
    client = TestClient(app)
    resp = client.get(f"/api/v1/hub/sites/{site_id}/findings")
    assert resp.status_code in (401, 403)


def test_patch_finding_transitions_status():
    """PATCH /hub/sites/{id}/findings/{fid} → transiciona el estado."""
    site_id = uuid.uuid4()
    finding_id = uuid.uuid4()
    updated_finding = _fake_orm_finding(site_id=site_id, id=finding_id, status="confirmed")

    findings_repo = MagicMock()
    # #242: la ruta comprueba que el hallazgo es de este sitio antes de cambiarlo.
    findings_repo.get = AsyncMock(return_value=_fake_orm_finding(site_id=site_id, id=finding_id))
    findings_repo.transition = AsyncMock(return_value=updated_finding)

    app = _build_app_with_overrides(findings_repo_mock=findings_repo)
    client = TestClient(app)
    resp = client.patch(
        f"/api/v1/hub/sites/{site_id}/findings/{finding_id}",
        json={"new_status": "confirmed"},
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


def test_patch_finding_invalid_transition_returns_422():
    """PATCH con transición inválida → 422."""
    from server.app.modules.curation.contracts import (
        InvalidFindingTransitionError,
    )

    site_id = uuid.uuid4()
    finding_id = uuid.uuid4()

    findings_repo = MagicMock()
    findings_repo.get = AsyncMock(return_value=_fake_orm_finding(site_id=site_id, id=finding_id))
    findings_repo.transition = AsyncMock(
        side_effect=InvalidFindingTransitionError("invalid")
    )

    app = _build_app_with_overrides(findings_repo_mock=findings_repo)
    client = TestClient(app)
    resp = client.patch(
        f"/api/v1/hub/sites/{site_id}/findings/{finding_id}",
        json={"new_status": "resolved"},
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 422


# ───────────────────────── Tests de informe ─────────────────────────


def test_get_report_returns_200_with_report_structure():
    """GET /hub/sites/{id}/report → 200 con estructura WebQualityReport."""
    from server.app.modules.curation.report_contracts import (
        WebQualityReport,
    )

    site_id = uuid.uuid4()
    report = WebQualityReport(
        site_id=site_id,
        site_name="Test",
        generated_at=NOW,
        totals_by_type={"stale": 1},
        totals_by_severity={"info": 1},
        sections=[],
    )

    builder = MagicMock()
    builder.build = AsyncMock(return_value=report)

    app = _build_app_with_overrides(report_builder_mock=builder)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/hub/sites/{site_id}/report",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["site_name"] == "Test"
    assert data["totals_by_type"]["stale"] == 1


def test_get_report_export_docx_returns_bytes():
    """GET /hub/sites/{id}/report/export?format=docx → binario DOCX."""
    from server.app.modules.curation.report_contracts import (
        WebQualityReport,
    )
    from server.app.routers.hub_content_quality_router import get_report_exporter

    site_id = uuid.uuid4()
    report = WebQualityReport(
        site_id=site_id,
        site_name="Test",
        generated_at=NOW,
        totals_by_type={},
        totals_by_severity={},
        sections=[],
    )

    builder = MagicMock()
    builder.build = AsyncMock(return_value=report)

    exporter = MagicMock()
    exporter.to_docx = AsyncMock(return_value=b"PK fake docx bytes")

    app = _build_app_with_overrides(report_builder_mock=builder)
    app.dependency_overrides[get_report_exporter] = lambda: exporter

    client = TestClient(app)
    resp = client.get(
        f"/api/v1/hub/sites/{site_id}/report/export",
        params={"format": "docx"},
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/")
    assert len(resp.content) > 0


def test_post_analyze_returns_202():
    """POST /hub/sites/{id}/analyze → 202 y encola run_for_site."""
    from server.app.routers.hub_content_quality_router import router, get_quality_job
    from server.app.modules.agents_hub.database.connection import get_async_session

    site_id = uuid.uuid4()
    session = AsyncMock()
    # SEC.8.1: la guarda resuelve el sitio a su organización antes de encolar nada.
    session.get = AsyncMock(return_value=_duenio_de_la_org())

    quality_job = MagicMock()
    quality_job.run_for_site = AsyncMock()

    app = FastAPI()
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_quality_job] = lambda: quality_job
    app.include_router(router, prefix="/api/v1")

    client = TestClient(app)
    resp = client.post(
        f"/api/v1/hub/sites/{site_id}/analyze",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 202
