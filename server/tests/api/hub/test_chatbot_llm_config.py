"""Tests TDD — El modelo de un chatbot se puede cambiar, y hay UNA config por defecto (FIX.1).

Encontrado durante las pruebas manuales del Bloque RAG. `gemini-2.0-flash` quedó retirado por
Google y no había forma de mover el chatbot a otro modelo: el formulario hardcodeaba
`llm_config_id` y **`ChatbotUpdate` ni siquiera lo declaraba**, así que hubo que repuntarlo por
SQL. Y marcar otra configuración por defecto respondía 409 en lugar de relevar a la anterior.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.main import app
from server.app.modules.agents_hub.database.config_models import (
    HubChatbot,
    HubLLMConfig,
)
from server.app.api.deps import get_session
from server.tests.api.hub.test_chatbots import _make_chatbot

CHATBOT_ID = uuid.UUID("00000000-0000-0000-0000-000000000100")
CONFIG_VIEJA = uuid.UUID("00000000-0000-0000-0000-000000000001")
CONFIG_NUEVA = uuid.UUID("00000000-0000-0000-0000-0000000000aa")

# SEC.2: superadmin, para que estos tests sigan probando lo suyo y no la tenencia
# —que tiene su propio gate en `tests/api/test_tenant_isolation.py`—.
_ADMIN = UserInfo(user_id="root", email="root@test.com", role="superadmin")


def _chatbot() -> SimpleNamespace:
    """Se reutiliza el doble de `test_chatbots.py` en vez de mantener dos.

    El modelo de respuesta del PATCH lleva 26 campos; un doble propio se queda corto en
    cuanto alguien añade uno, y el síntoma es un 500 de validación de respuesta que no dice
    nada sobre lo que el test quería comprobar.
    """
    chatbot = _make_chatbot(chatbot_id=CHATBOT_ID)
    chatbot.llm_config_id = CONFIG_VIEJA
    chatbot.retrieval_mode = "RAG"
    return chatbot


def _config(config_id: uuid.UUID, *, tier: int = 1, is_default: bool = False):
    return SimpleNamespace(
        id=config_id,
        # MT.2 — el doble tiene que llevar la columna nueva: sin ella, `config.organizacion_id`
        # es un AttributeError y el endpoint devuelve 500. Es el mismo riesgo que anotó
        # `project_external_client_mock_spec`, en versión casera: un doble sin `spec` no avisa
        # de que el modelo ha cambiado, lo descubre el 500.
        organizacion_id=None,
        provider="google",
        model_name="gemini-2.5-flash",
        temperature=0.1,
        top_p=1.0,
        max_tokens=12000,
        api_key_secret_name=None,
        tier=tier,
        purpose="chat",
        output_dimensionality=None,
        label="Gemini 2.5 Flash",
        is_default=is_default,
    )


def _sesion(*, por_modelo: dict, filas: list | None = None):
    """Sesión falsa cuyo `get` distingue por clase, que es lo que este prompt necesita.

    El doble compartido de `test_chatbots.py` devuelve la misma fila para cualquier `get`,
    así que no puede expresar «el chatbot existe pero la configuración no», que es justo el
    caso que separa un 404 con mensaje de un IntegrityError a mitad de la petición.
    """
    session = MagicMock()

    async def _get(modelo, ident):
        return por_modelo.get(modelo)

    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = filas or []
    resultado.scalar_one_or_none.return_value = (filas or [None])[0]
    async def _refresh(obj, *args, **kwargs):
        # La BD asigna el id al hacer flush; sin esto el modelo de respuesta ve `id=None` y
        # el 500 de validación tapa lo que el test estaba comprobando.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(return_value=resultado)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=_refresh)
    return session


def _override(session):
    async def _dep():
        yield session
    return _dep


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[get_current_user] = lambda: _ADMIN
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


class TestCambiarElModeloDelChatbot:

    def test_should_change_the_model_of_an_existing_chatbot(self, client):
        chatbot = _chatbot()
        session = _sesion(
            por_modelo={HubChatbot: chatbot, HubLLMConfig: _config(CONFIG_NUEVA)}
        )
        app.dependency_overrides[get_session] = _override(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/chatbots/{CHATBOT_ID}",
                json={"llm_config_id": str(CONFIG_NUEVA)},
            )
            assert resp.status_code == 200, resp.text
            assert chatbot.llm_config_id == CONFIG_NUEVA
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_should_reject_an_unknown_llm_config_with_404(self, client):
        """Mejor un 404 con mensaje que un IntegrityError de la FK a mitad de la petición."""
        session = _sesion(por_modelo={HubChatbot: _chatbot(), HubLLMConfig: None})
        app.dependency_overrides[get_session] = _override(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/chatbots/{CHATBOT_ID}",
                json={"llm_config_id": str(uuid.uuid4())},
            )
            assert resp.status_code == 404
            assert "config" in resp.json()["detail"]["message"].lower()
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_should_not_touch_the_model_when_the_field_is_absent(self, client):
        """El riesgo real: una edición inocente no puede reasignar el modelo en silencio.

        Es lo que hacía el formulario al hardcodear `llm_config_id`: cambiar el nombre de un
        chatbot de Ollama lo pasaba a Gemini sin decir nada.
        """
        chatbot = _chatbot()
        session = _sesion(por_modelo={HubChatbot: chatbot, HubLLMConfig: None})
        app.dependency_overrides[get_session] = _override(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/chatbots/{CHATBOT_ID}", json={"name": "Otro nombre"}
            )
            assert resp.status_code == 200, resp.text
            assert chatbot.llm_config_id == CONFIG_VIEJA
        finally:
            app.dependency_overrides.pop(get_session, None)


class TestUnaSolaConfiguracionPorDefecto:

    def test_should_promote_to_default_demoting_the_previous_one(self, client):
        """«Que esta sea la de por defecto» es UNA operación, no dos peticiones y un hueco."""
        anterior = _config(CONFIG_VIEJA, is_default=True)
        nueva = _config(CONFIG_NUEVA, is_default=False)
        session = _sesion(por_modelo={HubLLMConfig: nueva}, filas=[anterior])
        app.dependency_overrides[get_session] = _override(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/llm-configs/{CONFIG_NUEVA}", json={"is_default": True}
            )
            assert resp.status_code == 200, resp.text
            assert nueva.is_default is True
            assert anterior.is_default is False, "la anterior sigue marcada por defecto"
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_should_promote_on_create_demoting_the_previous_one(self, client):
        anterior = _config(CONFIG_VIEJA, is_default=True)
        session = _sesion(por_modelo={}, filas=[anterior])
        app.dependency_overrides[get_session] = _override(session)
        try:
            resp = client.post(
                "/api/v1/hub/llm-configs",
                json={
                    "provider": "google",
                    "model_name": "gemini-2.5-flash",
                    "label": "Gemini 2.5 Flash",
                    "tier": 1,
                    "purpose": "chat",
                    "is_default": True,
                },
            )
            assert resp.status_code == 201, resp.text
            assert anterior.is_default is False
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_should_not_demote_defaults_of_another_tier(self, client):
        """Cada tier tiene la suya: promover en el 1 no puede dejar el 2 sin defecto."""
        otro_tier = _config(CONFIG_VIEJA, tier=2, is_default=True)
        nueva = _config(CONFIG_NUEVA, tier=1)
        # El filtro por tier corre en SQL, así que la consulta no devuelve la del tier 2.
        session = _sesion(por_modelo={HubLLMConfig: nueva}, filas=[])
        app.dependency_overrides[get_session] = _override(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/llm-configs/{CONFIG_NUEVA}", json={"is_default": True}
            )
            assert resp.status_code == 200, resp.text
            assert nueva.is_default is True
            assert otro_tier.is_default is True
        finally:
            app.dependency_overrides.pop(get_session, None)
