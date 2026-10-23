"""Tests TDD para el router de prompt templates (Prompt 9E.3).

Deploy: cloud
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.modules.agents_hub.database.config_models import HubPromptTemplate
from server.app.api.deps import get_session

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}


# SEC.8.1: la plantilla no tiene organización propia —cuelga del chatbot—, así que el
# router resuelve el chatbot dueño antes de leer o escribir. Escribir en la plantilla ajena
# es controlar el prompt de sistema del asistente de otra administración.
ORG = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


def _make_token(role: str = "admin") -> str:
    import os
    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token
    return create_token(
        UserInfo(
            user_id="admin-1",
            email="admin@test.com",
            role=role,
            organizacion_ids=(str(ORG),),
        )
    )


def _make_template(**kwargs) -> HubPromptTemplate:
    defaults = dict(
        id=uuid.uuid4(),
        chatbot_id=uuid.uuid4(),
        slug="system_base",
        language="es",
        template_text="Eres un asistente de {empresa}.",
        version=1,
        default_tier=2,
        override_tier=None,
    )
    defaults.update(kwargs)
    m = MagicMock(spec=HubPromptTemplate)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _build_app(session_mock) -> FastAPI:
    from server.app.routers.hub_prompt_templates_router import router
    from types import SimpleNamespace

    # El chatbot dueño, que es a quien se le pregunta la organización.
    session_mock.get = AsyncMock(
        return_value=SimpleNamespace(id=uuid.uuid4(), organizacion_id=ORG)
    )

    async def _override():
        yield session_mock

    app = FastAPI()
    app.dependency_overrides[get_session] = _override
    app.include_router(router, prefix="/api/v1")
    return app


class TestPromptTemplatesRouter:

    def test_should_list_prompt_templates(self):
        tmpl = _make_template()
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [tmpl]
        session.execute = AsyncMock(return_value=result)

        client = TestClient(_build_app(session))
        resp = client.get(
            "/api/v1/hub/prompt-templates",
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["slug"] == "system_base"
        assert data[0]["version"] == 1

    def test_should_create_prompt_template_with_version_1(self):
        chatbot_id = uuid.uuid4()
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock(
            side_effect=lambda obj: setattr(obj, "id", uuid.uuid4())
        )

        client = TestClient(_build_app(session))
        resp = client.post(
            "/api/v1/hub/prompt-templates",
            json={
                "chatbot_id": str(chatbot_id),
                "slug": "system_base",
                "language": "es",
                "template_text": "Eres un asistente de {empresa}.",
                "default_tier": 2,
            },
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 201
        assert resp.json()["version"] == 1

    def test_should_increment_version_on_save(self):
        tmpl = _make_template(version=3)
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = tmpl
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        client = TestClient(_build_app(session))
        resp = client.patch(
            f"/api/v1/hub/prompt-templates/{tmpl.id}",
            json={"template_text": "Nuevo texto con {variable}."},
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 200
        assert tmpl.version == 4
        assert tmpl.template_text == "Nuevo texto con {variable}."

    def test_should_not_increment_version_without_text_change(self):
        tmpl = _make_template(version=2)
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = tmpl
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        client = TestClient(_build_app(session))
        resp = client.patch(
            f"/api/v1/hub/prompt-templates/{tmpl.id}",
            json={"default_tier": 3},
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 200
        assert tmpl.version == 2

    def test_should_delete_prompt_template(self):
        tmpl = _make_template()
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = tmpl
        session.execute = AsyncMock(return_value=result)
        session.delete = AsyncMock()
        session.commit = AsyncMock()

        client = TestClient(_build_app(session))
        resp = client.delete(
            f"/api/v1/hub/prompt-templates/{tmpl.id}",
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 204

    def test_should_return_404_for_missing_template(self):
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        client = TestClient(_build_app(session))
        resp = client.patch(
            f"/api/v1/hub/prompt-templates/{uuid.uuid4()}",
            json={"template_text": "x"},
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert resp.status_code == 404
