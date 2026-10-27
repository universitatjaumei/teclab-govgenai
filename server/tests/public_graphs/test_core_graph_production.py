"""Tests de RAG.2 — CoreGraph a producción (RED primero).

Lo que RAG.2 añade sobre el CoreGraph de 9B.7:

- El fallback del quality gate **emite el mensaje** «no tengo información suficiente»
  como respuesta normal, en vez de dejar `answer=None`, y anota `fallback_reason`.
- `enforce_citation_contract` se aplica tras la generación, con `fallback_reason='citation'`.
- El loop agéntico (bind_tools, máx. 10 iteraciones) vive en un componente reutilizable.
- El pipeline MD_AGENT_SELECTOR entrega un **índice** como evidencia inicial y delega la
  selección; el punto de extensión queda aislado para que VIS.2 sustituya el índice de
  documentos por el de submaterias sin tocar el grafo.
- El system prompt (base del chatbot + REGLAS DE CITA + bloque de fuentes) lo construye la
  TemplateStrategy: una sola fuente de verdad.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.agents_hub.agent.citation_validator import NO_CITATION_FALLBACK
from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
    PublicGraphConfig,
)
from server.app.modules.agents_hub.agent.public_graphs.core.core_graph import CoreGraph
from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
    RetrievalOutput,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
    RetrievalResult,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
    GraphDeps,
)
from server.tests.dobles import modelo_de_chat


def _cfg(**over) -> PublicGraphConfig:
    base = dict(
        profile="PUBLIC_KB_RICH",
        retrieval_mode="RAG",
        language_mode="prefer",
        quality_threshold=0.6,
        min_retrieval_results=1,
        min_retrieval_score=0.25,
        reranker_enabled=False,
        answer_template="generic",
    )
    base.update(over)
    return PublicGraphConfig(**base)


def _evidence(url: str = "https://ej.es/doc", title: str = "Doc") -> EvidenceItem:
    return EvidenceItem(
        source_id=str(uuid.uuid4()),
        content="contenido de la evidencia",
        source_url=url,
        title=title,
        language="es",
        score=0.9,
    )


def _graph(cfg, items, llm=None, deps=None, template=None) -> CoreGraph:
    retrieval = MagicMock()
    retrieval.retrieve = AsyncMock(
        return_value=RetrievalOutput(
            buckets=[RetrievalResult(items=items, debug={}, context_source_language="es")]
        )
    )
    merge = MagicMock()
    merge.merge = MagicMock(side_effect=lambda out: [i for b in out.buckets for i in b.items])
    if template is None:
        template = MagicMock()
        template.build_prompt_context = MagicMock(return_value="SYSTEM")
    language = MagicMock()
    language.detect = MagicMock(return_value="es")
    language.filter_items = MagicMock(side_effect=lambda lang, its: its)
    language.should_warn_translation = MagicMock(return_value=False)
    return CoreGraph(
        retrieval_strategy=retrieval,
        merge_strategy=merge,
        template_strategy=template,
        language_policy=language,
        cfg=cfg,
        deps=deps if deps is not None else GraphDeps(session=AsyncMock(), embedder=AsyncMock()),
        llm=llm,
    )


def _llm(text: str) -> MagicMock:
    llm = modelo_de_chat()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=text))
    return llm


# ───────────────────────────── Quality gate con mensaje ─────────────────────────────


@pytest.mark.asyncio
class TestQualityGateFallback:

    async def test_should_apply_quality_gate_fallback_on_low_evidence(self):
        """Sin evidencia, el gate no pasa y el grafo emite el mensaje de fallback."""
        graph = _graph(_cfg(quality_threshold=0.6), items=[], llm=_llm("no debería llamarse"))

        state = await graph.run("¿Cuántos días de permiso?", str(uuid.uuid4()))

        assert state["fallback_used"] is True
        assert state["answer"] == NO_CITATION_FALLBACK, (
            "el fallback debe emitir el mensaje, no dejar answer=None: el endpoint lo "
            "manda por SSE como respuesta normal"
        )

    async def test_should_report_quality_gate_as_fallback_reason(self):
        graph = _graph(_cfg(quality_threshold=0.9), items=[], llm=_llm("x"))

        state = await graph.run("pregunta", str(uuid.uuid4()))

        assert state["fallback_reason"] == "quality_gate"

    async def test_should_not_fall_back_when_evidence_passes_the_gate(self):
        graph = _graph(
            _cfg(quality_threshold=0.5),
            items=[_evidence()],
            llm=_llm("Respuesta con cita [Doc](https://ej.es/doc)."),
        )

        state = await graph.run("pregunta", str(uuid.uuid4()))

        assert state["fallback_used"] is False
        assert state["fallback_reason"] is None
        assert "Doc" in state["answer"]


# ───────────────────────────── Contrato de citas ─────────────────────────────


@pytest.mark.asyncio
class TestCitationContract:

    async def test_should_enforce_citation_contract_after_generation(self):
        """Si hubo evidencia y la respuesta no cita ninguna URL válida, se sustituye."""
        graph = _graph(
            _cfg(quality_threshold=0.1),
            items=[_evidence(url="https://ej.es/permisos")],
            llm=_llm("Tienes 22 días hábiles."),  # sin cita
        )

        state = await graph.run("¿Cuántos días?", str(uuid.uuid4()))

        assert state["answer"] == NO_CITATION_FALLBACK
        assert state["fallback_reason"] == "citation"

    async def test_should_keep_answer_that_cites_a_retrieved_url(self):
        graph = _graph(
            _cfg(quality_threshold=0.1),
            items=[_evidence(url="https://ej.es/permisos", title="Permisos")],
            llm=_llm("Tienes 22 días [Permisos](https://ej.es/permisos)."),
        )

        state = await graph.run("¿Cuántos días?", str(uuid.uuid4()))

        assert "22 días" in state["answer"]
        assert state["fallback_reason"] is None

    async def test_should_validate_citations_against_evidence_item_urls(self):
        """El validador consume EvidenceItem.source_url: Source ya no existe en este camino."""
        from server.app.modules.agents_hub.agent.citation_validator import (
            enforce_citation_contract,
        )

        items = [_evidence(url="https://ej.es/a", title="A")]

        assert enforce_citation_contract("sin citas", items, "RAG") == NO_CITATION_FALLBACK
        assert (
            enforce_citation_contract("texto [A](https://ej.es/a)", items, "RAG")
            == "texto [A](https://ej.es/a)"
        )


    async def test_should_not_report_fallback_when_only_the_anchor_was_degraded(self):
        """Degradar un ancla ajusta la respuesta; no es rendirse.

        `incumplio_citas` se calculaba comparando el texto validado con el original, así que
        cualquier ajuste contaba como sustitución. Con la degradación de anclas eso pasó de
        ser una equivalencia cierta a ser falsa, y arrastraba dos consecuencias: la respuesta
        se contabilizaba como fallback aunque el usuario la recibía entera, y —peor— se
        saltaba el aviso de vigencia, que sólo se añade cuando el contrato NO sustituyó.
        """
        graph = _graph(
            _cfg(quality_threshold=0.1),
            items=[_evidence(url="https://ej.es/permisos#art-1", title="Permisos")],
            llm=_llm("Tienes 22 días [Permisos, art. 1.3](https://ej.es/permisos#art-1.3)."),
        )

        state = await graph.run("¿Cuántos días?", str(uuid.uuid4()))

        assert "22 días" in state["answer"]
        assert "(https://ej.es/permisos)" in state["answer"]
        assert state["fallback_used"] is False
        assert state["fallback_reason"] is None


# ───────────────────────────── Loop agéntico portado ─────────────────────────────


@pytest.mark.asyncio
class TestAgenticLoop:

    async def test_should_run_agentic_loop_with_tools_in_selector_mode(self):
        """En MD_AGENT_SELECTOR el grafo hace bind_tools y ejecuta el loop tool-calling."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.agentic_loop import (
            AgenticLoop,
        )

        doc_id = str(uuid.uuid4())
        leido = {
            "title": "Reglamento",
            "url": "https://ej.es/reg",
            "markdown_content": "texto completo del reglamento",
        }
        reader = MagicMock()
        reader.read = AsyncMock(return_value=leido)
        reader.list_index = AsyncMock(return_value="1. Reglamento")

        primera = MagicMock(
            content="",
            tool_calls=[{"name": "read_document", "args": {"document_id": doc_id}, "id": "c1"}],
        )
        segunda = MagicMock(content="Según [Reglamento](https://ej.es/reg), sí.", tool_calls=[])
        con_tools = MagicMock()
        con_tools.ainvoke = AsyncMock(side_effect=[primera, segunda])
        llm = modelo_de_chat()
        llm.bind_tools = MagicMock(return_value=con_tools)

        loop = AgenticLoop(reader=reader, tools=["read_document"])
        items, texto = await loop.run(llm=llm, system="SYSTEM", query="¿sí o no?")

        llm.bind_tools.assert_called_once()
        assert "Reglamento" in texto
        assert [i.source_id for i in items] == [doc_id], (
            "solo los documentos realmente leídos entran como evidencia"
        )
        assert items[0].source_url == "https://ej.es/reg"

    async def test_should_stop_the_agentic_loop_at_the_iteration_limit(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.agentic_loop import (
            AgenticLoop,
        )

        siempre_tool = MagicMock(
            content="",
            tool_calls=[{"name": "list_documents", "args": {}, "id": "c"}],
        )
        con_tools = MagicMock()
        con_tools.ainvoke = AsyncMock(return_value=siempre_tool)
        llm = modelo_de_chat()
        llm.bind_tools = MagicMock(return_value=con_tools)
        reader = MagicMock()
        reader.list_index = AsyncMock(return_value="índice")
        reader.read = AsyncMock(return_value=None)

        loop = AgenticLoop(reader=reader, tools=["list_documents"], max_iterations=3)
        items, texto = await loop.run(llm=llm, system="S", query="q")

        assert con_tools.ainvoke.await_count == 3
        assert items == []


# ───────────── Selector: el índice es un punto de extensión, no "todos los documentos" ─────────────


@pytest.mark.asyncio
class TestSelectorIndexIsAnExtensionPoint:

    async def test_should_delegate_the_index_to_an_injectable_provider(self):
        """VIS.2 sustituirá el índice de documentos por el de submaterias. El pipeline no
        puede cementar de dónde sale el índice ni asumir que es «todo el corpus»."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.md_agent_selector_pipeline import (
            MdAgentSelectorPipeline,
        )

        provider = MagicMock()
        provider.build_index = AsyncMock(
            return_value=[
                EvidenceItem(source_id="s1", content="Submateria: permisos", title="permisos")
            ]
        )
        pipeline = MdAgentSelectorPipeline(index_provider=provider)

        result = await pipeline.run(
            "q", str(uuid.uuid4()), _cfg(retrieval_mode="MD_AGENT_SELECTOR"),
            GraphDeps(session=AsyncMock(), embedder=AsyncMock()),
        )

        provider.build_index.assert_awaited_once()
        assert [i.content for i in result.items] == ["Submateria: permisos"]

    async def test_should_not_put_whole_documents_in_the_default_index(self):
        """El índice por defecto lleva título/id, no el markdown completo: volcar el corpus
        entero en el prompt es justo lo que el modo selector viene a evitar."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.md_agent_selector_pipeline import (
            DocumentIndexProvider,
        )

        doc = MagicMock()
        doc.id = uuid.uuid4()
        doc.title = "Reglamento del Claustre"
        doc.canonical_url = "https://ej.es/claustre"
        doc.language = "ca"
        doc.markdown_content = "X" * 50_000

        session = AsyncMock()
        scalars = MagicMock()
        scalars.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[doc])))
        session.execute = AsyncMock(return_value=scalars)

        items = await DocumentIndexProvider().build_index(
            str(uuid.uuid4()), GraphDeps(session=session, embedder=AsyncMock())
        )

        assert len(items) == 1
        assert "Reglamento del Claustre" in items[0].content
        assert len(items[0].content) < 1_000, (
            "el índice no debe arrastrar el texto completo del documento"
        )


# ───────────────────────────── System prompt unificado ─────────────────────────────


class TestTemplateStrategyOwnsTheSystemPrompt:

    def test_should_build_system_prompt_with_base_rules_and_sources(self):
        """Las REGLAS DE CITA y el bloque de fuentes de agent/prompts.py se integran en la
        TemplateStrategy: una sola fuente del system prompt."""
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            GenericAnswerTemplateStrategy,
        )

        strategy = GenericAnswerTemplateStrategy(base_system_prompt="Eres el asistente de la UJI.")
        prompt = strategy.build_prompt_context(
            [_evidence(url="https://ej.es/a", title="Norma A")], "ca", "quina normativa?"
        )

        assert "Eres el asistente de la UJI." in prompt
        assert "REGLAS DE CITA" in prompt
        assert "Norma A" in prompt
        assert "https://ej.es/a" in prompt

    def test_should_instruct_tool_use_in_selector_mode(self):
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            GenericAnswerTemplateStrategy,
        )

        strategy = GenericAnswerTemplateStrategy(
            base_system_prompt="Base.", retrieval_mode="MD_AGENT_SELECTOR"
        )
        prompt = strategy.build_prompt_context([], None, "q")

        assert "read_document" in prompt
