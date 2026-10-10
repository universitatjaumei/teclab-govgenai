"""#252 — borrar una organización se lleva el corpus de sus chatbots.

Encontrado en el inventario de retención (#162). `delete_organizacion` borraba la organización y
dejaba que Postgres cascadeara a sus chatbots, pero el corpus no cuelga del chatbot por clave
foránea —`hub_documents.chatbot_id` no la tiene desde el reparto edge/cloud—, y por eso
`delete_chatbot` llama antes a `purgar_corpus_del_chatbot` (PIL.2). Borrar la organización se
saltaba esa purga: documentos, fragmentos y embeddings de todos sus chatbots quedaban sin dueño.

Ahora pasa por el mismo camino que borrar un chatbot, en la misma transacción. Y con la misma
regla: **las interacciones se quedan**, porque son el registro de lo que el asistente contestó.

Contra base real y por HTTP: un `AsyncMock` no sabe nada de cascadas, y lo que se prueba es
justo lo que la cascada no hace.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from server.app.core.auth.models import UserInfo
from server.tests.modules.agents_hub.integration.test_metadata_filter import _chunk, _documento

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


async def _organizacion_con_corpus(sesion, llm_id) -> dict:
    """Una organización con dos chatbots, cada uno con un documento, dos fragmentos y una
    interacción."""
    from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion
    from server.app.modules.agents_hub.database.operational_models import HubInteraction

    org = uuid.uuid4()
    sesion.add(HubOrganizacion(id=org, name=f"Org {org.hex[:6]}", partner_id=f"p-{org.hex[:6]}"))
    await sesion.flush()
    bots = []
    for n in range(2):
        bot = HubChatbot(
            organizacion_id=org, llm_config_id=llm_id, name=f"Bot {n} {org.hex[:6]}", system_prompt="x"
        )
        sesion.add(bot)
        await sesion.flush()
        doc = await _documento(sesion, bot.id)
        for i in range(2):
            await _chunk(sesion, bot.id, doc, f"Article {i}")
        sesion.add(
            HubInteraction(
                chatbot_id=bot.id, user_id="p@uji.es", user_message="?", assistant_message="."
            )
        )
        bots.append(bot.id)
    await sesion.flush()
    return {"org": org, "bots": bots}


@pytest.fixture
async def dos(sesion):
    from server.app.modules.agents_hub.database.config_models import HubLLMConfig, HubProvider

    await sesion.merge(HubProvider(id="google", name="Google", provider_type="google_genai"))
    llm = HubLLMConfig(provider="google", model_name="gemini-2.0-flash", temperature=0.2)
    sesion.add(llm)
    await sesion.flush()
    a = await _organizacion_con_corpus(sesion, llm.id)
    b = await _organizacion_con_corpus(sesion, llm.id)
    await sesion.commit()
    return a, b


def _cliente(sesion):
    from server.app.api.deps import get_current_user, modulos_concedidos
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.hub_organizaciones_router import router

    async def _s():
        yield sesion

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: _SUPERADMIN
    app.dependency_overrides[modulos_concedidos] = lambda: ["plataforma"]
    app.dependency_overrides[get_async_session] = _s
    app.include_router(router, prefix="/api/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _cuenta(sesion, modelo, bots) -> int:
    fila = await sesion.execute(
        select(func.count(modelo.id)).where(modelo.chatbot_id.in_(bots))
    )
    return int(fila.scalar_one() or 0)


@pytest.mark.asyncio
async def test_borrar_la_organizacion_se_lleva_el_corpus_de_sus_chatbots(sesion, dos):
    from server.app.modules.agents_hub.database.operational_models import (
        HubDocument,
        HubDocumentChunk,
        HubInteraction,
    )

    a, b = dos
    async with _cliente(sesion) as c:
        r = await c.delete(f"/api/v1/hub/organizaciones/{a['org']}")
    assert r.status_code == 204, r.text

    assert await _cuenta(sesion, HubDocument, a["bots"]) == 0
    assert await _cuenta(sesion, HubDocumentChunk, a["bots"]) == 0
    # Las interacciones se quedan, igual que al borrar un chatbot.
    assert await _cuenta(sesion, HubInteraction, a["bots"]) == 2
    # Y la otra organización, intacta.
    assert await _cuenta(sesion, HubDocument, b["bots"]) == 2
    assert await _cuenta(sesion, HubDocumentChunk, b["bots"]) == 4
