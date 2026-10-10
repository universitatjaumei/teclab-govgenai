"""#242 — en curación, el id hijo tiene que ser del sitio o del asistente de la ruta.

Encontrado en la revisión independiente de la PR #241. Tres rutas comprobaban la organización del
sitio o del asistente que venía en la ruta, pero **no que el id hijo les perteneciera**:

- ingerir en el asistente de A una página rastreada de B metía el contenido de B en el corpus de A;
- borrar una selección pasaba por el asistente de A pero borraba la selección de B;
- cambiar el estado de un hallazgo pasaba por el sitio de A pero cambiaba el de B, y un id que no
  existe daba un 500.

Las tres exigen un UUID ajeno, pero desde #241 las alcanza cualquiera con el módulo de curación.
Un hijo ajeno es un **404**: decir «existe y no es tuyo» ya cuenta que existe.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from server.app.core.auth.models import UserInfo

_SUPERADMIN = UserInfo(user_id=str(uuid.uuid4()), email="sa@uji.es", role="superadmin")


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


async def _organizacion_completa(sesion, llm_id) -> dict:
    """Una organización con su sitio, una página, un asistente, una selección y un hallazgo."""
    from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion
    from server.app.modules.agents_hub.database.operational_models import (
        HubContentFinding,
        HubCorpusSelection,
    )
    from server.app.modules.curation.site_repo import CrawledPageRepo, WebSiteRepo

    org = uuid.uuid4()
    sesion.add(HubOrganizacion(id=org, name=f"Org {org.hex[:6]}", partner_id=f"p-{org.hex[:6]}"))
    await sesion.flush()
    sitio = await WebSiteRepo(sesion).create(organizacion_id=org, name="Sitio", root_url=f"https://s{org.hex[:6]}.es/")
    pagina = await CrawledPageRepo(sesion).upsert(site_id=sitio.id, url=f"{sitio.root_url}a/", title="A")
    bot = HubChatbot(organizacion_id=org, llm_config_id=llm_id, name=f"Bot {org.hex[:6]}", system_prompt="x")
    sesion.add(bot)
    await sesion.flush()
    seleccion = HubCorpusSelection(chatbot_id=bot.id, site_id=sitio.id, rule_type="path_prefix", rule_value="/a/")
    hallazgo = HubContentFinding(
        site_id=sitio.id, finding_type="stale", severity="warning", confidence=0.9,
        page_id=pagina.id, status="new", detected_at=datetime.now(timezone.utc), signal_json={},
    )
    sesion.add_all([seleccion, hallazgo])
    await sesion.flush()
    ids = {
        "org": str(org), "sitio": sitio.id, "pagina": pagina.id, "bot": bot.id,
        "seleccion": seleccion.id, "hallazgo": hallazgo.id,
    }
    return ids


@pytest.fixture
async def dos(sesion):
    from server.app.modules.agents_hub.database.config_models import HubLLMConfig, HubProvider

    await sesion.merge(HubProvider(id="google", name="Google", provider_type="google_genai"))
    llm = HubLLMConfig(provider="google", model_name="gemini-2.0-flash", temperature=0.2)
    sesion.add(llm)
    await sesion.flush()
    a = await _organizacion_completa(sesion, llm.id)
    b = await _organizacion_completa(sesion, llm.id)
    await sesion.commit()
    return a, b


def _cliente(sesion, principal: UserInfo = _SUPERADMIN):
    from server.app.api.deps import get_current_user, modulos_concedidos
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.hub_content_quality_router import router as calidad
    from server.app.routers.hub_sites_router import router as sitios

    async def _s():
        yield sesion

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[modulos_concedidos] = lambda: ["curacion", "chatbots"]
    app.dependency_overrides[get_async_session] = _s
    app.include_router(sitios, prefix="/api/v1")
    app.include_router(calidad, prefix="/api/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_no_se_ingiere_en_un_asistente_una_pagina_de_otra_organizacion(sesion, dos):
    a, b = dos
    async with _cliente(sesion) as c:
        r = await c.post(f"/api/v1/hub/chatbots/{a['bot']}/pages/{b['pagina']}/ingest")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_no_se_borra_una_seleccion_de_otro_asistente(sesion, dos):
    from server.app.modules.agents_hub.database.operational_models import HubCorpusSelection

    a, b = dos
    async with _cliente(sesion) as c:
        r = await c.delete(f"/api/v1/hub/chatbots/{a['bot']}/selections/{b['seleccion']}")
    assert r.status_code == 404, r.text
    sesion.expire_all()
    assert await sesion.get(HubCorpusSelection, b["seleccion"]) is not None


@pytest.mark.asyncio
async def test_no_se_cambia_un_hallazgo_de_otro_sitio(sesion, dos):
    from server.app.modules.agents_hub.database.operational_models import HubContentFinding

    a, b = dos
    async with _cliente(sesion) as c:
        r = await c.patch(
            f"/api/v1/hub/sites/{a['sitio']}/findings/{b['hallazgo']}", json={"new_status": "dismissed"}
        )
    assert r.status_code == 404, r.text
    sesion.expire_all()
    assert (await sesion.get(HubContentFinding, b["hallazgo"])).status == "new"


@pytest.mark.asyncio
async def test_un_hallazgo_que_no_existe_es_404_y_no_500(sesion, dos):
    a, _b = dos
    async with _cliente(sesion) as c:
        r = await c.patch(f"/api/v1/hub/sites/{a['sitio']}/findings/{uuid.uuid4()}", json={"new_status": "dismissed"})
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_lo_propio_sigue_funcionando(sesion, dos):
    a, _b = dos
    async with _cliente(sesion) as c:
        r1 = await c.patch(
            f"/api/v1/hub/sites/{a['sitio']}/findings/{a['hallazgo']}", json={"new_status": "dismissed"}
        )
        r2 = await c.delete(f"/api/v1/hub/chatbots/{a['bot']}/selections/{a['seleccion']}")
    assert r1.status_code == 200, r1.text
    assert r2.status_code in (200, 204), r2.text
