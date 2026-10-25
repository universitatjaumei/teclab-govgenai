"""Tests de contrato de pipelines — 9B.14.

Todo pipeline en RetrievalPipelineFactory debe devolver RetrievalResult con:
- items: list[EvidenceItem]  (cada item cumple los campos del contrato)
- debug: dict con clave "pipeline_mode" igual al modo solicitado
- context_source_language: str | None

Los tests son parametrizados sobre `list_modes()` —el registro, desde PLG.1—: cuando se añada
un modo nuevo, por código o por un paquete instalado, solo hay que añadir su rama de mocking.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
    PublicGraphConfig,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
    RetrievalResult,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
    get_pipeline,
    list_modes,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
    GraphDeps,
)
from server.app.modules.agents_hub.services.retrieval.types import RetrievalContext, Source

_MOCK_SOURCE = Source(
    document_id=uuid.uuid4(),
    title="Documento de contrato",
    url="https://example.com/doc",
    excerpt="Fragmento de prueba del contrato.",
    score=0.85,
    metadata={"language": "es"},
)
_MOCK_CTX = RetrievalContext(sources=[_MOCK_SOURCE], mode="mock", total_tokens=50)

# Patches por pipeline
_PATCH_RAG = (
    "server.app.modules.agents_hub.agent.public_graphs.strategies"
    ".rag_vector_pipeline.VectorRetrievalStrategy.get_context"
)
_PATCH_MD = (
    "server.app.modules.agents_hub.agent.public_graphs.strategies"
    ".md_long_context_pipeline.LongContextRetrievalStrategy.get_context"
)


def _make_cfg(mode: str) -> PublicGraphConfig:
    return PublicGraphConfig(
        profile="PUBLIC_KB_RICH",
        retrieval_mode=mode,
        language_mode="prefer",
        quality_threshold=0.6,
        min_retrieval_results=2,
        min_retrieval_score=0.25,
        reranker_enabled=False,
        answer_template="generic",
    )


def _make_selector_deps() -> GraphDeps:
    """Deps con session mock preparado para MdAgentSelectorPipeline."""
    mock_doc = MagicMock()
    mock_doc.id = uuid.uuid4()
    mock_doc.markdown_content = "Contenido de documento de prueba."
    mock_doc.canonical_url = "https://example.com/doc"
    mock_doc.title = "Documento de prueba"
    mock_doc.language = "es"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_doc]

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    return GraphDeps(session=session, embedder=AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list_modes())
class TestPipelineContractSuite:

    async def test_pipeline_returns_retrieval_result(self, mode: str):
        """Todo pipeline debe devolver un RetrievalResult válido."""
        pipeline = get_pipeline(mode)
        cfg = _make_cfg(mode)
        chatbot_id = str(uuid.uuid4())

        if mode == "MD_AGENT_SELECTOR":
            deps = _make_selector_deps()
            result = await pipeline.run("consulta de contrato", chatbot_id, cfg, deps)
        elif mode == "MD_LONG_CONTEXT":
            deps = GraphDeps(session=AsyncMock(), embedder=AsyncMock())
            with patch(_PATCH_MD, AsyncMock(return_value=_MOCK_CTX)):
                result = await pipeline.run("consulta de contrato", chatbot_id, cfg, deps)
        else:  # RAG
            deps = GraphDeps(session=AsyncMock(), embedder=AsyncMock())
            with patch(_PATCH_RAG, AsyncMock(return_value=_MOCK_CTX)):
                result = await pipeline.run("consulta de contrato", chatbot_id, cfg, deps)

        assert isinstance(result, RetrievalResult), (
            f"Pipeline '{mode}' debe devolver RetrievalResult, no {type(result).__name__}"
        )
        assert isinstance(result.items, list), "items debe ser una lista"
        assert isinstance(result.debug, dict), "debug debe ser un dict"
        assert "pipeline_mode" in result.debug, "debug debe contener 'pipeline_mode'"
        assert result.debug["pipeline_mode"] == mode

    async def test_pipeline_items_conform_to_evidence_item_contract(self, mode: str):
        """Cada item devuelto debe ser EvidenceItem con source_id y content no vacíos."""
        pipeline = get_pipeline(mode)
        cfg = _make_cfg(mode)

        if mode == "MD_AGENT_SELECTOR":
            deps = _make_selector_deps()
            result = await pipeline.run("consulta", str(uuid.uuid4()), cfg, deps)
        elif mode == "MD_LONG_CONTEXT":
            deps = GraphDeps(session=AsyncMock(), embedder=AsyncMock())
            with patch(_PATCH_MD, AsyncMock(return_value=_MOCK_CTX)):
                result = await pipeline.run("consulta", str(uuid.uuid4()), cfg, deps)
        else:  # RAG
            deps = GraphDeps(session=AsyncMock(), embedder=AsyncMock())
            with patch(_PATCH_RAG, AsyncMock(return_value=_MOCK_CTX)):
                result = await pipeline.run("consulta", str(uuid.uuid4()), cfg, deps)

        for item in result.items:
            assert isinstance(item, EvidenceItem), (
                f"Pipeline '{mode}': item debe ser EvidenceItem, no {type(item).__name__}"
            )
            assert isinstance(item.source_id, str), "source_id debe ser un str no vacío"
            assert item.source_id, "source_id debe ser un str no vacío"
            assert isinstance(item.content, str), "content debe ser str"
