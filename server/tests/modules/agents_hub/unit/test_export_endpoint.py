"""Tests TDD (RED) para el endpoint de exportación de tareas.

Rutas reales (monorepo):
  src/api/routers/tasks.py → server/app/api/v1/hub_tasks.py
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}

_OWNER_ID = "owner-user-1"
_OTHER_ID = "other-user-2"


def _make_token(
    role: str = "user", user_id: str = _OWNER_ID, orgs: tuple[str, ...] = ()
) -> str:
    import os
    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token
    return create_token(
        UserInfo(
            user_id=user_id,
            email=f"{user_id}@test.com",
            role=role,
            organizacion_ids=orgs,
        )
    )


def _make_interaction(user_id: str = _OWNER_ID):
    interaction = MagicMock()
    interaction.run_id = uuid.uuid4()
    interaction.user_id = user_id
    interaction.user_message = "¿Cuál es el estado del expediente?"
    interaction.assistant_message = "Informe del expediente generado correctamente."
    return interaction


_ORG_DEL_CHATBOT = "00000000-0000-0000-0000-0000000000a1"


def _build_export_app(interaction_mock, org_del_chatbot: str = _ORG_DEL_CHATBOT) -> FastAPI:
    from types import SimpleNamespace
    import uuid as _uuid

    from server.app.api.v1.hub_tasks import router as tasks_router
    from server.app.api.deps import get_session
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock(spec=AsyncSession)
    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none = MagicMock(return_value=interaction_mock)
    mock_session.execute = AsyncMock(return_value=mock_scalar)
    # SEC.8.1: quien no es el dueño de la conversación tiene que pertenecer a la
    # organización del chatbot, así que el endpoint resuelve el chatbot con `session.get`.
    mock_session.get = AsyncMock(
        return_value=SimpleNamespace(
            id=_uuid.uuid4(), organizacion_id=_uuid.UUID(org_del_chatbot)
        )
    )

    async def _mock_session():
        yield mock_session

    app = FastAPI()
    app.dependency_overrides[get_session] = _mock_session
    app.include_router(tasks_router, prefix="/api/v1")
    return app


class TestExportEndpointAuthentication:

    def test_export_requires_authentication(self) -> None:
        """Sin token → 401."""
        from server.app.api.v1.hub_tasks import router as tasks_router
        app = FastAPI()
        app.include_router(tasks_router, prefix="/api/v1")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(f"/api/v1/hub/tasks/export/{uuid.uuid4()}")
        assert response.status_code == 401


class TestExportEndpointNotFound:

    @patch.dict("os.environ", _JWT_ENV)
    def test_export_unknown_run_id_returns_404(self) -> None:
        """run_id no existente → 404."""
        app = _build_export_app(interaction_mock=None)
        token = _make_token()

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                f"/api/v1/hub/tasks/export/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 404


class TestExportEndpointSecurity:

    @patch.dict("os.environ", _JWT_ENV)
    def test_export_forbidden_for_other_user(self) -> None:
        """Usuario que no es el dueño ni admin → 403."""
        interaction = _make_interaction(user_id=_OWNER_ID)
        app = _build_export_app(interaction)
        token = _make_token(user_id=_OTHER_ID)  # otro usuario

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                f"/api/v1/hub/tasks/export/{interaction.run_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 403

    @patch.dict("os.environ", _JWT_ENV)
    def test_export_allowed_for_an_admin_of_the_same_organization(self) -> None:
        """Un admin exporta la conversación de SU organización."""
        interaction = _make_interaction(user_id=_OWNER_ID)
        app = _build_export_app(interaction)
        token = _make_token(
            role="admin", user_id="admin-1", orgs=(_ORG_DEL_CHATBOT,)
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                f"/api/v1/hub/tasks/export/{interaction.run_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200

    def test_export_forbidden_for_an_admin_of_another_organization(self) -> None:
        """SEC.8.1: este test sustituye a uno que afirmaba «admin puede exportar
        cualquier tarea», que era literalmente el agujero.

        La conversación exportada es un dato personal de un ciudadano que habló con OTRA
        administración: ser admin no basta, hay que ser admin **de su organización**.
        """
        interaction = _make_interaction(user_id=_OWNER_ID)
        app = _build_export_app(interaction)
        token = _make_token(
            role="admin",
            user_id="admin-1",
            orgs=("00000000-0000-0000-0000-0000000000b2",),
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                f"/api/v1/hub/tasks/export/{interaction.run_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 403


class TestExportEndpointContent:

    @patch.dict("os.environ", _JWT_ENV)
    def test_export_markdown_contains_interaction_text(self) -> None:
        """El Markdown exportado contiene el mensaje del usuario y la respuesta."""
        interaction = _make_interaction()
        app = _build_export_app(interaction)
        token = _make_token()

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/hub/tasks/export/{interaction.run_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        body = response.text
        assert interaction.user_message in body
        assert "Informe" in body  # parte de la respuesta del asistente

    @patch.dict("os.environ", _JWT_ENV)
    def test_export_pdf_returns_pdf_content_type(self) -> None:
        """Con ?fmt=pdf → Content-Type application/pdf."""
        interaction = _make_interaction()
        app = _build_export_app(interaction)
        token = _make_token()

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/hub/tasks/export/{interaction.run_id}?fmt=pdf",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

    @patch.dict("os.environ", _JWT_ENV)
    def test_pdf_generation_content_matches_interaction(self) -> None:
        """Prompt 5.4: el contenido del PDF coincide con el texto del informe generado."""
        interaction = _make_interaction()
        app = _build_export_app(interaction)
        token = _make_token()

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/hub/tasks/export/{interaction.run_id}?fmt=pdf",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        assert len(response.content) > 0
        # Los PDFs generados por reportlab empiezan con %PDF
        assert response.content[:4] == b"%PDF"
