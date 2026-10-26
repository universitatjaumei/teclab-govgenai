"""Tests RAG.5 — empaquetador de contexto con presupuesto de tokens.

Hoy la evidencia se inyecta entera y el presupuesto solo lo respetaba MD_LONG_CONTEXT. En
RAG, con `top_k` grande o documentos largos, el contexto crece sin techo hasta que el
proveedor lo corta —y cuando lo corta el proveedor, no hay traza de qué se perdió—.

El packer corta **con criterio y dejando constancia**: por score descendente y anotando
cuántas evidencias se quedaron fuera, que es lo que RAG.11 necesitará para el bypass.
"""
from __future__ import annotations

import uuid

from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)


def _evidencia(titulo: str, score: float, caracteres: int = 400) -> EvidenceItem:
    return EvidenceItem(
        source_id=str(uuid.uuid4()),
        content="x" * caracteres,
        source_url=f"https://www.uji.es/{titulo}",
        title=titulo,
        language="ca",
        score=score,
    )


class TestPresupuesto:

    def test_should_pack_context_within_token_budget(self):
        from server.app.modules.agents_hub.services.retrieval.context_packer import pack

        # 4 caracteres por token: 400 caracteres = 100 tokens por evidencia
        empaquetado = pack([_evidencia(f"n{i}", 0.9 - i / 100) for i in range(10)], 250)

        assert empaquetado.total_tokens <= 250
        assert len(empaquetado.items) == 2

    def test_should_drop_lowest_scored_evidence_first_when_cutting(self):
        from server.app.modules.agents_hub.services.retrieval.context_packer import pack

        empaquetado = pack(
            [_evidencia("floja", 0.10), _evidencia("fuerte", 0.95), _evidencia("media", 0.50)],
            250,
        )

        assert [i.title for i in empaquetado.items] == ["fuerte", "media"]

    def test_should_report_dropped_count_in_packed_context(self):
        """Sin este recuento, un contexto recortado es indistinguible de uno completo."""
        from server.app.modules.agents_hub.services.retrieval.context_packer import pack

        empaquetado = pack([_evidencia(f"n{i}", 0.9) for i in range(10)], 250)

        assert empaquetado.dropped_count == 8

    def test_should_keep_everything_when_the_budget_is_enough(self):
        from server.app.modules.agents_hub.services.retrieval.context_packer import pack

        evidencias = [_evidencia(f"n{i}", 0.9) for i in range(3)]
        empaquetado = pack(evidencias, 128_000)

        assert len(empaquetado.items) == 3
        assert empaquetado.dropped_count == 0

    def test_should_keep_the_best_one_even_if_it_does_not_fit(self):
        """Un contexto vacío no produce ninguna respuesta; uno recortado sí.

        Mismo criterio que la degradación de VIS.2 en MD_LONG_CONTEXT: si ni la mejor
        evidencia cabe, entra igualmente y el recorte queda anotado.
        """
        from server.app.modules.agents_hub.services.retrieval.context_packer import pack

        empaquetado = pack([_evidencia("enorme", 0.9, caracteres=40_000)], 100)

        assert len(empaquetado.items) == 1
        assert empaquetado.dropped_count == 0

    def test_should_return_empty_context_without_evidence(self):
        from server.app.modules.agents_hub.services.retrieval.context_packer import pack

        empaquetado = pack([], 1_000)

        assert empaquetado.items == []
        assert empaquetado.total_tokens == 0
        assert empaquetado.dropped_count == 0


class TestIntegracionConElPipeline:

    async def test_should_use_the_cascade_budget_in_the_rag_pipeline(self):
        """El packer consume el presupuesto ya resuelto por el ConfigResolver (VIS.2).

        El default de plataforma son 128.000 **con carácter general** (decisión del usuario
        del 2026-07-31): el packer no baja ese valor, lo consume.
        """
        from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
            PublicGraphConfig,
        )
        from server.app.modules.agents_hub.agent.public_graphs.strategies.rag_vector_pipeline import (
            RagVectorPipeline,
        )
        from server.app.modules.agents_hub.services.retrieval.types import (
            RetrievalContext,
            Source,
        )

        class _Estrategia:
            async def get_context(self, query, chatbot_id, language=None):
                return RetrievalContext(
                    sources=[
                        Source(
                            document_id=uuid.uuid4(), title=f"n{i}",
                            url=f"https://www.uji.es/{i}", excerpt="x" * 400,
                            score=0.9 - i / 100, metadata={},
                        )
                        for i in range(10)
                    ],
                    mode="RAG",
                    total_tokens=1000,
                )

        cfg = PublicGraphConfig(
            profile="PUBLIC_KB_RICH", retrieval_mode="RAG", language_mode="prefer",
            quality_threshold=0.6, min_retrieval_results=2, min_retrieval_score=0.25,
            reranker_enabled=False, answer_template="generic",
            context_token_budget=250,
        )
        deps = type("D", (), {"session": None, "embedder": None, "llm": None})()

        async def _factoria(deps, cfg):  # RAG.6a la hizo async (resuelve el reranker)
            return _Estrategia()

        pipeline = RagVectorPipeline()
        pipeline._construir_estrategia = _factoria  # type: ignore[attr-defined]
        resultado = await pipeline.run("q", str(uuid.uuid4()), cfg, deps)

        assert len(resultado.items) == 2
        assert resultado.debug["dropped_count"] == 8
        assert resultado.debug["context_token_budget"] == 250
