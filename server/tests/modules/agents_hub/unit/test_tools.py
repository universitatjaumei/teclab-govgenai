"""Tests para las herramientas del agente."""
import uuid
import pytest
from unittest.mock import AsyncMock, Mock


class TestSearchKnowledgeTool:

    @pytest.mark.asyncio
    async def test_search_returns_formatted_results(self) -> None:
        from server.app.modules.agents_hub.agent.tools.search_knowledge import search_knowledge

        mock_retriever = AsyncMock()
        mock_retriever.hybrid_search = AsyncMock(return_value=[
            Mock(content="Resultado 1", source_url="url1", score=0.9),
            Mock(content="Resultado 2", source_url="url2", score=0.8),
        ])

        result = await search_knowledge(
            query="test query",
            chatbot_id=str(uuid.uuid4()),
            retriever=mock_retriever,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )

        assert "Resultado 1" in result
        assert "Resultado 2" in result

    @pytest.mark.asyncio
    async def test_search_handles_no_results(self) -> None:
        from server.app.modules.agents_hub.agent.tools.search_knowledge import search_knowledge

        mock_retriever = AsyncMock()
        mock_retriever.hybrid_search = AsyncMock(return_value=[])

        result = await search_knowledge(
            query="nonexistent",
            chatbot_id=str(uuid.uuid4()),
            retriever=mock_retriever,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024), embed_batch=None),
        )

        assert "no se encontr" in result.lower() or "not found" in result.lower()
