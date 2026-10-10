"""Tests para el endpoint /api/v1/hub/organizaciones (ROL.1)."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from server.app.core.auth.models import UserInfo
from server.app.main import app
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.api.deps import get_current_user

DEV_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")

# SEC.2: superadmin, para que estos tests sigan probando lo suyo y no la tenencia
# —que tiene su propio gate en `tests/api/test_tenant_isolation.py`—.
_ADMIN = UserInfo(user_id="root", email="root@test.com", role="superadmin")


def _make_organizacion(name: str = "UJI", is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=DEV_ORG_ID,
        name=name,
        partner_id="partner-1",
        theme_config={},
        is_active=is_active,
        default_public_graph_profile="PUBLIC_KB_RICH",
        default_retrieval_mode="RAG",
        default_language_mode="prefer",
        default_quality_threshold=0.6,
        default_min_retrieval_results=2,
        default_min_retrieval_score=0.25,
        default_reranker_enabled=True,
        default_answer_template="generic",
        default_context_token_budget=None,  # VIS.2: None = heredar el default de plataforma
        default_chunk_size=None,  # RAG.8
        default_chunk_overlap=None,
        default_chunking_strategy=None,
        default_query_rewriting_enabled=None,  # RAG.10
        rewrite_llm_config_id=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _session_for_list(rows_with_count: list):
    """Session mock para el endpoint list (devuelve tuplas (organizacion, count))."""
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = rows_with_count
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=rows_with_count[0][0] if rows_with_count else None)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _session_for_crud(org_obj=None):
    """Session mock para create/patch/delete."""
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = []
    # #252 — borrar cuenta antes lo que le queda a la organización; vacía, cero de todo.
    result.scalar_one.return_value = 0
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=org_obj)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _override_session(session):
    async def _dep():
        yield session
    return _dep


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user] = lambda: _ADMIN
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


class TestListOrganizaciones:
    def test_returns_list_of_organizaciones(self, client):
        o = _make_organizacion()
        session = _session_for_list([(o, 3)])
        app.dependency_overrides[get_async_session] = _override_session(session)
        try:
            resp = client.get("/api/v1/hub/organizaciones")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert data[0]["name"] == "UJI"
            assert data[0]["chatbot_count"] == 3
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_returns_empty_list(self, client):
        session = _session_for_list([])
        app.dependency_overrides[get_async_session] = _override_session(session)
        try:
            resp = client.get("/api/v1/hub/organizaciones")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_requires_auth(self, client):
        app.dependency_overrides.pop(get_current_user, None)
        try:
            resp = client.get("/api/v1/hub/organizaciones")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides[get_current_user] = lambda: _ADMIN


class TestCreateOrganizacion:
    def test_creates_organizacion_returns_201(self, client):
        created = _make_organizacion("Nueva Institución")
        session = _session_for_crud()

        async def _refresh(obj):
            obj.id = DEV_ORG_ID
            obj.created_at = created.created_at
            obj.updated_at = created.updated_at

        session.refresh = _refresh
        app.dependency_overrides[get_async_session] = _override_session(session)
        try:
            resp = client.post(
                "/api/v1/hub/organizaciones",
                json={"name": "Nueva Institución", "partner_id": "partner-1"},
            )
            assert resp.status_code == 201
            assert resp.json()["name"] == "Nueva Institución"
            assert resp.json()["partner_id"] == "partner-1"
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_requires_name_and_partner_id(self, client):
        session = _session_for_crud()
        app.dependency_overrides[get_async_session] = _override_session(session)
        try:
            resp = client.post("/api/v1/hub/organizaciones", json={"name": "Solo nombre"})
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_async_session, None)


class TestUpdateOrganizacion:
    def test_updates_name_returns_200(self, client):
        o = _make_organizacion("Original")

        async def _refresh(obj):
            pass

        session = _session_for_crud(o)
        session.refresh = _refresh
        app.dependency_overrides[get_async_session] = _override_session(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/organizaciones/{DEV_ORG_ID}",
                json={"name": "Actualizado"},
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "Actualizado"
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_returns_404_for_unknown_id(self, client):
        session = _session_for_crud(None)
        app.dependency_overrides[get_async_session] = _override_session(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/organizaciones/{uuid.uuid4()}",
                json={"name": "x"},
            )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_async_session, None)


class TestDeleteOrganizacion:
    def test_deletes_organizacion_returns_204(self, client):
        o = _make_organizacion()
        session = _session_for_crud(o)
        app.dependency_overrides[get_async_session] = _override_session(session)
        try:
            resp = client.delete(f"/api/v1/hub/organizaciones/{DEV_ORG_ID}")
            assert resp.status_code == 204
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_returns_404_for_unknown_id(self, client):
        session = _session_for_crud(None)
        app.dependency_overrides[get_async_session] = _override_session(session)
        try:
            resp = client.delete(f"/api/v1/hub/organizaciones/{uuid.uuid4()}")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_async_session, None)
