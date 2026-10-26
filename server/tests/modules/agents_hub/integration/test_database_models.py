"""Prompt 2.4 — Tests de modelos ORM (TDD - RED → GREEN).

La fixture base `db_session` vive en el conftest.py de este directorio y usa una BD
desechable por test: antes este fichero creaba y DESTRUÍA las tablas de la BD de
desarrollo.
"""
import uuid
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select


@pytest.fixture
async def seeded_session(db_session):
    """Sesión con los proveedores de LLM que estos tests dan por sembrados."""
    from server.app.modules.agents_hub.database.config_models import HubProvider

    await db_session.merge(
        HubProvider(id="google", name="Google", provider_type="google_genai")
    )
    await db_session.merge(
        HubProvider(id="openai", name="OpenAI", provider_type="openai_compatible")
    )
    await db_session.commit()
    return db_session


class TestHubLLMConfigModel:

    @pytest.mark.asyncio
    async def test_llm_config_persistence(self, seeded_session) -> None:
        """Prompt 2.8 — Validar que se pueden guardar y recuperar parámetros LLM."""
        from server.app.modules.agents_hub.database.config_models import HubLLMConfig

        config = HubLLMConfig(
            provider="google",
            model_name="gemini-2.5-flash",
            temperature=0.3,
            max_tokens=4096,
        )
        seeded_session.add(config)
        await seeded_session.commit()

        result = await seeded_session.execute(
            select(HubLLMConfig).where(HubLLMConfig.model_name == "gemini-2.5-flash")
        )
        saved = result.scalar_one()
        assert saved.temperature == pytest.approx(0.3)
        assert saved.max_tokens == 4096
        assert saved.provider == "google"


class TestHubChatbotModel:

    @pytest.mark.asyncio
    async def test_create_chatbot_requires_llm_config(self, seeded_session) -> None:
        """Prompt 2.9 — Validar que no se puede crear un chatbot sin llm_config_id."""
        from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion

        client = HubOrganizacion(name="Test Inst", partner_id="partner_dev")
        seeded_session.add(client)
        await seeded_session.flush()

        chatbot = HubChatbot(
            organizacion_id=client.id,
            llm_config_id=uuid.uuid4(),  # FK inválido — debe fallar
            name="Bot sin modelo",
            system_prompt="Test",
            sources=[],
        )
        seeded_session.add(chatbot)
        with pytest.raises(IntegrityError, match="hub_chatbots"):
            await seeded_session.flush()

    @pytest.mark.asyncio
    async def test_create_chatbot_with_valid_model(self, seeded_session) -> None:
        """Chatbot con llm_config válido se persiste correctamente."""
        from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion, HubLLMConfig

        llm = HubLLMConfig(provider="openai", model_name="gpt-4o", temperature=0.5)
        seeded_session.add(llm)
        await seeded_session.flush()

        client = HubOrganizacion(name="Univ. Test", partner_id="partner_dev")
        seeded_session.add(client)
        await seeded_session.flush()

        chatbot = HubChatbot(
            organizacion_id=client.id,
            llm_config_id=llm.id,
            name="Bot Válido",
            system_prompt="Eres útil.",
            sources=[],
        )
        seeded_session.add(chatbot)
        await seeded_session.commit()

        result = await seeded_session.execute(
            select(HubChatbot).where(HubChatbot.name == "Bot Válido")
        )
        saved = result.scalar_one()
        assert saved.llm_config_id == llm.id


class TestHubPromptTemplateModel:

    @pytest.mark.asyncio
    async def test_chatbot_retrieves_correct_prompt_by_language(self, seeded_session) -> None:
        """Prompt 2.8 — Al pedir 'system_base' en catalán no devuelve el de castellano."""
        from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion, HubLLMConfig, HubPromptTemplate

        llm = HubLLMConfig(provider="google", model_name="gemini-flash")
        seeded_session.add(llm)
        client = HubOrganizacion(name="Univ. CA", partner_id="partner_dev")
        seeded_session.add(client)
        await seeded_session.flush()

        chatbot = HubChatbot(
            organizacion_id=client.id,
            llm_config_id=llm.id,
            name="Bot CA",
            system_prompt="Base",
            sources=[],
        )
        seeded_session.add(chatbot)
        await seeded_session.flush()

        seeded_session.add_all([
            HubPromptTemplate(
                chatbot_id=chatbot.id,
                slug="system_base",
                language="es",
                template_text="Eres un asistente.",
            ),
            HubPromptTemplate(
                chatbot_id=chatbot.id,
                slug="system_base",
                language="ca",
                template_text="Ets un assistent.",
            ),
        ])
        await seeded_session.commit()

        result = await seeded_session.execute(
            select(HubPromptTemplate).where(
                HubPromptTemplate.chatbot_id == chatbot.id,
                HubPromptTemplate.slug == "system_base",
                HubPromptTemplate.language == "ca",
            )
        )
        ca_prompt = result.scalar_one()
        assert "assistent" in ca_prompt.template_text
        assert "asistente" not in ca_prompt.template_text


class TestHubDocumentChunkModel:

    @pytest.mark.asyncio
    async def test_create_chunk_with_vector(self, seeded_session) -> None:
        from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion, HubLLMConfig
        from server.app.modules.agents_hub.database.operational_models import HubDocumentChunk

        llm = HubLLMConfig(provider="google", model_name="gemini-flash")
        seeded_session.add(llm)
        client = HubOrganizacion(name="Test", partner_id="partner_dev")
        seeded_session.add(client)
        await seeded_session.flush()

        chatbot = HubChatbot(
            organizacion_id=client.id,
            llm_config_id=llm.id,
            name="Chunk Bot",
            system_prompt="Test",
            sources=[],
        )
        seeded_session.add(chatbot)
        await seeded_session.flush()

        chunk = HubDocumentChunk(
            chatbot_id=chatbot.id,
            content="Python es genial",
            source_url="https://example.com",
            content_hash="abc123",
            embedding=[0.1] * 1024,
            language="es",
            embedding_model="BAAI/bge-m3",
            embedding_dim=1024,
        )
        seeded_session.add(chunk)
        await seeded_session.commit()

        result = await seeded_session.execute(
            select(HubDocumentChunk).where(HubDocumentChunk.content_hash == "abc123")
        )
        saved = result.scalar_one()
        assert len(saved.embedding) == 1024
