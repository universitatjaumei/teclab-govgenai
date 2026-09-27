"""Seeds de ejemplo para el módulo agents_hub."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.connection import (
    create_async_engine,
    create_session_factory,
)
from server.app.modules.agents_hub.database.config_models import (
    HubChatbot,
    HubOrganizacion,
    HubLLMConfig,
    HubProvider,
)

# Issue #18 — lo llama `main.py` en el arranque: registro, no consola.
logger = logging.getLogger(__name__)

_DEV_LLM_CONFIG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_DEV_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
_DEV_CHATBOT_ID = uuid.UUID("00000000-0000-0000-0000-000000000100")


async def seed_hub_defaults() -> None:
    """Crea los datos de ejemplo mínimos para el Hub (idempotente)."""
    engine = create_async_engine()
    factory = create_session_factory(engine)

    async with factory() as session:
        await _seed_providers(session)
        await _seed_llm_config(session)
        await _seed_organizacion(session)
        await _seed_chatbot(session)
        await session.commit()

    await engine.dispose()
    logger.info("Valores por defecto del hub verificados o creados")


_DEFAULT_PROVIDERS = [
    # PIL.1: el proveedor del despliegue. Autentica por ADC, sin clave de API que repartir.
    HubProvider(id="vertex", name="Google Vertex AI", provider_type="google_vertexai"),
    HubProvider(id="google", name="Google AI (Gemini)", provider_type="google_genai"),
    HubProvider(id="openrouter", name="OpenRouter", provider_type="openai_compatible"),
    HubProvider(id="ollama", name="Ollama (Local)", provider_type="openai_compatible"),
]


async def _seed_providers(session: AsyncSession) -> None:
    for provider in _DEFAULT_PROVIDERS:
        existing = await session.get(HubProvider, provider.id)
        if not existing:
            session.add(provider)
    logger.info("Proveedores del hub verificados o creados")


async def _seed_llm_config(session: AsyncSession) -> None:
    existing = await session.get(HubLLMConfig, _DEV_LLM_CONFIG_ID)
    if existing:
        return
    session.add(
        HubLLMConfig(
            id=_DEV_LLM_CONFIG_ID,
            provider="google",
            model_name="gemini-2.0-flash",
            temperature=0.7,
            max_tokens=2048,
            tier=1,
            label="Gemini Flash 2.0",
            is_default=True,
            api_key_secret_name="GOOGLE_API_KEY",
        )
    )
    logger.info("Configuracion de modelo de desarrollo creada")


async def _seed_organizacion(session: AsyncSession) -> None:
    existing = await session.get(HubOrganizacion, _DEV_ORG_ID)
    if existing:
        return
    session.add(
        HubOrganizacion(
            id=_DEV_ORG_ID,
            name="Organización Demo",
            partner_id="admin_dev",
            is_active=True,
        )
    )
    logger.info("Organizacion de desarrollo creada")


async def _seed_chatbot(session: AsyncSession) -> None:
    result = await session.execute(
        select(HubChatbot).where(HubChatbot.id == _DEV_CHATBOT_ID)
    )
    if result.scalar_one_or_none():
        return
    session.add(
        HubChatbot(
            id=_DEV_CHATBOT_ID,
            organizacion_id=_DEV_ORG_ID,
            llm_config_id=_DEV_LLM_CONFIG_ID,
            name="Chatbot Demo",
            system_prompt="Eres un asistente útil que responde preguntas basándose en los documentos proporcionados.",
            is_active=True,
        )
    )
    logger.info("Chatbot de desarrollo creado")
