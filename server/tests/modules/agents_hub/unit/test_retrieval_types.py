"""Tests de los tipos compartidos de retrieval -- TDD RED."""
import uuid
import dataclasses

import pytest


class TestSource:

    def test_source_is_frozen(self):
        from server.app.modules.agents_hub.services.retrieval.types import Source
        s = Source(document_id=uuid.uuid4(), title="X", url="u", excerpt="e", score=0.9)
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.score = 0.5  # frozen dataclass

    def test_source_default_metadata_empty(self):
        from server.app.modules.agents_hub.services.retrieval.types import Source
        s = Source(document_id=uuid.uuid4(), title="X", url="u", excerpt="e", score=1.0)
        assert s.metadata == {}


class TestRetrievalContext:

    def test_empty_context(self):
        from server.app.modules.agents_hub.services.retrieval.types import RetrievalContext
        ctx = RetrievalContext(sources=[], mode="RAG", total_tokens=0)
        assert ctx.sources == []
        assert ctx.mode == "RAG"


class TestRetrievalStrategyProtocol:

    def test_protocol_requires_get_context_and_get_agent_tools(self):
        from server.app.modules.agents_hub.services.retrieval.types import RetrievalStrategy
        assert hasattr(RetrievalStrategy, "get_context")
        assert hasattr(RetrievalStrategy, "get_agent_tools")
