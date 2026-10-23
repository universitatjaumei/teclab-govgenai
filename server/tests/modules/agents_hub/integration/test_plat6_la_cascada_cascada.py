"""PLAT.6 — que la cascada de verdad cascadee, y que guardar no la congele.

Lo destapó la verificación en navegador siguiendo la secuencia completa, no un test unitario:
la pantalla manda **solo lo propio** —eso ya lo garantizaba su test—, pero el servidor
materializaba los valores por omisión del contrato al guardar (`model_dump()` sin más). El
efecto es exactamente el que el prompt prohíbe: el primer guardado de una organización se lleva
los dieciséis colores de la plataforma como valores **propios**, y a partir de ahí un cambio en
la plataforma ya no le llega. Nadie se enteraría hasta que alguien comparase a mano.

Y hay un segundo camino al mismo sitio: `get_theme_for_chatbot` servía el tema del asistente
**crudo**, sin resolver la cascada. Hoy no se nota porque todo se almacena completo; en cuanto
el almacenamiento es disperso, el widget se queda sin los colores que su organización sí tiene
puestos. Así que las dos mitades van juntas: almacenar solo lo enviado exige resolver la cascada
al servir.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from server.app.api.deps import get_current_user, get_current_user_optional
from server.app.core.auth.models import UserInfo
from server.app.api.deps import get_session


def _cliente(session, principal) -> AsyncClient:
    from server.app.routers.hub_themes_router import router

    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_current_user_optional] = lambda: principal
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def superadmin():
    return UserInfo(user_id="quien-manda", email="root@uji.es", role="superadmin")


async def _organizacion(session):
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    fila = HubOrganizacion(id=uuid.uuid4(), name="UJI", partner_id="p1")
    session.add(fila)
    await session.commit()
    return fila


class TestGuardarNoCongelaLoHeredado:

    @pytest.mark.asyncio
    async def test_should_store_only_what_the_caller_sent(self, db_session, superadmin):
        org = await _organizacion(db_session)

        async with _cliente(db_session, superadmin) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/themes",
                json={
                    "name": "UJI",
                    "organizacion_id": str(org.id),
                    "config": {"name": "uji", "colors": {"primary": "#c026d3"}},
                },
            )

        assert respuesta.status_code == 201, respuesta.text
        colores = respuesta.json()["config"]["colors"]
        # Un solo color propio. Con los dieciséis, el siguiente cambio de la plataforma
        # dejaría de llegarle a esta organización.
        assert list(colores) == ["primary"], colores

    @pytest.mark.asyncio
    async def test_should_let_a_later_platform_change_reach_the_child(
        self, db_session, superadmin
    ):
        """La propiedad que importa, y la que el almacenamiento completo rompía en silencio."""
        org = await _organizacion(db_session)

        async with _cliente(db_session, superadmin) as cliente:
            await cliente.post(
                "/api/v1/hub/themes",
                json={
                    "name": "UJI",
                    "organizacion_id": str(org.id),
                    "config": {"name": "uji", "colors": {"primary": "#c026d3"}},
                },
            )
            await cliente.post(
                "/api/v1/hub/themes",
                json={
                    "name": "Plataforma",
                    "config": {"name": "base", "colors": {"background": "#101010"}},
                },
            )

        propio = UserInfo(
            user_id="de-la-uji",
            email="a@uji.es",
            role="admin",
            organizacion_ids=(str(org.id),),
        )
        async with _cliente(db_session, propio) as c2:
            resuelto = (await c2.get("/api/v1/hub/themes/resolved")).json()["config"]

        assert resuelto["colors"]["primary"] == "#c026d3"
        # El fondo nuevo de la plataforma le llega porque no lo tiene congelado.
        assert resuelto["colors"]["background"] == "#101010"

    @pytest.mark.asyncio
    async def test_should_not_refill_the_contract_on_update(self, db_session, superadmin):
        org = await _organizacion(db_session)

        async with _cliente(db_session, superadmin) as cliente:
            creado = (
                await cliente.post(
                    "/api/v1/hub/themes",
                    json={
                        "name": "UJI",
                        "organizacion_id": str(org.id),
                        "config": {"name": "uji", "colors": {"primary": "#c026d3"}},
                    },
                )
            ).json()
            actualizado = await cliente.put(
                f"/api/v1/hub/themes/{creado['id']}",
                json={"config": {"name": "uji", "colors": {"primary": "#ff0000"}}},
            )

        assert actualizado.status_code == 200, actualizado.text
        assert list(actualizado.json()["config"]["colors"]) == ["primary"]


class TestElWidgetResuelveLaCascada:

    @pytest.mark.asyncio
    async def test_should_serve_the_chatbot_widget_the_inherited_colours(
        self, db_session, superadmin
    ):
        """El segundo camino al mismo defecto: el widget servía el tema del asistente crudo."""
        from server.app.modules.agents_hub.database.config_models import (
            HubChatbot,
            HubLLMConfig,
            HubProvider,
        )

        org = await _organizacion(db_session)
        # `llm_config_id` es NOT NULL y `provider` es FK contra `hub_providers`: un asistente
        # sin modelo, y un modelo sin proveedor dado de alta, no existen en este esquema.
        db_session.add(HubProvider(id="google", name="Google", provider_type="google"))
        await db_session.commit()
        llm = HubLLMConfig(provider="google", model_name="gemini-flash")
        db_session.add(llm)
        await db_session.commit()
        bot = HubChatbot(
            id=uuid.uuid4(),
            name="Asistente",
            organizacion_id=org.id,
            llm_config_id=llm.id,
            system_prompt="Eres un asistente.",
            access_mode="public_anon",
        )
        db_session.add(bot)
        await db_session.commit()

        async with _cliente(db_session, superadmin) as cliente:
            await cliente.post(
                "/api/v1/hub/themes",
                json={
                    "name": "Base",
                    "config": {"name": "base", "colors": {"background": "#101010"}},
                },
            )
            await cliente.post(
                "/api/v1/hub/themes",
                json={
                    "name": "UJI",
                    "organizacion_id": str(org.id),
                    "config": {"name": "uji", "colors": {"primary": "#c026d3"}},
                },
            )
            propio = (
                await cliente.post(
                    "/api/v1/hub/themes",
                    json={
                        "name": "Solo este bot",
                        "organizacion_id": str(org.id),
                        "chatbot_id": str(bot.id),
                        "config": {"name": "bot", "colors": {"text": "#ffffff"}},
                    },
                )
            ).json()
            await cliente.post(f"/api/v1/hub/themes/{propio['id']}/apply/{bot.id}")
            servido = (
                await cliente.get(f"/api/v1/hub/themes/for-chatbot/{bot.id}")
            ).json()["config"]

        # Lo suyo, lo de su organización y lo de la plataforma: los tres niveles.
        assert servido["colors"]["text"] == "#ffffff"
        assert servido["colors"]["primary"] == "#c026d3"
        assert servido["colors"]["background"] == "#101010"
