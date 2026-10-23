"""Temas: autenticación en la lectura y rutas que no salen del directorio (SEC.5, M2).

Dos agujeros, y el primero es de manual: `_theme_path` concatenaba lo que llegara en la URL
con el directorio de temas. Con `../` se leía cualquier `.json` del servidor, y como
`DELETE` usa la misma función, también se borraba.

El segundo es menos aparatoso y más incómodo de explicar: `GET /hub/themes/{id}` era
**público**. Un tema no es un secreto de estado, pero lleva los colores, el logotipo y el
nombre de la organización a la que pertenece, así que servía un censo de clientes sin pedir
nada a cambio.

**SEC.8.6 cambió el almacén, no el criterio.** Los temas son filas y ya no hay ruta que
recorrer, así que la comprobación del destino resuelto desapareció con el fichero. La
validación de **forma** del identificador se conserva y estos tests la siguen exigiendo:
sigue siendo la primera barrera, y lo que no tiene forma de identificador ni llega a
consultarse.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import server.app.main  # noqa: F401 — fija el orden de carga; ver test_chatbot_availability
from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.api.deps import get_session
from server.app.routers.hub_themes_router import router

ORG_A = str(uuid.UUID("00000000-0000-0000-0000-0000000000a1"))
ORG_B = str(uuid.UUID("00000000-0000-0000-0000-0000000000b2"))


def _sesion_con(tema=None):
    """Sesión doblada que devuelve este tema para cualquier `get` (SEC.8.6).

    Los temas vivían en disco y estos tests los escribían allí; ahora son filas, así que
    lo que hay que doblar es la sesión.
    """
    from unittest.mock import AsyncMock, MagicMock

    session = MagicMock()
    session.get = AsyncMock(return_value=tema)
    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = [tema] if tema else []
    session.execute = AsyncMock(return_value=resultado)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


def _app(
    rol: str = "admin",
    orgs: tuple[str, ...] = (ORG_A,),
    anonimo: bool = False,
    tema=None,
):
    app = FastAPI()
    if not anonimo:
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="admin-1", email="a@uji.es", role=rol, organizacion_ids=orgs
        )

    sesion = _sesion_con(tema)

    async def _sesion():
        yield sesion

    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def tema_de_org_b():
    """Un tema de una organización ajena, como fila y no como fichero."""
    from datetime import datetime, timezone

    from server.app.modules.agents_hub.database.config_models import HubTheme

    return HubTheme(
        id=uuid.uuid4(),
        name="Tema ajeno",
        organizacion_id=uuid.UUID(ORG_B),
        chatbot_id=None,
        is_default=False,
        config={"name": "ajeno", "version": "1.0.0"},
        created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )


class TestRutasQueNoSalenDelDirectorio:

    @pytest.mark.parametrize(
        "identificador",
        [
            "../secretos",
            "..%2Fsecretos",
            "....//secretos",
            "/etc/passwd",
            "C:/Windows/win",
            "tema.json",
            "TEMA",
            "tema con espacios",
        ],
    )
    def test_should_reject_theme_id_with_path_traversal(self, identificador):
        """SEC.8.6: ya no hay ruta que recorrer —los temas son filas—, pero la validación
        de forma se conserva y sigue siendo la primera barrera: lo que no tiene forma de
        identificador no llega a consultarse."""
        from server.app.routers.hub_themes_router import _assert_id_de_tema

        with pytest.raises(HTTPException) as exc:
            _assert_id_de_tema(identificador)
        assert exc.value.status_code == 400

    def test_should_accept_a_uuid_shaped_identifier(self):
        from server.app.routers.hub_themes_router import _assert_id_de_tema

        identificador = uuid.uuid4()
        assert _assert_id_de_tema(str(identificador)) == identificador

    def test_should_reject_traversal_over_http_on_every_verb(self):
        cliente = _app(rol="superadmin")

        for respuesta in (
            cliente.get("/api/v1/hub/themes/..%2Fsenuelo"),
            cliente.put(
                "/api/v1/hub/themes/..%2Fsenuelo",
                json={"config": {"name": "x", "version": "1.0.0"}},
            ),
            cliente.delete("/api/v1/hub/themes/..%2Fsenuelo"),
        ):
            assert respuesta.status_code in (400, 404), respuesta.text
            assert respuesta.status_code != 500


class TestAutenticacionEnLaLectura:

    def test_should_require_auth_on_get_theme(self, tema_de_org_b):
        anonimo = _app(anonimo=True, tema=tema_de_org_b)

        respuesta = anonimo.get(f"/api/v1/hub/themes/{tema_de_org_b.id}")

        assert respuesta.status_code == 401

    def test_should_forbid_reading_a_theme_of_another_org(self, tema_de_org_b):
        """SEC.2 llega también aquí: el tema lleva el nombre de su organización."""
        cliente = _app(orgs=(ORG_A,), tema=tema_de_org_b)

        respuesta = cliente.get(f"/api/v1/hub/themes/{tema_de_org_b.id}")

        assert respuesta.status_code == 403

    def test_should_allow_reading_a_theme_of_your_own_org(self, tema_de_org_b):
        cliente = _app(orgs=(ORG_B,), tema=tema_de_org_b)

        respuesta = cliente.get(f"/api/v1/hub/themes/{tema_de_org_b.id}")

        assert respuesta.status_code == 200
        assert respuesta.json()["name"] == "Tema ajeno"

    def test_should_let_any_admin_read_a_platform_theme(self):
        """Los temas de plataforma son la base de la cascada: no son de nadie."""
        cliente = _app(orgs=(ORG_A,))
        presets = cliente.get("/api/v1/hub/themes/presets")

        # Los presets siguen siendo públicos: son cuatro nombres, no configuración de nadie.
        assert presets.status_code == 200
