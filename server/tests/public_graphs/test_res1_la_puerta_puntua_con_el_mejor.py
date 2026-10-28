"""RES.1 — La puerta pregunta si hay UNA fuente buena, no si la media es buena.

`merge_node` calculaba la nota que decide si se responde como **media de todas** las
puntuaciones. Consecuencia: **la cola vota**, y ensanchar la búsqueda baja mecánicamente la nota,
de modo que `retrieval_top_k` —un mando de amplitud— decidía de rebote cuántas preguntas se
contestan.

Dos casos reales medidos el 2026-08-25, y son el motivo del cambio:

- `SGE-01` (créditos por ser miembro del Claustro): mejor fragmento **0,637**, media **0,371**,
  umbral 0,50 → se rendía. La evidencia estaba y la enterró el promedio.
- `REAL-07` (dieta con ingresos externos): mejor **0,626**, media **0,327**, umbral 0,35 → igual.

Medido sobre las dos baterías reales, la política del mejor fragmento da **20 de 25** y **4 de 7**
con *cualquier* anchura —2, 3, 5 u 8—, frente a 18 y 2. La columna plana es lo que se busca: que la
anchura deje de decidir si se contesta.

Lo que **no** cambia, y conviene que se lea aquí: la penalización por número de resultados
(`len(items) < min_retrieval_results` ⇒ ×0,5) mide otra cosa —cuántos resultados hay— y
desacoplarla del `top_k` fue justo lo que arregló RAG.15.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
    PublicGraphConfig,
)
from server.app.modules.agents_hub.agent.public_graphs.core.core_graph import CoreGraph
from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import RetrievalOutput
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
    GraphDeps,
)
from server.tests.dobles import modelo_de_chat


def _cfg(*, umbral: float, minimo: int = 1) -> PublicGraphConfig:
    return PublicGraphConfig(
        profile="PUBLIC_KB_RICH",
        retrieval_mode="RAG",
        language_mode="prefer",
        quality_threshold=umbral,
        min_retrieval_results=minimo,
        min_retrieval_score=0.0,
        reranker_enabled=False,
        answer_template="generic",
    )


def _grafo(items, cfg):
    retrieval = MagicMock()
    retrieval.retrieve = AsyncMock(return_value=RetrievalOutput(buckets=[]))
    merge = MagicMock()
    merge.merge = MagicMock(return_value=items)
    template = MagicMock()
    template.build_prompt_context = MagicMock(return_value="contexto")
    language = MagicMock()
    language.detect = MagicMock(return_value="es")
    language.filter_items = MagicMock(side_effect=lambda lang, elementos: elementos)
    language.should_warn_translation = MagicMock(return_value=False)

    llm = modelo_de_chat()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="respuesta"))

    return CoreGraph(
        retrieval_strategy=retrieval,
        merge_strategy=merge,
        template_strategy=template,
        language_policy=language,
        cfg=cfg,
        deps=GraphDeps(session=AsyncMock(), embedder=AsyncMock(), llm=llm),
        llm=llm,
    )


def _item(score: float, titulo: str = "Norma") -> EvidenceItem:
    return EvidenceItem(
        source_id=str(uuid.uuid4()), content="texto", title=titulo, score=score
    )


async def _estado(items, cfg) -> dict:
    grafo = _grafo(items, cfg)
    return await grafo.compile().ainvoke({
        "query": "una pregunta",
        "chatbot_id": str(uuid.uuid4()),
        "language": None,
        "history": [],
        "rewritten_query": None,
        "debug_bypass": False,
        "capture_context": False,
        "bypass": None,
        "retrieval_output": None,
        "merged_items": [],
        "answer": None,
        "quality_score": 0.0,
        "fallback_used": False,
        "translation_warning": False,
        "fallback_reason": None,
        "sources": [],
    })


@pytest.mark.asyncio
class TestLaNotaSaleDelMejorFragmento:

    async def test_should_score_the_gate_on_the_best_fragment(self):
        estado = await _estado(
            [_item(0.80), _item(0.40), _item(0.20)], _cfg(umbral=0.5)
        )
        assert estado["quality_score"] == pytest.approx(0.80)

    async def test_should_not_let_the_weak_tail_lower_the_score(self):
        """**El caso SGE-01.** Con la media (0,374) se rendía; con el mejor (0,637) responde.

        Es el test que justifica el prompt entero: la evidencia existía y la enterraba el
        promedio de los fragmentos que venían detrás.
        """
        items = [_item(0.637), _item(0.30), _item(0.29), _item(0.28)]

        estado = await _estado(items, _cfg(umbral=0.5))

        assert estado["quality_score"] == pytest.approx(0.637)
        # Se mira el MOTIVO y no `fallback_used`: con un LLM simulado que responde sin citar,
        # el contrato de citas degrada la respuesta y activa el fallback por su cuenta. Eso es
        # asunto de los tests del contrato; aquí lo que se afirma es que **la puerta dejó pasar**.
        assert estado["fallback_reason"] != "quality_gate", (
            "con un fragmento de 0,637 y un umbral de 0,50 la puerta tiene que dejar pasar; "
            "la media de la cola (0,374) no es la pregunta que hace el filtro"
        )

    async def test_should_not_depend_on_how_many_weak_items_follow(self):
        """La nota no puede moverse por añadir cola: eso es lo que acoplaba el umbral al top_k."""
        mejor = _item(0.70)
        cola = [_item(0.21), _item(0.20), _item(0.19), _item(0.18)]

        estrecho = await _estado([mejor] + cola[:1], _cfg(umbral=0.5))
        ancho = await _estado([mejor] + cola, _cfg(umbral=0.5))

        assert estrecho["quality_score"] == ancho["quality_score"]


@pytest.mark.asyncio
class TestLoQueNoCambia:

    async def test_should_still_penalise_when_fewer_items_than_the_minimum(self):
        """La penalización por número de resultados mide otra cosa y se queda."""
        estado = await _estado([_item(0.80)], _cfg(umbral=0.5, minimo=3))

        assert estado["quality_score"] == pytest.approx(0.40)
        assert estado["fallback_used"] is True

    async def test_should_keep_zero_when_there_are_no_items(self):
        estado = await _estado([], _cfg(umbral=0.5))

        assert estado["quality_score"] == 0.0
        assert estado["fallback_used"] is True

    async def test_should_keep_the_courtesy_score_when_items_have_no_score(self):
        """Items sin puntuación no son lo mismo que no tener items, y ya se distinguían."""
        sin_nota = EvidenceItem(source_id="x", content="texto", score=None)

        estado = await _estado([sin_nota], _cfg(umbral=0.4))

        assert estado["quality_score"] == pytest.approx(0.5)


@pytest.mark.asyncio
class TestLaTrazaDiceQueFragmentoDecidio:
    """Sin esto, depurar una respuesta rechazada pasa de leer un número a reproducir la
    consulta contra el corpus real."""

    async def test_should_record_which_fragment_set_the_score(self):
        estado = await _estado(
            [_item(0.31, "La que no manda"), _item(0.64, "La que decide")],
            _cfg(umbral=0.5),
        )

        assert estado.get("quality_source") is not None
        assert estado["quality_source"]["title"] == "La que decide"
        assert estado["quality_source"]["score"] == pytest.approx(0.64)
