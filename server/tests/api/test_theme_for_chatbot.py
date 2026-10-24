"""Hallazgo #3 de MAN.2: el widget publico no consume ningun tema.

`GET /hub/themes/for-chatbot/{chatbot_id}` resuelve el tema aplicado a un chatbot (si lo
hay) para que el widget lo pinte. Dos cosas no son evidentes leyendo el codigo:

- **Solo devuelve `config`.** SEC.5 (`test_themes_security.py`) cerro `GET /{theme_id}`
  porque un tema lleva `organizacion_id` y sin guarda era un censo de organizaciones. Este
  endpoint no reabre ese hueco: nunca expone `theme_id`, `organizacion_id` ni `name`.
- **La guarda es la misma que abrir el chat** (`assert_chatbot_access`, SEC.2.1): quien no
  podria conversar con el chatbot tampoco ve de que color lo pintarian.

`POST /{theme_id}/apply/{chatbot_id}` completa el stub que dejaba `# TODO: actualizar
configuracion del chatbot en BD` sin persistir nada: ahora guarda `{"theme_id": ...}` en
`HubChatbot.theme_config`, la columna que no tenia lector ni escritor en ningun sitio.
"""
from __future__ import annotations


import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import perezoso evitado a proposito: `test_tenant_isolation.py` documenta que
# `hub_chatbots_router`/routers hermanos arrastran el chunker y pyarrow, cuya carga nativa
# revienta el proceso en Windows si ocurre a mitad de la sesion de pytest. `hub_themes_router`
# no tiene esa cadena de imports, pero se importa `server.app.main` primero de todas formas
# para fijar el mismo orden de carga que el resto de la suite.
import server.app.main  # noqa: F401
from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.api.deps import get_session
from server.app.routers.hub_themes_router import router

ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")


def _app_con(principal: UserInfo, session):
    async def _sesion():
        yield session

    from server.app.api.deps import get_current_user_optional

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    # SEC.8.5: el endpoint admite dos vías (sesión o credencial de sitio), así que depende
    # de la variante opcional; sin este override caería al 401 antes de mirar nada.
    app.dependency_overrides[get_current_user_optional] = lambda: principal
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False)


def _sesion_que_devuelve(entidad=None, tema=None, *, de_la_plataforma=None, de_la_organizacion=None):
    """SEC.8.6: el tema ya no se lee del disco, así que la sesión tiene que servir dos
    cosas distintas —el chatbot y su tema— y despachar por modelo.

    PLAT.6 le añadió una tercera: el endpoint **resuelve la cascada** —plataforma →
    organización → asistente— en vez de devolver el tema apuntado tal cual, así que la sesión
    tiene que contestar también a las consultas de los niveles de arriba. Por omisión no hay
    ninguno, que es el caso de los tests que ya existían.
    """
    from server.app.modules.agents_hub.database.config_models import HubTheme

    async def _get(model, _pk):
        return tema if model is HubTheme else entidad

    def _execute(consulta):
        # `_tema_mas_reciente` distingue los dos niveles por `organizacion_id`: `IS NULL` es
        # el de plataforma. Leerlo de la consulta compilada es frágil; basta con el orden en
        # que el endpoint los pide, que es plataforma primero.
        pedidos = list(niveles)
        siguiente = pedidos.pop(0) if pedidos else None
        niveles[:] = pedidos
        resultado = MagicMock()
        resultado.scalars.return_value.first.return_value = siguiente
        return resultado

    niveles = [de_la_plataforma, de_la_organizacion]
    session = MagicMock()
    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    return session


def _chatbot(
    access_mode="public_anon",
    organizacion_id=None,
    theme_config=None,
    allowed_roles=(),
    allowed_saml_groups=(),
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        access_mode=access_mode,
        organizacion_id=organizacion_id or ORG_A,
        allowed_roles=allowed_roles,
        allowed_saml_groups=allowed_saml_groups,
        theme_config=theme_config if theme_config is not None else {},
    )


def _anonimo() -> UserInfo:
    return UserInfo(user_id="visitante", email="v@test.com", role="user")


@pytest.fixture
def tema_en_disco():
    """El tema del chatbot. Desde SEC.8.6 es una fila, no un fichero (el nombre de la
    fixture se conserva para no tocar los diez tests que la usan)."""
    from datetime import datetime, timezone

    from server.app.modules.agents_hub.database.config_models import HubTheme

    return HubTheme(
        id=uuid.uuid4(),
        name="Tema del chatbot",
        organizacion_id=ORG_A,
        chatbot_id=None,
        is_default=False,
        config={"name": "chatbot-theme", "colors": {"primary": "#123456"}},
        created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )


