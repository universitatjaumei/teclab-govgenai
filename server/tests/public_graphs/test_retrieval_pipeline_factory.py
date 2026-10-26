"""Tests de RetrievalPipelineFactory — 9B.5 (RED → GREEN)."""
import pytest


class TestRetrievalPipelineFactory:

    def test_factory_returns_pipeline_for_each_mode(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
            get_pipeline,
        )
        import asyncio

        for mode in ["RAG", "MD_LONG_CONTEXT", "MD_AGENT_SELECTOR"]:
            pipeline = get_pipeline(mode)
            assert hasattr(pipeline, "run"), f"Pipeline for {mode!r} missing .run"
            assert asyncio.iscoroutinefunction(pipeline.run), f"{mode!r} .run must be async"

    def test_factory_raises_for_unknown_mode(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
            get_pipeline,
        )
        with pytest.raises(ValueError, match="Unknown retrieval mode"):
            get_pipeline("UNKNOWN_MODE")

    def test_factory_raises_for_empty_mode(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
            get_pipeline,
        )
        with pytest.raises(ValueError, match="Unknown retrieval mode"):
            get_pipeline("")

    def test_factory_returns_distinct_instances(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
            get_pipeline,
        )
        p1 = get_pipeline("RAG")
        p2 = get_pipeline("RAG")
        assert p1 is not p2

    def test_factory_returns_rag_vector_pipeline_type(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
            get_pipeline,
        )
        from server.app.modules.agents_hub.agent.public_graphs.strategies.rag_vector_pipeline import (
            RagVectorPipeline,
        )
        assert isinstance(get_pipeline("RAG"), RagVectorPipeline)

    def test_factory_returns_md_long_context_pipeline_type(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
            get_pipeline,
        )
        from server.app.modules.agents_hub.agent.public_graphs.strategies.md_long_context_pipeline import (
            MdLongContextPipeline,
        )
        assert isinstance(get_pipeline("MD_LONG_CONTEXT"), MdLongContextPipeline)

    def test_factory_returns_md_agent_selector_pipeline_type(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
            get_pipeline,
        )
        from server.app.modules.agents_hub.agent.public_graphs.strategies.md_agent_selector_pipeline import (
            MdAgentSelectorPipeline,
        )
        assert isinstance(get_pipeline("MD_AGENT_SELECTOR"), MdAgentSelectorPipeline)
