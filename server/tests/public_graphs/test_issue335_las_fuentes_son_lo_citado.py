"""#335 — en contexto largo, las fuentes de la respuesta son los documentos que cita.

En `MD_LONG_CONTEXT` todo el corpus está en el contexto, así que todo es citable, y el
`CoreGraph` devolvía como `sources` todo lo citable: 15 o 23 fuentes por respuesta en un corpus
de 23 documentos. La lista no informaba de nada, ni a quien lee ni a la traza de
`hub_interactions`.

En los demás modos no cambia nada: sus fuentes ya son lo recuperado, que es poco y está
ordenado por relevancia.
"""
from __future__ import annotations

import uuid

import pytest

from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)


def _item(titulo: str, sin_validar: bool = False) -> EvidenceItem:
    return EvidenceItem(
        source_id=str(uuid.uuid4()),
        content=f"Article 1 de {titulo}",
        source_url=f"https://normativa.example.org/html/{titulo}.html",
        title=titulo,
        language="ca",
        score=1.0,
        metadata={"vigencia_no_validada": sin_validar},
    )


@pytest.mark.asyncio
async def test_en_contexto_largo_las_fuentes_son_las_citadas() -> None:
    a, b, c = _item("A"), _item("B"), _item("C")

    estado = await _ejecutar("MD_LONG_CONTEXT", [a, b, c], f"Es X [A]({a.source_url}).")

    assert [s.title for s in estado["sources"]] == ["A"]


@pytest.mark.asyncio
async def test_una_cita_con_ancla_cuenta_para_su_documento() -> None:
    """Hasta #336 el contrato baja el ancla al documento; después la admitirá. En los dos casos
    la cita es de ese documento."""
    a, b = _item("A"), _item("B")

    estado = await _ejecutar("MD_LONG_CONTEXT", [a, b], f"Es X [A, art. 3]({a.source_url}#art-3).")

    assert [s.title for s in estado["sources"]] == ["A"]


@pytest.mark.asyncio
async def test_el_aviso_de_vigencia_es_de_lo_citado() -> None:
    """Con todo el corpus como fuente, cualquier documento sin vigencia validada del corpus
    disparaba el aviso, aunque la respuesta no lo citara."""
    from server.app.modules.agents_hub.services.retrieval.vigencia import (
        AVISO_VIGENCIA_NO_VALIDADA,
    )

    a, b = _item("A"), _item("B", sin_validar=True)

    estado = await _ejecutar("MD_LONG_CONTEXT", [a, b], f"Es X [A]({a.source_url}).")

    assert AVISO_VIGENCIA_NO_VALIDADA not in estado["answer"]


@pytest.mark.asyncio
async def test_en_rag_las_fuentes_no_cambian() -> None:
    a, b = _item("A"), _item("B")

    estado = await _ejecutar("RAG", [a, b], f"Es X [A]({a.source_url}).")

    assert [s.title for s in estado["sources"]] == ["A", "B"]


# ───────────────────────── Andamiaje del grafo (el de test_vis_vigencia) ─────────────────────────


async def _ejecutar(modo: str, items: list[EvidenceItem], respuesta: str) -> dict:
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )
    from server.app.modules.agents_hub.agent.public_graphs.core.core_graph import CoreGraph
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        GenericAnswerTemplateStrategy,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
        RetrievalOutput,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
        RetrievalResult,
    )

    class _Retrieval:
        async def retrieve(self, query, chatbot_id, cfg, deps, language=None):
            return RetrievalOutput(
                buckets=[RetrievalResult(items=items, debug={}, context_source_language="ca")]
            )

    class _Merge:
        def merge(self, output):
            return [i for b in output.buckets for i in b.items]

    class _Lang:
        def detect(self, query):
            return "ca"

        def filter_items(self, language, items):
            return items

        def should_warn_translation(self, a, b):
            return False

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _LLM:
        async def ainvoke(self, mensajes):
            return _Resp(respuesta)

    cfg = PublicGraphConfig(
        profile="PUBLIC_KB_RICH", retrieval_mode=modo, language_mode="prefer",
        quality_threshold=0.0, min_retrieval_results=1, min_retrieval_score=0.0,
        reranker_enabled=False, answer_template="generic",
    )
    grafo = CoreGraph(
        retrieval_strategy=_Retrieval(),
        merge_strategy=_Merge(),
        template_strategy=GenericAnswerTemplateStrategy(retrieval_mode=modo),
        language_policy=_Lang(),
        cfg=cfg,
        deps=type("D", (), {"session": None, "embedder": None, "llm": None})(),
        llm=_LLM(),
    )
    return await grafo.run("quant?", str(uuid.uuid4()))
