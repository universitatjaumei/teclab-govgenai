"""Tests del router multi-materia — TDD RED."""
import uuid
import pytest
from unittest.mock import AsyncMock
from server.tests.dobles import modelo_de_chat


class TestRouteToSubagent:

    @pytest.fixture
    def router_chatbot(self):
        from dataclasses import dataclass
        @dataclass
        class FakeCB:
            id: uuid.UUID
            name: str
            system_prompt: str
            kind: str = "atomic"
            parent_chatbot_id: uuid.UUID | None = None
            retrieval_mode: str = "MD_AGENT_SELECTOR"
        router_id = uuid.uuid4()
        return [
            FakeCB(id=router_id, name="UJI", system_prompt="Asistente UJI", kind="router"),
            FakeCB(id=uuid.uuid4(), name="Normativa académica",
                   system_prompt="Reglamentos académicos, planes de estudio, permanencia",
                   parent_chatbot_id=router_id),
            FakeCB(id=uuid.uuid4(), name="RRHH",
                   system_prompt="Personal docente e investigador, nóminas, permisos",
                   parent_chatbot_id=router_id),
            FakeCB(id=uuid.uuid4(), name="Económico",
                   system_prompt="Presupuestos, justificación de gastos, contratos",
                   parent_chatbot_id=router_id),
        ]

    @pytest.mark.asyncio
    async def test_router_classifies_to_correct_child(self, router_chatbot):
        from server.app.modules.agents_hub.agent.router_node import build_route_to_subagent_node

        embedding_service = AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None)
        chatbot_provider = AsyncMock()
        chatbot_provider.get_children = AsyncMock(return_value=router_chatbot[1:])

        node = build_route_to_subagent_node(
            embedding_service=embedding_service,
            chatbot_provider=chatbot_provider,
        )
        state = {
            "messages": [type("M", (), {"content": "¿Cuántos días de permiso me corresponden?"})()],
            "chatbot_id": str(router_chatbot[0].id),
        }
        result = await node(state)
        assert result["selected_child_id"] in {str(c.id) for c in router_chatbot[1:]}
        assert result["routing_confidence"] >= 0.0

    @pytest.mark.asyncio
    async def test_router_with_single_child_passes_through(self, router_chatbot):
        from server.app.modules.agents_hub.agent.router_node import build_route_to_subagent_node
        embedding_service = AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None)
        only_one = [router_chatbot[1]]
        chatbot_provider = AsyncMock(get_children=AsyncMock(return_value=only_one))
        node = build_route_to_subagent_node(embedding_service, chatbot_provider)
        state = {"messages": [type("M", (), {"content": "x"})()],
                 "chatbot_id": str(router_chatbot[0].id)}
        result = await node(state)
        assert result["selected_child_id"] == str(only_one[0].id)
        assert result["routing_confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_router_with_no_children_raises(self, router_chatbot):
        from server.app.modules.agents_hub.agent.router_node import build_route_to_subagent_node
        embedding_service = AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None)
        chatbot_provider = AsyncMock(get_children=AsyncMock(return_value=[]))
        node = build_route_to_subagent_node(embedding_service, chatbot_provider)
        state = {"messages": [type("M", (), {"content": "x"})()],
                 "chatbot_id": str(router_chatbot[0].id)}
        with pytest.raises(ValueError, match="sin hijos"):
            await node(state)

    @pytest.mark.asyncio
    async def test_low_confidence_falls_back_to_llm_classifier(self, router_chatbot):
        """Si la confianza por embeddings < umbral, usa LLM como segundo intento."""
        from server.app.modules.agents_hub.agent.router_node import build_route_to_subagent_node
        embedding_service = AsyncMock(embed=AsyncMock(return_value=[0.0] * 1024))
        # Embeddings idénticos → confianza ≈ 1.0 entre todos → tie-breaker por LLM
        llm = modelo_de_chat()
        llm.ainvoke = AsyncMock(return_value=type("R", (),
                                                  {"content": str(router_chatbot[2].id)})())
        chatbot_provider = AsyncMock(get_children=AsyncMock(return_value=router_chatbot[1:]))
        node = build_route_to_subagent_node(embedding_service, chatbot_provider,
                                            llm_fallback=llm,
                                            confidence_threshold=0.95)
        result = await node({
            "messages": [type("M", (), {"content": "ambigua"})()],
            "chatbot_id": str(router_chatbot[0].id),
        })
        assert result["selected_child_id"] == str(router_chatbot[2].id)