"""#372 — el panel puede leer y escribir la región de un proveedor y el proveedor de un modelo.

#370 llevó el chat a Vertex con la región en `hub_providers.location`, pero la API de proveedores
no la conocía: solo se fijaba por la semilla o por SQL. Y el `PATCH` de un modelo descartaba
`provider` sin avisar, así que cambiar un modelo de AI Studio a Vertex desde el panel parecía
guardarse y no se guardaba: la reconfiguración de producción del 05-11 tuvo que ir por SQL.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from server.app.core.auth.models import UserInfo


@asynccontextmanager
async def _cliente(session):
    from fastapi import FastAPI

    from server.app.api.deps import get_current_user, get_session, modulos_concedidos
    from server.app.routers.hub_llm_configs_router import router

    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: UserInfo(
        user_id="root", email="root@example.org", role="superadmin"
    )
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[modulos_concedidos] = lambda: ["plataforma"]
    app.include_router(router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _proveedores(session) -> None:
    from server.app.modules.agents_hub.database.config_models import HubProvider

    await session.merge(HubProvider(id="google", name="Google", provider_type="google_genai"))
    await session.merge(
        HubProvider(id="vertex", name="Vertex", provider_type="google_vertexai")
    )
    await session.flush()


class TestLaRegionDelProveedor:

    @pytest.mark.asyncio
    async def test_se_crea_con_region_y_se_lee(self, db_session) -> None:
        async with _cliente(db_session) as c:
            r = await c.post("/api/v1/hub/llm-configs/providers", json={
                "id": f"vertex-{uuid.uuid4().hex[:6]}", "name": "Vertex oeste",
                "provider_type": "google_vertexai", "location": "europe-west4",
            })
            assert r.status_code == 201, r.text
            assert r.json()["location"] == "europe-west4"

            lista = await c.get("/api/v1/hub/llm-configs/providers")
        assert {p["id"]: p["location"] for p in lista.json()}[r.json()["id"]] == "europe-west4"

    @pytest.mark.asyncio
    async def test_se_cambia_y_se_vacia(self, db_session) -> None:
        """Vaciarla es volver a la del entorno, y tiene que poder hacerse desde el panel."""
        await _proveedores(db_session)
        await db_session.commit()

        async with _cliente(db_session) as c:
            r = await c.patch(
                "/api/v1/hub/llm-configs/providers/vertex", json={"location": "global"}
            )
            assert r.status_code == 200, r.text
            assert r.json()["location"] == "global"

            r = await c.patch(
                "/api/v1/hub/llm-configs/providers/vertex", json={"location": None}
            )
        assert r.json()["location"] is None


class TestElProveedorDelModelo:

    @pytest.mark.asyncio
    async def test_cambiar_el_proveedor_se_guarda(self, db_session) -> None:
        from server.app.modules.agents_hub.database.config_models import HubLLMConfig

        await _proveedores(db_session)
        config = HubLLMConfig(provider="google", model_name="gemini-2.5-pro", tier=2)
        db_session.add(config)
        await db_session.commit()
        config_id = config.id

        async with _cliente(db_session) as c:
            r = await c.patch(f"/api/v1/hub/llm-configs/{config_id}", json={"provider": "vertex"})

        assert r.status_code == 200, r.text
        assert r.json()["provider"] == "vertex"
        from sqlalchemy import select

        db_session.expire_all()
        guardado = await db_session.scalar(
            select(HubLLMConfig.provider).where(HubLLMConfig.id == config_id)
        )
        assert guardado == "vertex"

    @pytest.mark.asyncio
    async def test_un_proveedor_que_no_existe_es_un_404_y_no_un_500(self, db_session) -> None:
        from server.app.modules.agents_hub.database.config_models import HubLLMConfig

        await _proveedores(db_session)
        config = HubLLMConfig(provider="google", model_name="gemini-2.5-pro", tier=2)
        db_session.add(config)
        await db_session.commit()

        async with _cliente(db_session) as c:
            r = await c.patch(
                f"/api/v1/hub/llm-configs/{config.id}", json={"provider": "no-existe"}
            )

        assert r.status_code == 404, r.text


class TestLoQueEncontroLaRevisionDeLaPR373:
    """El servidor dice qué tipos de proveedor hay, qué sirve a cada propósito y qué es una
    región; el panel solo lo pinta. Sin esto, el desplegable era la única lista de tipos, y
    cada tipo que le faltaba —Vertex, el reranker, `local`— se reescribía al guardar."""

    @pytest.mark.asyncio
    async def test_un_tipo_de_proveedor_desconocido_es_un_422(self, db_session) -> None:
        async with _cliente(db_session) as c:
            r = await c.post("/api/v1/hub/llm-configs/providers", json={
                "id": f"raro-{uuid.uuid4().hex[:6]}", "name": "Raro", "provider_type": "protocolo_raro",
            })
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_la_region_se_limpia_en_el_servidor(self, db_session) -> None:
        """Un cliente de la API que no pase por el panel no puede dejar «  global » ni ''."""
        await _proveedores(db_session)
        await db_session.commit()

        async with _cliente(db_session) as c:
            r = await c.patch("/api/v1/hub/llm-configs/providers/vertex", json={"location": "  global "})
            assert r.json()["location"] == "global"
            r = await c.patch("/api/v1/hub/llm-configs/providers/vertex", json={"location": "  "})
            assert r.json()["location"] is None
            r = await c.patch("/api/v1/hub/llm-configs/providers/vertex", json={"location": "x" * 51})
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_mover_un_modelo_de_chat_al_reranker_es_un_422(self, db_session) -> None:
        """Antes el campo se descartaba y esto era inalcanzable; con #372 se guardaba y todas las
        llamadas de ese nivel fallaban con «Provider type desconocido»."""
        from server.app.modules.agents_hub.database.config_models import HubLLMConfig, HubProvider

        await _proveedores(db_session)
        await db_session.merge(
            HubProvider(id="vertex-ranking", name="Ranking", provider_type="discovery_engine")
        )
        config = HubLLMConfig(provider="google", model_name="gemini-2.5-pro", tier=2, purpose="chat")
        db_session.add(config)
        await db_session.commit()
        config_id = config.id

        async with _cliente(db_session) as c:
            r = await c.patch(f"/api/v1/hub/llm-configs/{config_id}", json={"provider": "vertex-ranking"})

        assert r.status_code == 422, r.text
        assert "chat" in r.text

    @pytest.mark.asyncio
    async def test_crear_un_modelo_con_un_proveedor_que_no_sirve_a_su_proposito_es_un_422(self, db_session) -> None:
        from server.app.modules.agents_hub.database.config_models import HubProvider

        await _proveedores(db_session)
        await db_session.merge(
            HubProvider(id="vertex-ranking", name="Ranking", provider_type="discovery_engine")
        )
        await db_session.commit()

        async with _cliente(db_session) as c:
            r = await c.post("/api/v1/hub/llm-configs", json={
                "provider": "vertex-ranking", "model_name": "semantic-ranker", "purpose": "embedding",
            })
        assert r.status_code == 422, r.text
