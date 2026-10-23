"""Fixtures compartidas para tests E2E de agents_hub.

Requieren PostgreSQL con pgvector corriendo en localhost:5432. Corren contra la **BD
desechable por test** de la fixture `db_url` (conftest raíz): la versión anterior creaba
las tablas del hub sobre `DATABASE_URL` —la BD del desarrollador— y `setup_chatbot` le
dejó 12 organizaciones y chatbots residuales (TST.2). Lo vigila
`e2e/test_db_isolation.py`.

Nota de diseño: todos los fixtures de BD tienen scope="function" para
evitar conflictos de event loop entre pytest-asyncio y httpx.AsyncClient.
"""
# ── Orden de importación obligatorio, no reordenar ─────────────────────────────
# `langchain_text_splitters` arrastra `sentence_transformers` → torch. En Windows, cargar torch
# DESPUÉS de haber abierto una conexión asyncpg aborta el proceso con «Windows fatal exception:
# access violation»; al revés funciona. Diagnosticado el 2026-07-29. Este fichero crea un motor,
# así que le toca (APER.16).
import langchain_text_splitters  # noqa: F401  ← debe ir primero

import os
import uuid

import pytest

# SEC.2: el chat y la exportación exigen que el principal gestione la organización del
# chatbot. Estos E2E prueban otra cosa, así que la organización del doble y la del token
# son la misma; la tenencia tiene su gate propio en `tests/api/test_tenant_isolation.py`.
# El mismo valor está en `test_chat_flow.py`, que crea principales adicionales.
ORG_PRUEBA = uuid.UUID("00000000-0000-0000-0000-00000000dead")

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
    "GOOGLE_API_KEY": "test-key",
    "GEMINI_API_KEY": "test-key",
}


@pytest.fixture(autouse=True)
def _set_jwt_env():
    os.environ.update(_JWT_ENV)


@pytest.fixture
async def db_engine(db_url):
    """Motor por test sobre la BD desechable (las tablas hub_ ya vienen creadas)."""
    from server.app.modules.agents_hub.database.connection import create_async_engine

    engine = create_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Sesión de BD por test."""
    from server.app.modules.agents_hub.database.connection import create_session_factory

    factory = create_session_factory(db_engine)
    async with factory() as session:
        yield session


@pytest.fixture
def auth_headers():
    """Headers JWT para usuario final (e2e-user-1)."""
    from server.app.core.auth import UserInfo, create_token

    token = create_token(
        UserInfo(
            user_id="e2e-user-1",
            email="e2e@test.com",
            role="user",
            organizacion_ids=(str(ORG_PRUEBA),),
        )
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    """Headers JWT para administrador."""
    from server.app.core.auth import UserInfo, create_token

    token = create_token(
        UserInfo(
            user_id="admin-e2e-1",
            email="admin-e2e@test.com",
            role="admin",
            organizacion_ids=(str(ORG_PRUEBA),),
        )
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def setup_chatbot(db_session):
    """Crea un chatbot de prueba con cliente, config LLM y chunk de conocimiento."""
    from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion, HubLLMConfig, HubProvider
    from server.app.modules.agents_hub.database.operational_models import HubDocumentChunk
    from server.app.modules.agents_hub.ingestion.hasher import hash_content

    await db_session.merge(HubProvider(id="google", name="Google", provider_type="google_genai"))
    await db_session.commit()

    llm_config = HubLLMConfig(
        provider="google",
        model_name="gemini-2.0-flash",
        temperature=0.7,
    )
    db_session.add(llm_config)
    await db_session.flush()

    client = HubOrganizacion(
        id=ORG_PRUEBA, name="E2E Test Client", partner_id="partner-e2e-1"
    )
    db_session.add(client)
    await db_session.flush()

    chatbot = HubChatbot(
        organizacion_id=client.id,
        llm_config_id=llm_config.id,
        name=f"E2E Bot {uuid.uuid4()}",
        system_prompt="Eres un asistente de prueba.",
        sources=["https://example.com"],
    )
    db_session.add(chatbot)
    await db_session.flush()

    content = "Python es un lenguaje de programación versátil y fácil de aprender."
    chunk = HubDocumentChunk(
        chatbot_id=chatbot.id,
        content=content,
        source_url="https://example.com/python",
        content_hash=hash_content(content),
        embedding=[0.1] * 1024,
        language="es",
        embedding_model="BAAI/bge-m3",
        embedding_dim=1024,
    )
    db_session.add(chunk)
    await db_session.commit()

    return chatbot


@pytest.fixture
def test_app(db_engine):
    """App FastAPI de test con los routers hub y la sesión de test inyectada."""
    from fastapi import FastAPI
    from server.app.api.v1.hub_chat import router as chat_router
    from server.app.api.v1.hub_tasks import router as tasks_router
    from server.app.modules.agents_hub.database.connection import (
        create_session_factory,

    )
    from server.app.api.deps import get_session

    async def _override_session():
        factory = create_session_factory(db_engine)
        async with factory() as session:
            yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = _override_session
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(tasks_router, prefix="/api/v1")
    return app
