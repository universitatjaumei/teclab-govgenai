"""Tests MOD.2 — el servicio de embeddings se resuelve por configuración, no por import.

Hasta aquí, `get_embedding_service()` devolvía el local incondicionalmente y
`GoogleEmbeddingService` era código inalcanzable. Con esto, un despliegue que no pueda sacar
el dato pone BGE-M3 local y otro pone Google: **misma imagen, distinta fila**.

El adaptador se elige por `HubProvider.provider_type`, que es el mismo mecanismo que
`model_factory` usa para el chat. Añadir un modelo o cambiar de proveedor dentro de un tipo
soportado es un UPDATE; solo un tipo nuevo exige código, y eso es irreducible.
"""
from __future__ import annotations


import pytest


async def _organizacion_y_chatbot(session, **chatbot_kwargs):
    from server.app.modules.agents_hub.database.config_models import (
        HubChatbot,
        HubLLMConfig,
        HubOrganizacion,
        HubProvider,
    )

    await session.merge(
        HubProvider(id="google", name="Google", provider_type="google_genai")
    )
    chat = HubLLMConfig(provider="google", model_name="gemini-flash", purpose="chat")
    session.add(chat)
    org = HubOrganizacion(name="UJI", partner_id="partner_dev")
    session.add(org)
    await session.flush()
    chatbot = HubChatbot(
        organizacion_id=org.id, llm_config_id=chat.id, name="Bot",
        system_prompt="x", sources=[], **chatbot_kwargs,
    )
    session.add(chatbot)
    await session.flush()
    return org, chatbot


class TestResolucion:

    @pytest.mark.asyncio
    async def test_should_use_the_local_service_when_nothing_is_configured(self, db_session):
        """Sin configuración, local: los tests y el desarrollo no pueden salir a la red
        por accidente, y una clave que falta no puede convertirse en una factura."""
        from server.app.modules.agents_hub.services.embedding_service import (
            LocalEmbeddingService,
        )
        from server.app.modules.agents_hub.services.embedding_resolver import (
            resolve_embedding_service,
        )

        _, chatbot = await _organizacion_y_chatbot(db_session)
        await db_session.commit()

        servicio = await resolve_embedding_service(db_session, chatbot.id)

        assert isinstance(servicio, LocalEmbeddingService)

    @pytest.mark.asyncio
    async def test_should_resolve_the_adapter_from_provider_type(self, db_session):
        from server.app.modules.agents_hub.database.config_models import HubLLMConfig
        from server.app.modules.agents_hub.services.embedding_service import (
            GoogleEmbeddingService,
        )
        from server.app.modules.agents_hub.services.embedding_resolver import (
            resolve_embedding_service,
        )

        _, chatbot = await _organizacion_y_chatbot(db_session)
        db_session.add(
            HubLLMConfig(
                provider="google",
                model_name="gemini-embedding-001",
                purpose="embedding",
                output_dimensionality=1024,
                is_default=True,
            )
        )
        await db_session.commit()

        servicio = await resolve_embedding_service(
            db_session, chatbot.id, client_factory=lambda **_: object()
        )

        assert isinstance(servicio, GoogleEmbeddingService)
        assert servicio.model_name == "gemini-embedding-001"
        assert servicio.dimensions == 1024

    @pytest.mark.asyncio
    async def test_vertex_usa_la_region_de_su_proveedor(self, db_session):
        """#370 — la región es del proveedor, y una misma fila no puede querer decir una región
        para el chat y otra para los embeddings: es el dato que sostiene dónde se tratan."""
        from server.app.modules.agents_hub.database.config_models import (
            HubLLMConfig,
            HubProvider,
        )
        from server.app.modules.agents_hub.services.embedding_resolver import (
            resolve_embedding_service,
        )

        _, chatbot = await _organizacion_y_chatbot(db_session)
        await db_session.merge(
            HubProvider(
                id="vertex-oeste", name="Vertex", provider_type="google_vertexai",
                location="europe-west4",
            )
        )
        db_session.add(
            HubLLMConfig(
                provider="vertex-oeste", model_name="gemini-embedding-001",
                purpose="embedding", output_dimensionality=1024, is_default=True,
            )
        )
        await db_session.commit()

        servicio = await resolve_embedding_service(
            db_session, chatbot.id, client_factory=lambda **_: object()
        )

        assert servicio._location == "europe-west4"

    @pytest.mark.asyncio
    async def test_should_fail_explicitly_for_an_unsupported_provider_type(self, db_session):
        """Sin fallback silencioso (CLAUDE.md): degradar a local sin avisar dejaría el
        corpus a medias entre dos espacios vectoriales sin que nadie se entere."""
        from server.app.modules.agents_hub.database.config_models import (
            HubLLMConfig,
            HubProvider,
        )
        from server.app.modules.agents_hub.services.embedding_resolver import (
            EmbeddingProviderNotSupported,
            resolve_embedding_service,
        )

        _, chatbot = await _organizacion_y_chatbot(db_session)
        await db_session.merge(
            HubProvider(id="exotico", name="Exotico", provider_type="protocolo_raro")
        )
        db_session.add(
            HubLLMConfig(
                provider="exotico", model_name="m", purpose="embedding", is_default=True
            )
        )
        await db_session.commit()

        with pytest.raises(EmbeddingProviderNotSupported) as error:
            await resolve_embedding_service(db_session, chatbot.id)

        assert "protocolo_raro" in str(error.value)

    @pytest.mark.asyncio
    async def test_should_ignore_configs_of_another_purpose(self, db_session):
        """El modelo de chat no puede acabar generando embeddings por parecerse la tabla."""
        from server.app.modules.agents_hub.services.embedding_service import (
            LocalEmbeddingService,
        )
        from server.app.modules.agents_hub.services.embedding_resolver import (
            resolve_embedding_service,
        )

        _, chatbot = await _organizacion_y_chatbot(db_session)
        await db_session.commit()

        servicio = await resolve_embedding_service(db_session, chatbot.id)

        assert isinstance(servicio, LocalEmbeddingService)


class TestRerankerDesactivadoPorDefecto:
    """Decisión del usuario (2026-08-01): el mecanismo se construye, el interruptor no."""

    @pytest.mark.asyncio
    async def test_should_default_reranker_to_disabled(self, db_session):
        from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
            get_effective_public_graph_config,
        )

        _, chatbot = await _organizacion_y_chatbot(db_session)
        await db_session.commit()

        cfg = await get_effective_public_graph_config(chatbot.id, db_session)

        assert cfg.reranker_enabled is False

    def test_should_default_reranker_to_disabled_on_the_platform(self):
        from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
            _PLATFORM_DEFAULTS,
        )

        assert _PLATFORM_DEFAULTS.reranker_enabled is False
