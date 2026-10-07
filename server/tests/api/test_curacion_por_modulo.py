"""La curación se concede por módulo, no por rol de administrador (2026-10-07).

**Cómo salió.** Dos compañeras van a curar la web de la Escuela de Doctorado. Los endpoints de
curación pedían rol `admin` o `superadmin` **y no comprobaban el módulo** `curacion`: el módulo
sólo escondía el menú. Para dejarlas curar había que hacerlas administradoras de la UJI, y eso
traía potestades que nada tienen que ver con curar.

**Decisión del usuario: basta el módulo.** Con rol `user` y el módulo `curacion`, se cura. Y lo
que toca el corpus de **un chatbot** —elegir páginas para él, ingerirlas, retirarlas, los
análisis de huecos y caducidades— pide además el módulo `chatbots`: con sólo `curacion` no se
pueden retirar páginas del asistente de normativa.

La organización la siguen acotando `assert_site_org_access` y `assert_chatbot_org_access`.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from server.app.core.auth.models import UserInfo


def _rutas_de(modulo_router):
    from fastapi.routing import APIRoute

    return [r for r in modulo_router.routes if isinstance(r, APIRoute)]


def _modulos_que_pide(dependant) -> set[str]:
    """Los códigos de `require_module(...)` en el árbol de dependencias de una ruta."""
    pedidos: set[str] = set()
    for dep in dependant.dependencies:
        llamada = dep.call
        if getattr(llamada, "__qualname__", "").startswith("require_module."):
            for celda in llamada.__closure__ or ():
                if isinstance(celda.cell_contents, str):
                    pedidos.add(celda.cell_contents)
        pedidos |= _modulos_que_pide(dep)
    return pedidos


def _roles_que_pide(dependant) -> bool:
    """Si alguna dependencia es la vieja puerta de rol de estos routers."""
    for dep in dependant.dependencies:
        if getattr(dep.call, "__name__", "") == "_require_admin":
            return True
        if _roles_que_pide(dep):
            return True
    return False


def _todas():
    from server.app.routers import hub_content_quality_router, hub_sites_router

    return _rutas_de(hub_sites_router.router) + _rutas_de(hub_content_quality_router.router)


def test_hay_rutas_que_mirar():
    assert len(_todas()) > 20


@pytest.mark.parametrize("ruta", _todas(), ids=lambda r: f"{sorted(r.methods)[0]} {r.path}")
def test_toda_ruta_de_curacion_pide_el_modulo_y_no_el_rol(ruta):
    assert "curacion" in _modulos_que_pide(ruta.dependant)
    assert not _roles_que_pide(ruta.dependant)


@pytest.mark.parametrize(
    "ruta",
    [r for r in _todas() if r.path.startswith(("/hub/chatbots/", "/hub/quality/"))],
    ids=lambda r: f"{sorted(r.methods)[0]} {r.path}",
)
def test_lo_que_toca_un_chatbot_pide_ademas_chatbots(ruta):
    assert "chatbots" in _modulos_que_pide(ruta.dependant)


@pytest.mark.parametrize(
    "ruta",
    [r for r in _todas() if not r.path.startswith(("/hub/chatbots/", "/hub/quality/"))],
    ids=lambda r: f"{sorted(r.methods)[0]} {r.path}",
)
def test_curar_un_sitio_no_pide_chatbots(ruta):
    assert "chatbots" not in _modulos_que_pide(ruta.dependant)


# --- Por HTTP, con una persona de rol `user` ---------------------------------------------------


@pytest.fixture
async def db_session(db_url: str):
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    motor = create_async_engine(db_url)
    async with create_session_factory(motor)() as s:
        yield s
    await motor.dispose()


def _app(db_session, principal: UserInfo, modulos: list[str]) -> FastAPI:
    from server.app.api.deps import get_current_user, modulos_concedidos
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.hub_sites_router import router

    async def _sesion():
        yield db_session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[modulos_concedidos] = lambda: modulos
    app.dependency_overrides[get_async_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return app


async def _get(app, url):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(url)


@pytest.mark.asyncio
async def test_una_usuaria_con_el_modulo_cura(db_session):
    usuaria = UserInfo(user_id=str(uuid.uuid4()), email="u@uji.es", role="user", organizacion_ids=(str(uuid.uuid4()),))
    r = await _get(_app(db_session, usuaria, ["curacion"]), "/api/v1/hub/sites")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_sin_el_modulo_no(db_session):
    admin = UserInfo(user_id=str(uuid.uuid4()), email="a@uji.es", role="admin", organizacion_ids=(str(uuid.uuid4()),))
    r = await _get(_app(db_session, admin, ["informes"]), "/api/v1/hub/sites")
    assert r.status_code == 403
    assert r.json()["detail"]["modulo_requerido"] == "curacion"


@pytest.mark.asyncio
async def test_con_solo_curacion_no_toca_el_corpus_de_un_chatbot(db_session):
    usuaria = UserInfo(user_id=str(uuid.uuid4()), email="u@uji.es", role="user", organizacion_ids=(str(uuid.uuid4()),))
    r = await _get(_app(db_session, usuaria, ["curacion"]), f"/api/v1/hub/chatbots/{uuid.uuid4()}/selections")
    assert r.status_code == 403
    assert r.json()["detail"]["modulo_requerido"] == "chatbots"


@pytest.mark.asyncio
async def test_una_usuaria_da_de_alta_un_sitio_en_su_organizacion(db_session):
    """Su pantalla no puede leer la lista de organizaciones (es de administración), así que el
    alta llega sin `organizacion_id`. Si pertenece a una sola, es ésa: no hay nada que elegir."""
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    org = uuid.uuid4()
    db_session.add(HubOrganizacion(id=org, name=f"Org {org.hex[:6]}", partner_id="uji"))
    await db_session.commit()
    usuaria = UserInfo(user_id=str(uuid.uuid4()), email="u@uji.es", role="user", organizacion_ids=(str(org),))

    app = _app(db_session, usuaria, ["curacion"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/v1/hub/sites",
            json={"name": "Escola de Doctorat", "root_url": f"https://www.uji.es/{org.hex[:6]}/"},
        )

    assert r.status_code == 201, r.text
    assert r.json()["organizacion_id"] == str(org)
