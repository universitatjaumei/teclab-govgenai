"""#319 — Elegir el modelo de un chatbot no es administrar la plataforma.

`ChatbotsPage` llena su selector «Modelo de lenguaje» con `GET /hub/llm-configs`, y el router
exigía `plataforma` entero (INF.7). Un administrador con `chatbots` y sin `plataforma` recibía un
403, veía el selector vacío y no podía guardar ningún chatbot. Pasó en producción, con el primer
usuario de la UJI que no era superadministrador.

Es el defecto que PLAT.5 ya corrigió en organizaciones: leer la lista sólo exige ser
administrador, y el módulo se exige por endpoint. Lo que se pierde al bajar el módulo del router
es que un endpoint nuevo no lo pueda olvidar; eso lo recupera el último test.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.core.auth.models import UserInfo

ORG = "00000000-0000-0000-0000-0000000000a1"


def _admin() -> UserInfo:
    return UserInfo(user_id="admin-1", email="a@example.org", role="admin", organizacion_ids=(ORG,))


def _sesion():
    session = MagicMock()
    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=resultado)
    session.get = AsyncMock(return_value=SimpleNamespace(id="google"))
    session.commit = AsyncMock()
    return session


def _cliente(modulos: list[str], session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.app.api.deps import get_current_user, get_session, modulos_concedidos
    from server.app.routers.hub_llm_configs_router import router

    async def _sesion_override():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = _admin
    app.dependency_overrides[get_session] = _sesion_override
    app.dependency_overrides[modulos_concedidos] = lambda: modulos
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


@pytest.mark.parametrize("modulo", ["chatbots", "plataforma"])
def test_quien_administra_chatbots_o_la_plataforma_puede_leer_los_modelos(modulo):
    resp = _cliente([modulo], _sesion()).get("/api/v1/hub/llm-configs")

    assert resp.status_code == 200


def test_sin_chatbots_ni_plataforma_no_se_leen_los_modelos():
    """Revisión de la PR #320: el listado quedó sin ningún módulo, así que un administrador que
    sólo tenía `informes` leía modelos, proveedores y nombres de secreto de la plataforma. Lo
    que hacía falta era dejar pasar a Chatbots, no a todo el mundo."""
    session = _sesion()

    resp = _cliente(["informes", "utilidades"], session).get("/api/v1/hub/llm-configs")

    assert resp.status_code == 403
    assert resp.json()["detail"]["modulos_requeridos"] == ["chatbots", "plataforma"]
    session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("get", "/api/v1/hub/llm-configs/providers", None),
        ("get", "/api/v1/hub/llm-configs/available-models/google", None),
        (
            "post",
            "/api/v1/hub/llm-configs",
            {"provider": "google", "model_name": "m", "label": "x", "tier": 1},
        ),
        ("patch", f"/api/v1/hub/llm-configs/{ORG}", {"label": "y"}),
        ("delete", f"/api/v1/hub/llm-configs/{ORG}", None),
        ("post", f"/api/v1/hub/llm-configs/{ORG}/test", None),
    ],
)
def test_lo_demas_sigue_siendo_de_la_plataforma(metodo, ruta, cuerpo):
    session = _sesion()
    cliente = _cliente(["chatbots"], session)

    resp = cliente.request(metodo, ruta, json=cuerpo)

    assert resp.status_code == 403
    assert resp.json()["detail"]["modulo_requerido"] == "plataforma"
    session.commit.assert_not_awaited()


def test_un_endpoint_nuevo_no_puede_olvidar_el_modulo():
    """Sustituye a la dependencia a nivel de router: sólo el listado se libra de `plataforma`."""
    from fastapi.routing import APIRoute

    from server.app.api.deps import modulos_concedidos
    from server.app.routers.hub_llm_configs_router import router

    def _exige_plataforma(ruta: APIRoute) -> bool:
        pendientes = list(ruta.dependant.dependencies)
        while pendientes:
            dep = pendientes.pop()
            celdas = getattr(dep.call, "__closure__", None) or ()
            if any(sub.call is modulos_concedidos for sub in dep.dependencies) and any(
                c.cell_contents == "plataforma" for c in celdas
            ):
                return True
            pendientes.extend(dep.dependencies)
        return False

    libres = sorted(
        (sorted(r.methods or ())[0], r.path)
        for r in router.routes
        if isinstance(r, APIRoute) and not _exige_plataforma(r)
    )

    assert libres == [("GET", "/hub/llm-configs")]
