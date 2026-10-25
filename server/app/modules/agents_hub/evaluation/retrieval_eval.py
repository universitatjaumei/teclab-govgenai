"""Harness de evaluación del retriever y gate de regresión (RAG.1). Deploy: edge.

Ejecuta el dataset dorado contra `HybridRetriever` y produce cifras comparables. El gate
compara con una línea base versionada y **falla solo si alguna métrica baja más que la
tolerancia**: una mejora siempre pasa, y el ruido de un cambio de fusión no rompe el build.

Qué mide y qué NO mide, porque es fácil confundirlo:

- **Mide el mecanismo de recuperación**: fusión híbrida, filtros, ranking, umbral. Eso es
  lo que cambian RAG.3–RAG.8, y por eso el gate vive en CI.
- **No mide la calidad del modelo de embedding.** El corpus de fixture se ingiere con un
  embedding determinista para que el resultado sea reproducible; medir BGE-M3 exige el
  corpus real y va por la vía manual/nocturna del CLI.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from server.app.modules.agents_hub.evaluation.golden_dataset import (
    GoldenDataset,
    GoldenQuery,
)
from server.app.modules.agents_hub.evaluation.retrieval_metrics import (
    mrr,
    promedio,
    recall_at_k,
)

TOLERANCIA_POR_DEFECTO = 0.02


class Retriever(Protocol):
    async def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        chatbot_id: uuid.UUID,
        top_k: int = ...,
        language: str | None = ...,
    ) -> list: ...


class EmbeddingService(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class Rewriter(Protocol):
    async def __call__(self, query: str, history: list[str]) -> str: ...


@dataclass(frozen=True)
class QueryResult:
    query: str
    tags: tuple[str, ...]
    expected: list[str]
    # Lo recuperado se guarda entero: sin esto, un fallo del dorado no se puede depurar
    # sin volver a ejecutar la consulta a mano.
    retrieved: list[str]
    recall_at_5: float
    recall_at_10: float
    mrr: float


@dataclass(frozen=True)
class EvalReport:
    dataset: str
    per_query: tuple[QueryResult, ...]
    recall_at_5: float
    recall_at_10: float
    mrr: float

    def render(self) -> str:
        return (
            f"{self.dataset}: recall@5={self.recall_at_5:.3f} "
            f"recall@10={self.recall_at_10:.3f} mrr={self.mrr:.3f} "
            f"({len(self.per_query)} consultas)"
        )

    def to_baseline(self) -> dict:
        return {
            "dataset": self.dataset,
            "queries": len(self.per_query),
            "recall_at_5": round(self.recall_at_5, 4),
            "recall_at_10": round(self.recall_at_10, 4),
            "mrr": round(self.mrr, 4),
        }


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    summary: str
    regressions: list[str] = field(default_factory=list)


def _objetivos(consulta: GoldenQuery) -> list[str]:
    return list(consulta.targets)


async def run_golden_eval(
    retriever: Retriever,
    embedding: EmbeddingService,
    dataset: GoldenDataset,
    chatbot_id: uuid.UUID,
    top_k: int = 10,
    rewriter: "Rewriter | None" = None,
) -> EvalReport:
    """Ejecuta cada consulta del dorado y agrega las métricas.

    `rewriter` (RAG.10) permite medir la reescritura de consulta ON vs OFF sin montar el
    grafo entero: es el único punto donde el harness necesita saber que existe, porque la
    reescritura cambia **con qué se busca** y nada más.
    """
    resultados: list[QueryResult] = []

    for consulta in dataset.queries:
        texto = consulta.query
        if rewriter is not None and consulta.history:
            texto = await rewriter(consulta.query, list(consulta.history))
        vector = await embedding.embed(texto)
        hallados = await retriever.hybrid_search(
            query=texto,
            query_embedding=vector,
            chatbot_id=chatbot_id,
            top_k=top_k,
            language=None,
        )
        # El eje de comparación es la URL de la fuente, que es lo que el dorado declara.
        recuperados = [r.source_url for r in hallados]
        objetivos = _objetivos(consulta)
        resultados.append(
            QueryResult(
                query=consulta.query,
                tags=consulta.tags,
                expected=objetivos,
                retrieved=recuperados,
                recall_at_5=recall_at_k(recuperados, objetivos, k=5),
                recall_at_10=recall_at_k(recuperados, objetivos, k=10),
                mrr=mrr(recuperados, objetivos),
            )
        )

    return EvalReport(
        dataset=dataset.name,
        per_query=tuple(resultados),
        recall_at_5=promedio([r.recall_at_5 for r in resultados]),
        recall_at_10=promedio([r.recall_at_10 for r in resultados]),
        mrr=promedio([r.mrr for r in resultados]),
    )


def check_gate(
    informe: EvalReport,
    baseline: EvalReport | dict | None,
    tolerance: float = TOLERANCIA_POR_DEFECTO,
) -> GateVerdict:
    """Compara con la línea base. Sin baseline no hay gate, pero sí informe."""
    if baseline is None:
        return GateVerdict(
            passed=True,
            summary=f"sin baseline con la que comparar; {informe.render()}",
        )

    base = baseline.to_baseline() if isinstance(baseline, EvalReport) else baseline
    regresiones: list[str] = []
    for metrica in ("recall_at_5", "recall_at_10", "mrr"):
        actual = getattr(informe, metrica)
        referencia = float(base.get(metrica, 0.0))
        if actual < referencia - tolerance:
            regresiones.append(
                f"{metrica}: {actual:.3f} < {referencia:.3f} - {tolerance:.2f}"
            )

    if regresiones:
        return GateVerdict(
            passed=False,
            summary=f"{len(regresiones)} metrica(s) por debajo de la baseline",
            regressions=regresiones,
        )
    return GateVerdict(passed=True, summary=f"dentro de la baseline; {informe.render()}")
