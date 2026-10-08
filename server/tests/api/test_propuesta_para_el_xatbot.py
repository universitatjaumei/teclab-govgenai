"""Proponer páginas para un asistente mientras se cura la web (2026-10-08).

Piloto de un asistente alimentado desde la web de la Escuela de Doctorado. Quien cura con el
módulo `curacion` revisa la web y, a la vez, **propone** qué páginas deberían alimentar el
asistente; quien lo crea —con el módulo `chatbots`— decide y las publica en Publicación.

Hasta ahora no había forma: Publicación trabaja asistente a asistente, sus marcas vivían sólo en
el navegador y «marcar» era publicar. Decisión del usuario: una marca **guardada por página e
independiente de cualquier asistente**, con quién la puso y cuándo.

Lo que fija este fichero, por HTTP y contra la base:
- se marca y se desmarca con el módulo `curacion` (rol `user` basta);
- se lista filtrando por propuestas;
- **una página de otro sitio es un 404**, no una marca puesta por la puerta de atrás (la lección
  de #242);
- **un nuevo rastreo no la borra**: el trabajo de revisar no se puede perder al actualizar la web.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from server.app.core.auth.models import UserInfo


@pytest.fixture
async def sesion(db_url: str):
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    motor = create_async_engine(db_url)
    async with create_session_factory(motor)() as s:
        yield s
    await motor.dispose()


async def _escenario(sesion):
    """Una organización, dos sitios suyos y una página en cada uno."""
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion
    from server.app.modules.curation.site_repo import CrawledPageRepo, WebSiteRepo

    org = uuid.uuid4()
    sesion.add(HubOrganizacion(id=org, name=f"Org {org.hex[:6]}", partner_id="uji"))
    await sesion.flush()
    sitio = await WebSiteRepo(sesion).create(organizacion_id=org, name="Escola", root_url=f"https://e{org.hex[:6]}.es/")
    otro = await WebSiteRepo(sesion).create(organizacion_id=org, name="Altre", root_url=f"https://a{org.hex[:6]}.es/")
    pagina = await CrawledPageRepo(sesion).upsert(site_id=sitio.id, url=f"{sitio.root_url}beques/", title="Beques")
    ajena = await CrawledPageRepo(sesion).upsert(site_id=otro.id, url=f"{otro.root_url}x/", title="X")
    ids = (str(org), sitio.id, pagina.id, ajena.id, sitio.root_url)
    await sesion.commit()
    return ids


def _cliente(sesion, principal: UserInfo, modulos: list[str]):
    from server.app.api.deps import get_current_user, modulos_concedidos
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.hub_sites_router import router

    async def _s():
        yield sesion

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[modulos_concedidos] = lambda: modulos
    app.dependency_overrides[get_async_session] = _s
    app.include_router(router, prefix="/api/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _curadora(org: str) -> UserInfo:
    return UserInfo(user_id=str(uuid.uuid4()), email="curadora@uji.es", role="user", organizacion_ids=(org,))


@pytest.mark.asyncio
async def test_se_propone_y_se_lista_con_quien_y_cuando(sesion):
    org, sitio, pagina, _ajena, _raiz = await _escenario(sesion)
    async with _cliente(sesion, _curadora(org), ["curacion"]) as c:
        r = await c.put(f"/api/v1/hub/sites/{sitio}/pages/{pagina}/propuesta")
        assert r.status_code == 200, r.text
        assert r.json()["propuesta_por"] == "curadora@uji.es"
        assert r.json()["propuesta_at"]

        propuestas = await c.get(f"/api/v1/hub/sites/{sitio}/pages", params={"propuestas": True})
    assert [p["id"] for p in propuestas.json()] == [str(pagina)]


@pytest.mark.asyncio
async def test_se_desmarca(sesion):
    org, sitio, pagina, _ajena, _raiz = await _escenario(sesion)
    async with _cliente(sesion, _curadora(org), ["curacion"]) as c:
        await c.put(f"/api/v1/hub/sites/{sitio}/pages/{pagina}/propuesta")
        r = await c.delete(f"/api/v1/hub/sites/{sitio}/pages/{pagina}/propuesta")
        assert r.status_code == 200, r.text
        assert r.json()["propuesta_at"] is None
        propuestas = await c.get(f"/api/v1/hub/sites/{sitio}/pages", params={"propuestas": True})
    assert propuestas.json() == []


@pytest.mark.asyncio
async def test_una_pagina_de_otro_sitio_es_404(sesion):
    org, sitio, _pagina, ajena, _raiz = await _escenario(sesion)
    async with _cliente(sesion, _curadora(org), ["curacion"]) as c:
        r = await c.put(f"/api/v1/hub/sites/{sitio}/pages/{ajena}/propuesta")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_sin_el_modulo_de_curacion_no(sesion):
    org, sitio, pagina, _ajena, _raiz = await _escenario(sesion)
    async with _cliente(sesion, _curadora(org), ["informes"]) as c:
        r = await c.put(f"/api/v1/hub/sites/{sitio}/pages/{pagina}/propuesta")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_un_nuevo_rastreo_no_borra_la_propuesta(sesion):
    from server.app.modules.curation.site_repo import CrawledPageRepo

    org, sitio, pagina, _ajena, raiz = await _escenario(sesion)
    async with _cliente(sesion, _curadora(org), ["curacion"]) as c:
        await c.put(f"/api/v1/hub/sites/{sitio}/pages/{pagina}/propuesta")

    # El rastreo actualiza la página por su URL con lo que trae del portal.
    await CrawledPageRepo(sesion).upsert(site_id=sitio, url=f"{raiz}beques/", title="Beques 2026-27", token_count=900)
    await sesion.commit()

    async with _cliente(sesion, _curadora(org), ["curacion"]) as c:
        propuestas = await c.get(f"/api/v1/hub/sites/{sitio}/pages", params={"propuestas": True})
    assert [p["title"] for p in propuestas.json()] == ["Beques 2026-27"]
    assert propuestas.json()[0]["propuesta_por"] == "curadora@uji.es"


def test_publicacion_ve_la_propuesta():
    """Quien crea el asistente filtra por propuestas en Publicación: el candidato la trae."""
    from server.app.modules.curation.selection_contracts import CandidatePageView

    assert {"propuesta_at", "propuesta_por"} <= set(CandidatePageView.model_fields)
