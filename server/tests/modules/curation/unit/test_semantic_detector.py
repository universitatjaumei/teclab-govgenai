"""Tests TDD — SemanticContradictionDetector (Prompt 9Q.4).

Segunda pasada selectiva con LLM a nivel sitio: clustering pgvector (coseno),
control de coste y juez LLM duplicado/contradicción. Respeta audit_semantic_scope.

Fakes deterministas: LLM y embedding_service inyectados, sin red ni BD real.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest


# ───────────────────────── Fakes ─────────────────────────


class _FakeSite:
    def __init__(self, scope: str) -> None:
        self.id = uuid.uuid4()
        self.audit_semantic_scope = scope


class _FakePage:
    def __init__(self, site_id: uuid.UUID, url: str, **f: Any) -> None:
        self.id = uuid.uuid4()
        self.site_id = site_id
        self.url = url
        self.canonical_url: str | None = f.get("canonical_url", url)
        self.content_hash: str | None = f.get("content_hash", "h" + url)
        self.markdown_content: str | None = f.get("markdown_content", f"Texto de {url}")
        self.status: str = f.get("status", "active")
        self.page_embedding: list[float] | None = f.get("page_embedding")


class _FakeDocument:
    def __init__(self, crawled_page_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.crawled_page_id = crawled_page_id


class _FakeChunk:
    def __init__(self, document_id: uuid.UUID, content: str, embedding: list[float]) -> None:
        self.id = uuid.uuid4()
        self.document_id = document_id
        self.content = content
        self.embedding = embedding


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeScalars":
        return _FakeScalars(self._rows)


class _FakeScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _FakeSession:
    """Dispatch por _model_hint sobre el statement (mismo patrón que 9Q.3)."""

    def __init__(self, site: _FakeSite, pages: list, documents: list | None = None,
                 chunks: list | None = None) -> None:
        self._site = site
        self._pages = pages
        self._documents = documents or []
        self._chunks = chunks or []
        self.flush_count = 0

    async def get(self, model, ident):
        return self._site if ident == self._site.id else None

    async def execute(self, stmt):
        hint = getattr(stmt, "_model_hint", "page")
        if hint == "document":
            return _FakeResult(self._documents)
        if hint == "chunk":
            return _FakeResult(self._chunks)
        return _FakeResult(self._pages)

    async def flush(self) -> None:
        self.flush_count += 1


class _FakeEmbeddingService:
    def __init__(self, vector: list[float] | None = None) -> None:
        self.calls: list[str] = []
        self._vector = vector or [1.0, 0.0]

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return list(self._vector)


class _FakeLLM:
    model_name = "fake-judge"

    def __init__(self, response: str = '{"relation":"unrelated","confidence":0.5,"explanation":"x"}') -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, context: str) -> str:
        self.calls.append((prompt, context))
        return self.response


def _detector(session, llm, emb, **kwargs):
    from server.app.modules.curation.semantic_detector import (
        SemanticContradictionDetector,
    )

    return SemanticContradictionDetector(session, llm, emb, **kwargs)


# ───────────────────────── Cobertura "ingested" ─────────────────────────


class TestIngestedCoverage:

    @pytest.mark.asyncio
    async def test_only_ingested_pages_considered_and_zero_embeds(self) -> None:
        """Solo páginas con HubDocument; las no ingeridas se ignoran; 0 embeds."""
        site = _FakeSite("ingested")
        # A y B ingeridas (embeddings idénticos → par); C sin documento.
        page_a = _FakePage(site.id, "https://u.es/a", canonical_url="https://u.es/a")
        page_b = _FakePage(site.id, "https://u.es/b", canonical_url="https://u.es/b")
        page_c = _FakePage(site.id, "https://u.es/c", canonical_url="https://u.es/c")
        doc_a = _FakeDocument(page_a.id)
        doc_b = _FakeDocument(page_b.id)
        chunks = [
            _FakeChunk(doc_a.id, "contenido largo a", [1.0, 0.0]),
            _FakeChunk(doc_b.id, "contenido largo b", [1.0, 0.0]),
        ]
        session = _FakeSession(site, [page_a, page_b, page_c], [doc_a, doc_b], chunks)
        emb = _FakeEmbeddingService()
        llm = _FakeLLM('{"relation":"duplicate","confidence":0.95,"explanation":"iguales"}')
        det = _detector(session, llm, emb, similarity_threshold=0.9)

        findings = await det.analyze(site.id)

        assert emb.calls == []  # nunca embebe en modo ingested
        assert len(llm.calls) == 1  # único par (A,B); C ignorada
        assert len(findings) == 1
        ids_in_finding = {findings[0].page_id, findings[0].related_page_id}
        assert ids_in_finding == {page_a.id, page_b.id}

    @pytest.mark.asyncio
    async def test_representative_chunk_is_largest(self) -> None:
        site = _FakeSite("ingested")
        page_a = _FakePage(site.id, "https://u.es/a", canonical_url="https://u.es/a")
        page_b = _FakePage(site.id, "https://u.es/b", canonical_url="https://u.es/b")
        doc_a = _FakeDocument(page_a.id)
        doc_b = _FakeDocument(page_b.id)
        # El chunk más grande de A tiene embedding [1,0]; el pequeño [0,1].
        chunks = [
            _FakeChunk(doc_a.id, "corto", [0.0, 1.0]),
            _FakeChunk(doc_a.id, "este es mucho mas largo que el otro", [1.0, 0.0]),
            _FakeChunk(doc_b.id, "contenido b", [1.0, 0.0]),
        ]
        session = _FakeSession(site, [page_a, page_b], [doc_a, doc_b], chunks)
        llm = _FakeLLM('{"relation":"duplicate","confidence":0.9,"explanation":"x"}')
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.9)

        findings = await det.analyze(site.id)
        # Con el chunk grande [1,0] la similitud con B [1,0] es 1.0 → par detectado.
        assert len(findings) == 1


# ───────────────────────── Cobertura "full" ─────────────────────────


class TestFullCoverage:

    @pytest.mark.asyncio
    async def test_pages_without_embedding_are_embedded_and_persisted(self) -> None:
        site = _FakeSite("full")
        page_a = _FakePage(site.id, "https://u.es/a", canonical_url="https://u.es/a", page_embedding=None)
        page_b = _FakePage(site.id, "https://u.es/b", canonical_url="https://u.es/b", page_embedding=None)
        session = _FakeSession(site, [page_a, page_b])
        emb = _FakeEmbeddingService(vector=[1.0, 0.0])
        llm = _FakeLLM('{"relation":"unrelated","confidence":0.1,"explanation":"x"}')
        det = _detector(session, llm, emb, similarity_threshold=0.9)

        await det.analyze(site.id)

        assert len(emb.calls) == 2  # ambas páginas embebidas
        assert page_a.page_embedding == [1.0, 0.0]
        assert page_b.page_embedding == [1.0, 0.0]

    @pytest.mark.asyncio
    async def test_second_run_does_not_reembed(self) -> None:
        site = _FakeSite("full")
        page_a = _FakePage(site.id, "https://u.es/a", canonical_url="https://u.es/a", page_embedding=None)
        page_b = _FakePage(site.id, "https://u.es/b", canonical_url="https://u.es/b", page_embedding=None)
        session = _FakeSession(site, [page_a, page_b])
        emb = _FakeEmbeddingService(vector=[1.0, 0.0])
        det = _detector(session, _FakeLLM(), emb, similarity_threshold=0.9)

        await det.analyze(site.id)
        await det.analyze(site.id)

        assert len(emb.calls) == 2  # no re-embebe en la segunda pasada


# ───────────────────────── Clustering / control de coste ─────────────────────────


class TestClusteringAndCost:

    @pytest.mark.asyncio
    async def test_only_pairs_above_threshold(self) -> None:
        site = _FakeSite("full")
        # A,B muy similares; C ortogonal.
        page_a = _FakePage(site.id, "https://u.es/a", canonical_url="https://u.es/a", page_embedding=[1.0, 0.0])
        page_b = _FakePage(site.id, "https://u.es/b", canonical_url="https://u.es/b", page_embedding=[1.0, 0.0])
        page_c = _FakePage(site.id, "https://u.es/c", canonical_url="https://u.es/c", page_embedding=[0.0, 1.0])
        session = _FakeSession(site, [page_a, page_b, page_c])
        llm = _FakeLLM('{"relation":"duplicate","confidence":0.9,"explanation":"x"}')
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.92)

        await det.analyze(site.id)
        assert len(llm.calls) == 1  # solo el par (A,B)

    @pytest.mark.asyncio
    async def test_zero_pairs_means_zero_llm_calls(self) -> None:
        site = _FakeSite("full")
        page_a = _FakePage(site.id, "https://u.es/a", canonical_url="https://u.es/a", page_embedding=[1.0, 0.0])
        page_b = _FakePage(site.id, "https://u.es/b", canonical_url="https://u.es/b", page_embedding=[0.0, 1.0])
        session = _FakeSession(site, [page_a, page_b])
        llm = _FakeLLM()
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.92)

        findings = await det.analyze(site.id)
        assert llm.calls == []
        assert findings == []

    @pytest.mark.asyncio
    async def test_same_canonical_pairs_discarded(self) -> None:
        site = _FakeSite("full")
        shared = "https://u.es/canonical"
        page_a = _FakePage(site.id, "https://u.es/a?x=1", canonical_url=shared, page_embedding=[1.0, 0.0])
        page_b = _FakePage(site.id, "https://u.es/a?x=2", canonical_url=shared, page_embedding=[1.0, 0.0])
        session = _FakeSession(site, [page_a, page_b])
        llm = _FakeLLM()
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.9)

        findings = await det.analyze(site.id)
        assert llm.calls == []  # misma canonical → es 9Q.3, no se juzga aquí
        assert findings == []

    @pytest.mark.asyncio
    async def test_max_pairs_per_run_respected(self) -> None:
        site = _FakeSite("full")
        # 3 páginas mutuamente similares → 3 pares; max=1 → 1 sola llamada.
        pages = [
            _FakePage(site.id, f"https://u.es/p{i}", canonical_url=f"https://u.es/p{i}",
                      page_embedding=[1.0, 0.0])
            for i in range(3)
        ]
        session = _FakeSession(site, pages)
        llm = _FakeLLM('{"relation":"unrelated","confidence":0.1,"explanation":"x"}')
        det = _detector(session, llm, _FakeEmbeddingService(),
                        similarity_threshold=0.9, max_pairs_per_run=1)

        await det.analyze(site.id)
        assert len(llm.calls) == 1


# ───────────────────────── Juez LLM ─────────────────────────


class TestJudge:

    def _two_similar(self, site):
        a = _FakePage(site.id, "https://u.es/a", canonical_url="https://u.es/a", page_embedding=[1.0, 0.0])
        b = _FakePage(site.id, "https://u.es/b", canonical_url="https://u.es/b", page_embedding=[1.0, 0.0])
        return a, b

    @pytest.mark.asyncio
    async def test_contradiction_is_critical_with_propagated_confidence(self) -> None:
        site = _FakeSite("full")
        a, b = self._two_similar(site)
        session = _FakeSession(site, [a, b])
        llm = _FakeLLM('{"relation":"contradiction","confidence":0.87,"explanation":"se contradicen"}')
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.9)

        findings = await det.analyze(site.id)
        assert len(findings) == 1
        assert findings[0].finding_type == "contradiction"
        assert findings[0].severity == "critical"
        assert findings[0].confidence == 0.87

    @pytest.mark.asyncio
    async def test_duplicate_is_warning(self) -> None:
        site = _FakeSite("full")
        a, b = self._two_similar(site)
        session = _FakeSession(site, [a, b])
        llm = _FakeLLM('{"relation":"duplicate","confidence":0.95,"explanation":"iguales"}')
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.9)

        findings = await det.analyze(site.id)
        assert len(findings) == 1
        assert findings[0].finding_type == "duplicate"
        assert findings[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_unrelated_emits_nothing(self) -> None:
        site = _FakeSite("full")
        a, b = self._two_similar(site)
        session = _FakeSession(site, [a, b])
        llm = _FakeLLM('{"relation":"unrelated","confidence":0.2,"explanation":"distintos"}')
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.9)

        findings = await det.analyze(site.id)
        assert findings == []

    @pytest.mark.asyncio
    async def test_signal_contains_similarity_and_explanation(self) -> None:
        site = _FakeSite("full")
        a, b = self._two_similar(site)
        session = _FakeSession(site, [a, b])
        llm = _FakeLLM('{"relation":"duplicate","confidence":0.9,"explanation":"motivo X"}')
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.9)

        findings = await det.analyze(site.id)
        sig = findings[0].signal
        assert "similarity" in sig
        assert sig["explanation"] == "motivo X"

    @pytest.mark.asyncio
    async def test_judge_response_with_markdown_fences(self) -> None:
        site = _FakeSite("full")
        a, b = self._two_similar(site)
        session = _FakeSession(site, [a, b])
        fenced = '```json\n{"relation":"duplicate","confidence":0.93,"explanation":"con fences"}\n```'
        llm = _FakeLLM(fenced)
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.9)

        findings = await det.analyze(site.id)
        assert len(findings) == 1
        assert findings[0].finding_type == "duplicate"


# ───────────────────────── Anonimización ─────────────────────────


class TestAnonymization:

    @pytest.mark.asyncio
    async def test_anonymizer_invoked_when_injected(self) -> None:
        site = _FakeSite("full")
        a = _FakePage(site.id, "https://u.es/a", canonical_url="https://u.es/a",
                      markdown_content="Juan Pérez DNI 12345678Z", page_embedding=[1.0, 0.0])
        b = _FakePage(site.id, "https://u.es/b", canonical_url="https://u.es/b",
                      markdown_content="Juan Pérez DNI 12345678Z bis", page_embedding=[1.0, 0.0])
        session = _FakeSession(site, [a, b])

        anon_calls: list[str] = []

        def anonymizer(text: str) -> str:
            anon_calls.append(text)
            return "[ANON]"

        llm = _FakeLLM('{"relation":"duplicate","confidence":0.9,"explanation":"x"}')
        det = _detector(session, llm, _FakeEmbeddingService(),
                        similarity_threshold=0.9, anonymizer=anonymizer)

        await det.analyze(site.id)
        assert len(anon_calls) == 2  # ambos textos anonimizados
        # el texto que llegó al LLM es el anonimizado
        prompt_sent = llm.calls[0][0] + llm.calls[0][1]
        assert "12345678Z" not in prompt_sent
        assert "[ANON]" in prompt_sent

    @pytest.mark.asyncio
    async def test_no_anonymizer_passes_original_text(self) -> None:
        site = _FakeSite("full")
        a = _FakePage(site.id, "https://u.es/a", canonical_url="https://u.es/a",
                      markdown_content="texto original A", page_embedding=[1.0, 0.0])
        b = _FakePage(site.id, "https://u.es/b", canonical_url="https://u.es/b",
                      markdown_content="texto original B", page_embedding=[1.0, 0.0])
        session = _FakeSession(site, [a, b])
        llm = _FakeLLM('{"relation":"unrelated","confidence":0.1,"explanation":"x"}')
        det = _detector(session, llm, _FakeEmbeddingService(), similarity_threshold=0.9)

        await det.analyze(site.id)
        combined = llm.calls[0][0] + llm.calls[0][1]
        assert "texto original A" in combined