class TestGetThemeForChatbot:
    def test_should_404_when_chatbot_does_not_exist(self):
        cliente = _app_con(_anonimo(), _sesion_que_devuelve(None))

        resp = cliente.get(f"/api/v1/hub/themes/for-chatbot/{uuid.uuid4()}")

        assert resp.status_code == 404

    def test_should_return_empty_config_when_no_theme_applied(self):
        chatbot = _chatbot(access_mode="public_anon", theme_config={})
        cliente = _app_con(_anonimo(), _sesion_que_devuelve(chatbot))

        resp = cliente.get(f"/api/v1/hub/themes/for-chatbot/{chatbot.id}")

        assert resp.status_code == 200
        assert resp.json() == {"config": {}}

    def test_should_resolve_the_applied_theme_config(self, tema_en_disco):
        chatbot = _chatbot(
            access_mode="public_anon", theme_config={"theme_id": str(tema_en_disco.id)}
        )
        cliente = _app_con(_anonimo(), _sesion_que_devuelve(chatbot, tema=tema_en_disco))

        resp = cliente.get(f"/api/v1/hub/themes/for-chatbot/{chatbot.id}")

        assert resp.status_code == 200
        assert resp.json() == {"config": {"name": "chatbot-theme", "colors": {"primary": "#123456"}}}

    def test_should_not_leak_theme_id_or_organizacion_id(self, tema_en_disco):
        """El disenio existe justo para no reabrir el censo de organizaciones de SEC.5."""
        chatbot = _chatbot(
            access_mode="public_anon", theme_config={"theme_id": str(tema_en_disco.id)}
        )
        cliente = _app_con(_anonimo(), _sesion_que_devuelve(chatbot, tema=tema_en_disco))

        resp = cliente.get(f"/api/v1/hub/themes/for-chatbot/{chatbot.id}")

        assert set(resp.json().keys()) == {"config"}

    def test_should_403_a_visitor_on_a_restricted_chatbot(self):
        chatbot = _chatbot(
            access_mode="restricted",
            organizacion_id=ORG_A,
            allowed_roles=("informer",),
        )
        # El visitante no pertenece a ORG_A ni tiene el rol permitido.
        cliente = _app_con(
            UserInfo(user_id="u", email="u@test.com", role="user", organizacion_ids=(str(ORG_B),)),
            _sesion_que_devuelve(chatbot),
        )

        resp = cliente.get(f"/api/v1/hub/themes/for-chatbot/{chatbot.id}")

        assert resp.status_code == 403

    def test_should_allow_a_superadmin_regardless_of_access_mode(self):
        chatbot = _chatbot(access_mode="restricted", organizacion_id=ORG_A)
        cliente = _app_con(
            UserInfo(user_id="root", email="root@test.com", role="superadmin"),
            _sesion_que_devuelve(chatbot),
        )

        resp = cliente.get(f"/api/v1/hub/themes/for-chatbot/{chatbot.id}")

        assert resp.status_code == 200


class TestApplyThemeToChatbot:
    def test_should_404_when_theme_does_not_exist(self):
        chatbot = _chatbot()
        cliente = _app_con(
            UserInfo(user_id="root", email="root@test.com", role="superadmin"),
            _sesion_que_devuelve(chatbot),
        )

        resp = cliente.post(f"/api/v1/hub/themes/{uuid.uuid4()}/apply/{chatbot.id}")

        assert resp.status_code == 404

    def test_should_404_when_chatbot_does_not_exist(self, tema_en_disco):
        cliente = _app_con(
            UserInfo(user_id="root", email="root@test.com", role="superadmin"),
            _sesion_que_devuelve(None, tema=tema_en_disco),
        )

        resp = cliente.post(f"/api/v1/hub/themes/{tema_en_disco.id}/apply/{uuid.uuid4()}")

        assert resp.status_code == 404

    def test_should_persist_the_applied_theme_id_on_the_chatbot(self, tema_en_disco):
        chatbot = _chatbot(theme_config={})
        session = _sesion_que_devuelve(chatbot, tema=tema_en_disco)
        cliente = _app_con(
            UserInfo(user_id="root", email="root@test.com", role="superadmin"), session
        )

        resp = cliente.post(f"/api/v1/hub/themes/{tema_en_disco.id}/apply/{chatbot.id}")

        assert resp.status_code == 200
        assert chatbot.theme_config == {"theme_id": str(tema_en_disco.id)}
        session.commit.assert_awaited_once()

    def test_should_require_superadmin(self, tema_en_disco):
        chatbot = _chatbot()
        cliente = _app_con(
            UserInfo(user_id="a", email="a@test.com", role="admin"),
            _sesion_que_devuelve(chatbot, tema=tema_en_disco),
        )

        resp = cliente.post(f"/api/v1/hub/themes/{tema_en_disco.id}/apply/{chatbot.id}")

        assert resp.status_code == 403
