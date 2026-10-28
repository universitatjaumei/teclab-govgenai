"""#298 — los routers cloud de chatbots y organizaciones dejan de tocar datos del cliente.

El corpus, los agentes, los sitios y los informes son del cliente, y por tanto edge. Las
operaciones sobre el corpus —estadísticas, regenerar fragmentos, recalcular— pasan a un router
`edge` con las mismas rutas. Lo que el cloud no puede dejar de saber —el tamaño del corpus al
pasar a `MD_LONG_CONTEXT`, si una organización tiene datos, la purga al borrar— lo pide por un
puerto inyectado, `DatosDelCliente`: aquí se sustituye por un doble para probar que lo pide a
él y no a la base.

Contra base real, porque la purga tiene que seguir en la misma transacción que el borrado (PIL.2)
y eso sólo se ve con una sesión de verdad.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from server.app.core.auth.models import UserInfo
from server.app.core.datos_del_cliente import CorpusRetirado
from server.app.main import _register_cloud, _register_edge
from server.tests.rutas import caminos

_SUPERADMIN = UserInfo(user_id=str(uuid.uuid4()), email="sa@uji.es", role="superadmin")
_CORPUS = ("corpus-stats", "regenerate-chunks", "recalculate-corpus")


class _DatosDelClienteDeMentira:
    """Contesta lo que el test le dice y apunta lo que le piden."""

    def __init__(self, sesion, *, tokens: int = 0, pendiente: dict[str, int] | None = None):
        self._sesion = sesion
        self._tokens = tokens
        self._pendiente = pendiente or {}
        self.purgados: list[uuid.UUID] = []
        self.chatbot_vivo_al_purgar: list[bool] = []
        self.fuentes_borradas: list[uuid.UUID] = []

    async def tokens_del_corpus(self, chatbot_id: uuid.UUID) -> int:
        return self._tokens

    async def lo_que_impide_borrar(self, organizacion_id: uuid.UUID) -> dict[str, int]:
        return dict(self._pendiente)

    async def purgar_corpus(self, chatbot_ids) -> CorpusRetirado:
        from server.app.modules.agents_hub.database.config_models import HubChatbot

        for chatbot_id in chatbot_ids:
            self.purgados.append(chatbot_id)
            self.chatbot_vivo_al_purgar.append(await self._sesion.get(HubChatbot, chatbot_id) is not None)
        return CorpusRetirado(documentos=len(chatbot_ids), fragmentos=0)

    async def borrar_fuentes(self, chatbot_ids) -> None:
        self.fuentes_borradas.extend(chatbot_ids)


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
async def mundo(sesion):
    from server.app.modules.agents_hub.database.config_models import (
        HubChatbot,
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
    bot = HubChatbot(organizacion_id=org, llm_config_id=llm.id, name="Bot", system_prompt="x")
    sesion.add(bot)
    await sesion.commit()
    return {"org": org, "bot": bot.id}


def _cliente(sesion, datos):
    from server.app.api.deps import get_current_user, get_datos_del_cliente, get_session, modulos_concedidos
    from server.app.routers.hub_chatbots_router import router as chatbots
    from server.app.routers.hub_organizaciones_router import router as organizaciones

    async def _s():
        yield sesion

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: _SUPERADMIN
    app.dependency_overrides[modulos_concedidos] = lambda: ["plataforma", "chatbots"]
    app.dependency_overrides[get_session] = _s
    app.dependency_overrides[get_datos_del_cliente] = lambda: datos
    app.include_router(chatbots, prefix="/api/v1")
    app.include_router(organizaciones, prefix="/api/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _registradas(registrar) -> set[str]:
    app = FastAPI()
    registrar(app)
    return set(caminos(app))


@pytest.mark.parametrize("ruta", _CORPUS)
def test_las_operaciones_del_corpus_son_edge(ruta):
    assert any(p.endswith(f"/{ruta}") for p in _registradas(_register_edge))
    assert not any(p.endswith(f"/{ruta}") for p in _registradas(_register_cloud))


@pytest.mark.asyncio
async def test_borrar_un_chatbot_purga_por_el_puerto_antes_de_borrarlo(sesion, mundo):
    datos = _DatosDelClienteDeMentira(sesion)

    async with _cliente(sesion, datos) as c:
        r = await c.delete(f"/api/v1/hub/chatbots/{mundo['bot']}")

    assert r.status_code == 204, r.text
    assert datos.purgados == [mundo["bot"]]
    assert datos.chatbot_vivo_al_purgar == [True], "la purga va antes del borrado (PIL.2)"
    assert datos.fuentes_borradas == [mundo["bot"]]


@pytest.mark.asyncio
async def test_borrar_una_organizacion_purga_sus_chatbots_por_el_puerto(sesion, mundo):
    datos = _DatosDelClienteDeMentira(sesion)

    async with _cliente(sesion, datos) as c:
        r = await c.delete(f"/api/v1/hub/organizaciones/{mundo['org']}")

    assert r.status_code == 204, r.text
    assert datos.purgados == [mundo["bot"]]
    assert datos.fuentes_borradas == [mundo["bot"]]


@pytest.mark.asyncio
async def test_una_organizacion_con_datos_no_se_borra(sesion, mundo):
    datos = _DatosDelClienteDeMentira(sesion, pendiente={"sitios": 2})

    async with _cliente(sesion, datos) as c:
        r = await c.delete(f"/api/v1/hub/organizaciones/{mundo['org']}")

    assert r.status_code == 409, r.text
    assert r.json()["detail"]["pendiente"] == {"sitios": 2}
    assert datos.purgados == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("tokens", "esperado"), [(10, 200), (10_000_000, 400)])
async def test_el_tamano_para_md_long_context_lo_dice_el_puerto(sesion, mundo, tokens, esperado):
    datos = _DatosDelClienteDeMentira(sesion, tokens=tokens)

    async with _cliente(sesion, datos) as c:
        r = await c.patch(f"/api/v1/hub/chatbots/{mundo['bot']}", json={"retrieval_mode": "MD_LONG_CONTEXT"})

    assert r.status_code == esperado, r.text
