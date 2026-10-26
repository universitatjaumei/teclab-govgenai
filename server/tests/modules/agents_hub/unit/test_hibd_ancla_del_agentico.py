"""HIB.D — de dónde sale el ancla en el modo selector, y por qué a veces no hay.

**Paso 0 del prompt, que era obligatorio, y el resultado matiza su premisa.** El prompt partía
de que «el pipeline agéntico cita `canonical_url` sin ancla», señalando
`md_agent_selector_pipeline.py:79`. Siguiendo el camino real de una cita:

1. Esa línea 79 construye el **índice** —las fichas que el modelo lee para elegir—, y el índice
   **no es citable**: `core_graph` toma los `citables` de `agentic_loop.run()`, que devuelve
   `leidas`, los documentos que el bucle abrió de verdad. Así que la línea señalada no es la
   fuente de ninguna cita.
2. `search_knowledge` **sí lleva el ancla**, y por el mismo camino que el RAG: sus resultados
   pasan por `_BuscadorVectorial.search` → `VectorRetrievalStrategy.get_context`, donde la URL
   se construye con `url_de_cita(doc, best.metadata)` (PUB.3 / ING.0.4), y `_source_to_evidence`
   la conserva en `source_url`. **No hay nada que arreglar aquí.**
3. `read_document` **no lleva ancla**, y es correcto que no la lleve: inyecta el documento
   **entero**, así que no hay un artículo concreto al que apuntar. Poner uno arbitrario sería
   peor que no poner ninguno —apuntaría a un artículo que no es el que fundamenta la
   afirmación— y el contrato de citas no lo cazaría, porque sólo detecta anclas **inexistentes**,
   no anclas equivocadas (defecto 3 del inventario del 2026-08-26).

Conclusión: **el prompt se cierra sin cambio de código**, que es uno de los dos resultados que
él mismo admite. Lo que queda es esta prueba, y su función es impedir el arreglo equivocado: que
alguien lea «el agéntico no pone ancla» y le ponga una a las lecturas de documento entero.

Deploy: edge
"""
from __future__ import annotations

import inspect
from pathlib import Path



class TestSearchKnowledgeCitaConAncla:

    def test_should_build_the_fragment_url_through_the_citation_helper(self):
        """El ancla no se pega a mano en el agéntico: viene de recorrer el mismo camino."""
        from server.app.modules.agents_hub.agent.public_graphs.core import graph_factory

        fuente = inspect.getsource(graph_factory._BuscadorVectorial.search)

        assert "_source_to_evidence" in fuente
        assert "get_context" in fuente

    def test_should_keep_the_url_of_the_source_in_the_evidence(self):
        """Si `_source_to_evidence` perdiera la URL, el ancla se caería en silencio."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.rag_vector_pipeline import (
            _source_to_evidence,
        )
        from server.app.modules.agents_hub.services.retrieval.types import Source
        import uuid

        fuente = Source(
            document_id=uuid.uuid4(),
            title="Llei 9/2017",
            url="https://www.uji.es/norma/contractacio#a118",
            excerpt="...",
            score=0.8,
            metadata={},
        )

        assert _source_to_evidence(fuente).source_url.endswith("#a118")

    def test_should_carry_the_fragment_url_into_the_agentic_evidence(self):
        """`_buscar` extiende `leidas` con lo que devuelve el buscador, sin reescribir URLs."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies import agentic_loop

        fuente = inspect.getsource(agentic_loop)
        cuerpo = fuente[fuente.index("async def _buscar") :]

        assert "leidas.extend(encontrados)" in cuerpo
        # Y no se reconstruye la URL a partir del documento, que es donde se perdería.
        assert "canonical_url" not in cuerpo.split("return")[0]


class TestReadDocumentNoInventaAncla:

    def test_should_cite_the_whole_document_without_an_anchor(self):
        """Un documento entero no tiene un artículo al que apuntar.

        `AgenticRetrievalStrategy.read` devuelve `canonical_url`, y eso es lo correcto: la
        alternativa —elegir un ancla cualquiera del documento— produciría una cita que abre
        un artículo que no fundamenta nada, y el contrato de citas la aceptaría porque el
        ancla **existe**.
        """
        from server.app.modules.agents_hub.services.retrieval import agentic_strategy

        fuente = inspect.getsource(agentic_strategy.AgenticRetrievalStrategy.read)

        assert '"url": doc.canonical_url' in fuente
        assert "with_anchor" not in fuente
        assert "url_de_cita" not in fuente

    def test_should_not_grow_an_anchor_on_a_whole_document_read(self):
        """Guardarraíl del arreglo equivocado.

        Si alguien lee «el agéntico no pone ancla» y se lo añade aquí, este test se pone
        rojo y le manda a leer el paso 0 de HIB.D.
        """
        fuente = Path(
            "app/modules/agents_hub/agent/public_graphs/strategies/agentic_loop.py"
        ).read_text(encoding="utf-8")
        cuerpo = fuente[fuente.index('if nombre == "read_document"') :]
        cuerpo = cuerpo[: cuerpo.index('if nombre == "search_knowledge"')]

        for inventado in ("with_anchor", "url_de_cita", "#art", 'anchor"'):
            assert inventado not in cuerpo, (
                f"«{inventado}» en la lectura de documento entero: HIB.D midió que ahí no hay "
                "artículo al que apuntar y que un ancla arbitraria es peor que ninguna"
            )


class TestElIndiceNoEsCitable:

    def test_should_take_the_citable_set_from_what_the_loop_read(self):
        """Los `citables` son `leidas`, no los ítems del índice.

        Es lo que hace que la línea que el prompt señalaba —`source_url=d.canonical_url` en
        `build_index`— no sea la fuente de ninguna cita.
        """
        from server.app.modules.agents_hub.agent.public_graphs.core import core_graph

        fuente = inspect.getsource(core_graph)

        assert "citables, answer = await self.agentic_loop.run(" in fuente
