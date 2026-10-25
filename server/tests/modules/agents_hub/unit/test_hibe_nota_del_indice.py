"""HIB.E (segunda parte) — la nota que la puerta LEE de verdad en el modo agéntico.

**El error que esto corrige, y es mío.** La primera pasada de HIB.E puso la similitud coseno en
los documentos que el `AgenticLoop` **lee**. Correcto y útil —las fuentes citadas llevan ahora una
nota real— pero **no es la nota que la puerta mira**: `core_graph` toma el máximo de
`merged_items`, y para `MD_AGENT_SELECTOR` esos items son el **índice** que devuelve
`MdAgentSelectorPipeline`, no lo que el agente acabó leyendo.

Lo detectó la medición: las tres tandas del barrido de umbral —0,35, 0,50 y 0,65— dieron
`quality_score = 1.000` exacto en los 18 escenarios. Un arreglo que no mueve el número que
pretendía mover es indistinguible de no haberlo hecho, y sólo se vio porque se midió.

**Qué nota lleva ahora cada entrada del índice**: la mejor similitud coseno entre la consulta y
los fragmentos de ese documento. Con eso el máximo del índice es «la mejor coincidencia del
corpus con esta pregunta», que es **exactamente** la magnitud que la puerta lee en la rama
vectorial. Sin esa igualdad, un umbral de 0,65 significaría una cosa en el RAG y otra aquí.
"""
import uuid

import pytest

from server.app.modules.agents_hub.agent.public_graphs.strategies.md_agent_selector_pipeline import (
    MdAgentSelectorPipeline,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)


class _IndiceFalso:
    """Un proveedor con la firma nueva: recibe la consulta, porque sin ella no hay similitud
    que calcular. Que la firma vieja no compile es el punto."""

    def __init__(self, notas: dict[str, float] | None = None) -> None:
        self.notas = notas or {}
        self.consulta_vista: str | None = None

    async def build_index(self, chatbot_id: str, deps, query: str = "", language=None) -> list[EvidenceItem]:
        self.consulta_vista = query
        return [
            EvidenceItem(
                source_id=str(uuid.uuid4()),
                content=f"{titulo} (id: ...)",
                source_url=f"https://www.uji.es/{titulo}",
                title=titulo,
                language="val",
                score=nota,
                metadata={"index_entry": True},
            )
            for titulo, nota in (self.notas or {"Norma": 1.0}).items()
        ]


@pytest.mark.asyncio
class TestLaPuertaDelAgenticoLeeUnaMagnitud:

    async def test_should_pass_the_query_down_to_the_index_provider(self):
        """Sin la consulta el índice no puede llevar similitud, y ése era el motivo real de
        que la nota fuera una constante: nadie le pasaba con qué comparar."""
        proveedor = _IndiceFalso({"Reglament de permanencia": 0.74})
        pipeline = MdAgentSelectorPipeline(index_provider=proveedor)

        await pipeline.run("Quants credits he de superar?", "cb", cfg=None, deps=None)

        assert proveedor.consulta_vista == "Quants credits he de superar?"

    async def test_should_carry_a_real_score_on_each_index_entry(self):
        proveedor = _IndiceFalso({"Norma A": 0.81, "Norma B": 0.62})
        pipeline = MdAgentSelectorPipeline(index_provider=proveedor)

        salida = await pipeline.run("x", "cb", cfg=None, deps=None)

        assert sorted(i.score for i in salida.items) == [0.62, 0.81]

    async def test_should_not_return_a_flat_index_of_ones(self):
        """El guardarraíl contra la regresión exacta que se midió: 18 de 18 escenarios con
        `quality_score` 1.000 en tres umbrales distintos."""
        proveedor = _IndiceFalso({"Norma A": 0.81, "Norma B": 0.62, "Norma C": 0.55})
        pipeline = MdAgentSelectorPipeline(index_provider=proveedor)

        salida = await pipeline.run("x", "cb", cfg=None, deps=None)

        assert {i.score for i in salida.items} != {1.0}

    async def test_should_report_in_debug_whether_the_scores_are_measured(self):
        """Si no hubo con qué medir —sin embedder— el índice sale plano, y eso tiene que
        poder distinguirse de un índice medido que resultó plano. Sin la marca, la traza de
        HIB.I no permite saber cuál de las dos cosas pasó."""
        proveedor = _IndiceFalso({"Norma A": 1.0, "Norma B": 1.0})
        pipeline = MdAgentSelectorPipeline(index_provider=proveedor)

        salida = await pipeline.run("x", "cb", cfg=None, deps=None)

        assert "index_scores_medidos" in salida.debug
