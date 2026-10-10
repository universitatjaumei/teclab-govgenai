"""#253 — borrar un chatbot se lleva sus trabajos de ingesta y sus `.md` fuente.

Encontrado en el inventario de retención (#162). `purgar_corpus_del_chatbot` (PIL.2) borraba
documentos y fragmentos y nada más: `hub_ingestion_jobs.chatbot_id` no tiene clave foránea, así que
los trabajos se quedaban, y con ellos el `.md` que cada uno guardó en `ingestion/{chatbot}/`.

Las filas se borran en la misma transacción que el corpus; los ficheros, **después** del commit,
como lo subido de una propuesta de script (#251): si el borrado de ficheros fallara antes, el
chatbot seguiría vivo apuntando a fuentes que ya no existen. Vale igual al borrar la organización,
que purga cada chatbot por el mismo camino (#252).

Contra base real, por HTTP y con almacenamiento en disco: lo que se prueba es lo que la cascada no
hace y lo que una sesión de mentira no ve.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

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


@pytest.fixture
def almacen(tmp_path):
    from server.app.core.storage import FsspecStorageService

    return FsspecStorageService(backend="file", bucket=str(tmp_path))


async def _chatbot_con_ingesta(sesion, almacen, org, llm_id) -> uuid.UUID:
    """Un chatbot con dos trabajos de ingesta, cada uno con su `.md` en el almacenamiento."""
    from server.app.modules.agents_hub.database.config_models import HubChatbot
    from server.app.modules.agents_hub.database.operational_models import HubIngestionJob

    bot = HubChatbot(organizacion_id=org, llm_config_id=llm_id, name=f"Bot {uuid.uuid4().hex[:6]}", system_prompt="x")
    sesion.add(bot)
    await sesion.flush()
    for _ in range(2):
        job_id = uuid.uuid4()
        clave = f"ingestion/{bot.id}/{job_id}.md"
        await almacen.put(clave, b"# Norma\n")
        sesion.add(HubIngestionJob(id=job_id, chatbot_id=bot.id, source_url=clave, status="completed"))
    await sesion.flush()
    return bot.id


@pytest.fixture
async def mundo(sesion, almacen):
    from server.app.modules.agents_hub.database.config_models import (
        HubLLMConfig,
        HubOrganizacion,
        HubProvider,
    )

    await sesion.merge(HubProvider(id="google", name="Google", provider_type="google_genai"))
    llm = HubLLMConfig(provider="google", model_name="gemini-2.0-flash", temperature=0.2)
    sesion.add(llm)
    org = uuid.uuid4()
    sesion.add(HubOrganizacion(id=org, name=f"Org {org.hex[:6]}", partner_id=f"p-{org.hex[:6]}"))
    await sesion.flush()
    borrado = await _chatbot_con_ingesta(sesion, almacen, org, llm.id)
    vecino = await _chatbot_con_ingesta(sesion, almacen, org, llm.id)
    await sesion.commit()
    return {"org": org, "borrado": borrado, "vecino": vecino}


def _cliente(sesion, almacen):
    from server.app.api.deps import get_current_user, modulos_concedidos
    from server.app.core.storage import get_storage_service
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.hub_chatbots_router import router as chatbots
    from server.app.routers.hub_organizaciones_router import router as organizaciones

    async def _s():
        yield sesion

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: _SUPERADMIN
    app.dependency_overrides[modulos_concedidos] = lambda: ["plataforma", "chatbots"]
    app.dependency_overrides[get_async_session] = _s
    app.dependency_overrides[get_storage_service] = lambda: almacen
    app.include_router(chatbots, prefix="/api/v1")
    app.include_router(organizaciones, prefix="/api/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _trabajos(sesion, chatbot_id) -> int:
    from server.app.modules.agents_hub.database.operational_models import HubIngestionJob

    fila = await sesion.execute(
        select(func.count(HubIngestionJob.id)).where(HubIngestionJob.chatbot_id == chatbot_id)
    )
    return int(fila.scalar_one() or 0)


async def _ficheros(almacen, chatbot_id) -> bool:
    return await almacen.exists(f"ingestion/{chatbot_id}")


@pytest.mark.asyncio
async def test_borrar_un_chatbot_se_lleva_sus_trabajos_y_sus_fuentes(sesion, almacen, mundo):
    async with _cliente(sesion, almacen) as c:
        r = await c.delete(f"/api/v1/hub/chatbots/{mundo['borrado']}")
    assert r.status_code == 204, r.text

    assert await _trabajos(sesion, mundo["borrado"]) == 0
    assert not await _ficheros(almacen, mundo["borrado"])
    # El vecino, intacto.
    assert await _trabajos(sesion, mundo["vecino"]) == 2
    assert await _ficheros(almacen, mundo["vecino"])


@pytest.mark.asyncio
async def test_borrar_la_organizacion_tambien(sesion, almacen, mundo):
    async with _cliente(sesion, almacen) as c:
        r = await c.delete(f"/api/v1/hub/organizaciones/{mundo['org']}")
    assert r.status_code == 204, r.text

    for bot in (mundo["borrado"], mundo["vecino"]):
        assert await _trabajos(sesion, bot) == 0
        assert not await _ficheros(almacen, bot)
