"""#340 — las valoraciones con estrellas del widget público se registran.

`POST /hub/feedback/{id}` exigía sesión, y quien usa el widget de un chatbot `public_anon` es
anónimo: conversa con la credencial de sitio (`X-Widget-Key`, SEC.8.5). La valoración recibía un
401, la estrella se desmarcaba (#278) y el widget no decía nada: no se había guardado ninguna.

Ahora la credencial de sitio vale para valorar con las mismas condiciones que para conversar: es
del chatbot de la interacción, el chatbot es `public_anon` y la interacción es del público de ese
widget. Con BD porque lo que se comprueba es que la valoración queda guardada.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

async def _chatbot(session, access_mode: str):
    """Como `_organizacion_y_chatbot` de test_embedding_resolution, pero con nombre único: el
    nombre del chatbot es UNIQUE y aquí se crean dos en la misma base."""
    from server.app.modules.agents_hub.database.config_models import (
        HubChatbot,
        HubLLMConfig,
        HubOrganizacion,
        HubProvider,
    )

    await session.merge(HubProvider(id="google", name="Google", provider_type="google_genai"))
    llm = HubLLMConfig(provider="google", model_name="gemini-flash", purpose="chat")
    org = HubOrganizacion(name=f"UJI {uuid.uuid4().hex[:6]}", partner_id="partner_dev")
    session.add_all([llm, org])
    await session.flush()
    chatbot = HubChatbot(
        organizacion_id=org.id, llm_config_id=llm.id, name=f"Bot {uuid.uuid4().hex[:8]}",
        system_prompt="x", sources=[], access_mode=access_mode,
    )
    session.add(chatbot)
    await session.flush()
    return chatbot


async def _escenario(session, *, access_mode="public_anon", autor=None):
    from server.app.core.auth.widget_key import crear_widget_key
    from server.app.modules.agents_hub.database.operational_models import HubInteraction

    chatbot = await _chatbot(session, access_mode)
    interaccion = HubInteraction(
        id=uuid.uuid4(),
        chatbot_id=chatbot.id,
        user_id=autor or f"widget:{chatbot.id}",
        user_message="q",
        assistant_message="a",
    )
    session.add(interaccion)
    clave, _ = await crear_widget_key(session, chatbot_id=chatbot.id, name="Portal")
    await session.flush()
    return chatbot, interaccion, clave


@asynccontextmanager
async def _cliente(session):
    from server.app.api.deps import get_session
    from server.app.api.v1.hub_feedback import router

    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _valorar(session, interaccion_id, clave=None):
    cabeceras = {"X-Widget-Key": clave} if clave else {}
    async with _cliente(session) as c:
        return await c.post(f"/api/v1/hub/feedback/{interaccion_id}", json={"score": 4}, headers=cabeceras)


@pytest.mark.asyncio
async def test_el_publico_del_widget_valora_con_la_credencial_de_sitio(db_session) -> None:
    _, interaccion, clave = await _escenario(db_session)

    respuesta = await _valorar(db_session, interaccion.id, clave)

    assert respuesta.status_code == 204
    await db_session.refresh(interaccion)
    assert interaccion.feedback_score == 4


@pytest.mark.asyncio
async def test_sin_sesion_ni_credencial_es_un_401_aunque_la_interaccion_no_exista(db_session) -> None:
    """Antes de buscar la interacción: si no, el 404 diría cuáles existen."""
    respuesta = await _valorar(db_session, uuid.uuid4())

    assert respuesta.status_code == 401


@pytest.mark.asyncio
async def test_la_credencial_de_otro_chatbot_no_vale(db_session) -> None:
    _, interaccion, _ = await _escenario(db_session)
    _, _, clave_ajena = await _escenario(db_session)

    respuesta = await _valorar(db_session, interaccion.id, clave_ajena)

    assert respuesta.status_code == 403


@pytest.mark.asyncio
async def test_un_chatbot_que_no_es_publico_no_se_valora_con_la_credencial(db_session) -> None:
    _, interaccion, clave = await _escenario(db_session, access_mode="authenticated")

    respuesta = await _valorar(db_session, interaccion.id, clave)

    assert respuesta.status_code == 403


@pytest.mark.asyncio
async def test_la_credencial_no_valora_la_conversacion_de_una_persona(db_session) -> None:
    """El público del widget valora lo suyo, no lo que alguien preguntó con sesión."""
    _, interaccion, clave = await _escenario(db_session, autor="admin-1")

    respuesta = await _valorar(db_session, interaccion.id, clave)

    assert respuesta.status_code == 403
