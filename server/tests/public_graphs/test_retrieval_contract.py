"""Tests de contrato del retrieval para grafos públicos — 9B.4 (RED → GREEN).

Verifican que EvidenceItem y RetrievalResult cumplen el contrato común
que todas las RetrievalPipeline deben respetar, con independencia de la
estrategia concreta (RAG, MD_LONG_CONTEXT, MD_AGENT_SELECTOR).
"""
import dataclasses

import pytest


class TestEvidenceItem:

    def test_evidence_item_has_required_fields(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            EvidenceItem,
        )
        item = EvidenceItem(source_id="doc-1", content="Texto de prueba.")

        assert item.source_id == "doc-1"
        assert item.content == "Texto de prueba."
        assert item.source_url is None
        assert item.title is None
        assert item.language is None
        assert item.score is None
        assert isinstance(item.metadata, dict)

    def test_evidence_item_is_frozen(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            EvidenceItem,
        )
        item = EvidenceItem(source_id="doc-1", content="Contenido.")
        with pytest.raises(dataclasses.FrozenInstanceError):
            item.score = 0.9  # type: ignore[misc]  # frozen dataclass

    def test_evidence_item_optional_fields_accepted(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            EvidenceItem,
        )
        item = EvidenceItem(
            source_id="doc-2",
            content="Artículo de normativa.",
            source_url="https://example.com/norma",
            title="Normativa X",
            language="es",
            score=0.87,
            metadata={"section": "3.1"},
        )
        assert item.title == "Normativa X"
        assert item.language == "es"
        assert item.score == pytest.approx(0.87)
        assert item.metadata == {"section": "3.1"}


class TestRetrievalResult:

    def test_pipeline_result_has_items_and_debug(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            RetrievalResult,
        )
        result = RetrievalResult(items=[], debug={})

        assert hasattr(result, "items")
        assert hasattr(result, "debug")
        assert isinstance(result.items, list)
        assert isinstance(result.debug, dict)

    def test_context_source_language_is_set_when_items_present(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            EvidenceItem,
            RetrievalResult,
        )
        items = [
            EvidenceItem(source_id="doc-1", content="Contenido A.", language="es"),
            EvidenceItem(source_id="doc-2", content="Contenido B.", language="es"),
        ]
        result = RetrievalResult(items=items, debug={}, context_source_language="es")

        assert result.context_source_language == "es"
        assert len(result.items) == 2
        assert all(i.language == "es" for i in result.items)

    def test_context_source_language_is_none_by_default(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            RetrievalResult,
        )
        result = RetrievalResult(items=[], debug={})
        assert result.context_source_language is None

    def test_contract_is_serializable_or_repr_safe(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            EvidenceItem,
            RetrievalResult,
        )
        item = EvidenceItem(
            source_id="doc-1",
            content="Texto de ejemplo.",
            title="Título del documento",
            score=0.9,
        )
        result = RetrievalResult(
            items=[item],
            debug={"tokens_used": 42, "pipeline_mode": "RAG"},
            context_source_language="es",
        )
        repr_str = repr(result)

        assert "RetrievalResult" in repr_str
        assert "doc-1" in repr_str

    def test_debug_dict_accepts_arbitrary_trace_data(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            RetrievalResult,
        )
        debug = {
            "tokens_used": 512,
            "pipeline_mode": "MD_LONG_CONTEXT",
            "docs_selected": 3,
            "reranker_applied": False,
        }
        result = RetrievalResult(items=[], debug=debug)
        assert result.debug["pipeline_mode"] == "MD_LONG_CONTEXT"
        assert result.debug["docs_selected"] == 3


class TestRetrievalPipelineProtocol:

    def test_graph_deps_has_session_and_embedder(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
            GraphDeps,
        )
        deps = GraphDeps(session=object(), embedder=object())
        assert deps.session is not None
        assert deps.embedder is not None
        assert deps.llm is None

    def test_graph_deps_accepts_optional_llm(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
            GraphDeps,
        )
        fake_llm = object()
        deps = GraphDeps(session=object(), embedder=object(), llm=fake_llm)
        assert deps.llm is fake_llm

    def test_retrieval_pipeline_protocol_is_importable(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
            RetrievalPipeline,
        )
        assert RetrievalPipeline is not None

    def test_retrieval_pipeline_protocol_has_run_method(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
            RetrievalPipeline,
        )
        assert hasattr(RetrievalPipeline, "run")
