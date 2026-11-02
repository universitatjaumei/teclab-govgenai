"""Tests del CoreGraph — 9B.7 (RED/GREEN).

Verifican que:
- El CoreGraph compila sin error con cualquier conjunto de estrategias mock.
- Se toma el camino fallback cuando la calidad de retrieval es baja.
- El grafo produce una respuesta con cada retrieval_mode usando estrategias mock.
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
    RetrievalResult,
)
from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
    GraphDeps,
)

_CFG = PublicGraphConfig(
    profile="PUBLIC_KB_RICH",
    retrieval_mode="RAG",
    language_mode="prefer",
    quality_threshold=0.6,
    min_retrieval_results=2,
    min_retrieval_score=0.25,
    reranker_enabled=False,
    answer_template="generic",
)


def _mock_strategies(merge_return=None, answer="respuesta"):
    mock_retrieval = MagicMock()
    mock_retrieval.retrieve = AsyncMock(
        return_value=RetrievalOutput(buckets=[])
    )
    mock_merge = MagicMock()
    mock_merge.merge = MagicMock(return_value=merge_return if merge_return is not None else [])
    mock_template = MagicMock()
    mock_template.build_prompt_context = MagicMock(return_value=answer)
    mock_language = MagicMock()
    mock_language.detect = MagicMock(return_value="es")
    mock_language.filter_items = MagicMock(side_effect=lambda lang, items: items)
    mock_language.should_warn_translation = MagicMock(return_value=False)
    return mock_retrieval, mock_merge, mock_template, mock_language


@pytest.mark.asyncio
class TestCoreGraph:

    async def test_core_graph_compiles_with_mock_strategies(self):
        """CoreGraph debe compilar sin errores con cualquier conjunto de estrategias mock."""
        retrieval, merge, template, language = _mock_strategies()
        deps = GraphDeps(session=AsyncMock(), embedder=AsyncMock())

        graph = CoreGraph(
            retrieval_strategy=retrieval,
            merge_strategy=merge,
            template_strategy=template,
            language_policy=language,
            cfg=_CFG,
            deps=deps,
        )
        compiled = graph.compile()
        assert compiled is not None

    async def test_core_graph_branches_to_fallback_when_quality_low(self):
        """Cuando merge devuelve 0 items, quality_score=0 < threshold → fallback."""
        retrieval, merge, template, language = _mock_strategies(merge_return=[])
        deps = GraphDeps(session=AsyncMock(), embedder=AsyncMock())

        graph = CoreGraph(
            retrieval_strategy=retrieval,
            merge_strategy=merge,
            template_strategy=template,
            language_policy=language,
            cfg=_CFG,
            deps=deps,
        )
        result = await graph.run("¿qué es esto?", str(uuid.uuid4()))

        assert result["fallback_used"] is True
        # Reapuntado en RAG.2: el fallback dejó de devolver answer=None y ahora emite el
        # mensaje, que el endpoint manda por SSE como respuesta normal.
        from server.app.modules.agents_hub.agent.citation_validator import (
            NO_CITATION_FALLBACK,
        )

        assert result["answer"] == NO_CITATION_FALLBACK
        assert result["fallback_reason"] == "quality_gate"

    async def test_should_use_the_configured_no_answer_message(self):
        """UX.4: «no lo sé» a secas deja a quien pregunta donde estaba.

        A quién hay que remitirlo depende del asistente —Infocampus atiende al público, no
        al personal de gestión—, así que es configuración del chatbot y no una constante.
        """
        from dataclasses import replace

        A_INFOCAMPUS = (
            "No he trobat fonament suficient. Contacta amb Infocampus: "
            "https://www.uji.es/serveis/infocampus/"
        )
        retrieval, merge, template, language = _mock_strategies(merge_return=[])
        deps = GraphDeps(session=AsyncMock(), embedder=AsyncMock())

        graph = CoreGraph(
            retrieval_strategy=retrieval,
            merge_strategy=merge,
            template_strategy=template,
            language_policy=language,
            cfg=replace(_CFG, no_answer_message=A_INFOCAMPUS),
            deps=deps,
        )
        result = await graph.run("¿qué es esto?", str(uuid.uuid4()))

        assert result["answer"] == A_INFOCAMPUS
        assert result["fallback_used"] is True

    async def test_should_keep_the_generic_text_when_no_message_is_configured(self):
        """Sin configurar, el texto de siempre: no se obliga a nadie a rellenar el campo."""
        from server.app.modules.agents_hub.agent.citation_validator import (
            NO_CITATION_FALLBACK,
        )

        retrieval, merge, template, language = _mock_strategies(merge_return=[])
        graph = CoreGraph(
            retrieval_strategy=retrieval,
            merge_strategy=merge,
            template_strategy=template,
            language_policy=language,
            cfg=_CFG,
            deps=GraphDeps(session=AsyncMock(), embedder=AsyncMock()),
        )

        result = await graph.run("¿qué es esto?", str(uuid.uuid4()))

        assert result["answer"] == NO_CITATION_FALLBACK

    async def test_core_graph_runs_with_each_retrieval_mode_using_generic_profile(self):
        """Con 2 items de score 0.9, el grafo produce una respuesta en cada retrieval_mode."""
        for mode in ("RAG", "MD_LONG_CONTEXT", "MD_AGENT_SELECTOR"):
            item = EvidenceItem(source_id="doc1", content="contenido de prueba", score=0.9)
            items = [item, item]

            mock_result = RetrievalResult(items=items, debug={"pipeline_mode": mode})
            mock_output = RetrievalOutput(buckets=[mock_result])

            mock_retrieval = MagicMock()
            mock_retrieval.retrieve = AsyncMock(return_value=mock_output)
            mock_merge = MagicMock()
            mock_merge.merge = MagicMock(return_value=items)
            mock_template = MagicMock()
            mock_template.build_prompt_context = MagicMock(return_value=f"contexto_{mode}")
            mock_language = MagicMock()
            mock_language.detect = MagicMock(return_value="es")
            mock_language.filter_items = MagicMock(side_effect=lambda lang, items: items)
            mock_language.should_warn_translation = MagicMock(return_value=False)

            cfg = PublicGraphConfig(
                profile="PUBLIC_KB_RICH",
                retrieval_mode=mode,
                language_mode="prefer",
                quality_threshold=0.6,
                min_retrieval_results=2,
                min_retrieval_score=0.25,
                reranker_enabled=False,
                answer_template="generic",
            )
            deps = GraphDeps(session=AsyncMock(), embedder=AsyncMock())

            graph = CoreGraph(
                retrieval_strategy=mock_retrieval,
                merge_strategy=mock_merge,
                template_strategy=mock_template,
                language_policy=mock_language,
                cfg=cfg,
                deps=deps,
            )
            result = await graph.run("¿qué es X?", str(uuid.uuid4()))

            assert result["fallback_used"] is False, f"Fallback no esperado en modo {mode}"
            # #364: el grafo añade la fecha de hoy al final del contexto de cualquier plantilla.
            assert result["answer"].startswith(f"contexto_{mode}\n\nFECHA DE HOY:"), (
                f"Respuesta incorrecta en modo {mode}"
            )
