"""Tests del Copilot (1C.0.bis): RAG sobre docs + NL→config para chart/etl/script."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.redaccion.services.charts.chart_factory import ChartFactory
from server.app.modules.redaccion.services.copilot import (
    CopilotService,
    CopilotTranslator,
    DocsRetriever,
    IndexedChunk,
)
from server.tests.dobles import modelo_de_chat

# ──────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────


class FakeEmbeddingService:
    """Embeddings 4-dim deterministas basados en presencia de keywords.

    Permite control sobre el ranking de retrieval sin cargar BGE-M3.
    """

    KEYWORDS = ["bloque", "widget", "redaccion", "chatbot"]

    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        return [1.0 if kw in lowered else 0.0 for kw in self.KEYWORDS]


def _make_chunk(text: str, source_path: str, module: str, chunk_idx: int = 0) -> IndexedChunk:
    return IndexedChunk(
        text=text,
        source_path=source_path,
        module=module,  # type: ignore[arg-type]
        chunk_idx=chunk_idx,
        embedding=[0.0, 0.0, 0.0, 0.0],
    )


# ──────────────────────────────────────────────────────────────────
# Test 1 — should_index_docs_and_retrieve_by_module
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_index_docs_and_retrieve_by_module(tmp_path: Path) -> None:
    redaccion_doc = tmp_path / "REDACCION_CONTRACT_FIRST.md"
    redaccion_doc.write_text(
        "# Redacción\n\nUn bloque IA pertenece al sistema de redacción.\n",
        encoding="utf-8",
    )
    chatbots_subdir = tmp_path / "chatbots-publicos"
    chatbots_subdir.mkdir()
    (chatbots_subdir / "README.md").write_text(
        "# Chatbots públicos\n\nEl widget del chatbot se embebe en sitios web.\n",
        encoding="utf-8",
    )

    retriever = DocsRetriever(
        embedding_service=FakeEmbeddingService(),
        docs_dir=tmp_path,
    )
    await retriever.index()

    assert len(retriever.chunks) >= 2

    redaccion_hits = await retriever.retrieve("bloque", module="redaccion", top_k=4)
    assert redaccion_hits, "Esperábamos al menos un chunk de redacción"
    assert all(c.module == "redaccion" for c in redaccion_hits)
    assert "bloque" in redaccion_hits[0].text.lower()

    chatbots_hits = await retriever.retrieve("widget", module="chatbots", top_k=4)
    assert chatbots_hits, "Esperábamos al menos un chunk de chatbots"
    assert all(c.module == "chatbots" for c in chatbots_hits)
    assert "widget" in chatbots_hits[0].text.lower()


# ──────────────────────────────────────────────────────────────────
# Test 2 — should_answer_question_with_source_refs
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_answer_question_with_source_refs() -> None:
    mock_llm = modelo_de_chat()
    mock_llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="Para crear un bloque ve a la sección X.")
    )

    fake_retriever = MagicMock(spec=DocsRetriever)
    fake_retriever.retrieve = AsyncMock(
        return_value=[
            _make_chunk(
                text="Sección X: crear un bloque IA en redacción.",
                source_path="docs/REDACCION_CONTRACT_FIRST.md",
                module="redaccion",
                chunk_idx=2,
            )
        ]
    )

    service = CopilotService(llm=mock_llm, retriever=fake_retriever)
    answer = await service.answer("¿Cómo creo un bloque?", module="redaccion")

    assert answer.answer == "Para crear un bloque ve a la sección X."
    assert len(answer.source_refs) == 1
    ref = answer.source_refs[0]
    assert ref.path == "docs/REDACCION_CONTRACT_FIRST.md"
    assert ref.chunk_idx == 2
    assert ref.module == "redaccion"
    assert "bloque" in ref.excerpt.lower()
    fake_retriever.retrieve.assert_awaited_once()


# ──────────────────────────────────────────────────────────────────
# Test 3 — should_translate_nl_to_chart_config_when_target_is_chart
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_translate_nl_to_chart_config_when_target_is_chart() -> None:
    """PRO.8 — esto exigía `generate_script`, o sea que el `target_kind` mentía: se pedía una
    configuración y se devolvía código, con su auditoría y su sandbox detrás.

    El mock lleva `spec=ChartFactory` a propósito: sin él, un `MagicMock` responde a cualquier
    método y este test seguiría verde con una factoría que ya no tuviera el que llama.
    """
    chart_result = MagicMock()
    chart_result.model_dump = MagicMock(
        return_value={"mode": "configuration", "configuration": {"chart_type": "bar"}}
    )
    mock_chart_factory = MagicMock(spec=ChartFactory)
    mock_chart_factory.generate_chart_from_nl = AsyncMock(return_value=chart_result)

    service = CopilotTranslator(
        modelo=modelo_de_chat(),
        chart_factory=mock_chart_factory,
    )

    response = await service.translate_nl_to_config(
        instruction="Gráfico de barras del total por región",
        target_kind="chart_config",
        sample_schema={"columns": ["region", "total"]},
    )

    assert response.kind == "chart_config"
    assert response.payload == {"mode": "configuration", "configuration": {"chart_type": "bar"}}
    mock_chart_factory.generate_chart_from_nl.assert_awaited_once()
    call_kwargs = mock_chart_factory.generate_chart_from_nl.await_args.kwargs
    assert call_kwargs["nl_prompt"] == "Gráfico de barras del total por región"
    assert call_kwargs["schema"] == {"columns": ["region", "total"]}


# ──────────────────────────────────────────────────────────────────
# Test 4 — should_translate_nl_to_etl_operations_when_target_is_data_transform
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_translate_nl_to_etl_operations_when_target_is_data_transform() -> None:
    etl_result = MagicMock()
    etl_result.model_dump = MagicMock(
        return_value={
            "mode": "operations",
            "operations": [
                {"op": "groupby", "cols": ["mes"], "agg_dict": {"importe": "sum"}}
            ],
            "model_used": "gpt-4o",
        }
    )
    mock_etl_factory = MagicMock()
    mock_etl_factory.generate_operations_from_nl = AsyncMock(return_value=etl_result)

    service = CopilotTranslator(
        modelo=modelo_de_chat(),
        etl_factory=mock_etl_factory,
    )

    response = await service.translate_nl_to_config(
        instruction="Agrupa por mes y suma el importe",
        target_kind="etl_ops",
        sample_schema={"columns": ["mes", "importe"]},
    )

    assert response.kind == "etl_ops"
    assert response.payload["mode"] == "operations"
    assert response.payload["operations"][0]["op"] == "groupby"
    mock_etl_factory.generate_operations_from_nl.assert_awaited_once()


# ──────────────────────────────────────────────────────────────────
# Test 5 — should_translate_nl_to_script_proposal_when_target_is_admin_script
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_translate_nl_to_script_proposal_when_target_is_admin_script() -> None:
    proposal_result = MagicMock()
    proposal_result.model_dump = MagicMock(
        return_value={
            "code": "def extract(df): return df.head()",
            "audit_result": {"is_safe": True, "reason": "ok"},
            "model_used": "gpt-4o",
        }
    )
    mock_script_proposal = MagicMock()
    mock_script_proposal.propose = AsyncMock(return_value=proposal_result)

    service = CopilotTranslator(
        modelo=modelo_de_chat(),
        script_proposal=mock_script_proposal,
    )

    response = await service.translate_nl_to_config(
        instruction="Devuelve las primeras 5 filas del DataFrame",
        target_kind="script_proposal",
        sample_schema={"columns": ["a", "b"]},
    )

    assert response.kind == "script_proposal"
    assert "def extract" in response.payload["code"]
    assert response.payload["audit_result"]["is_safe"] is True
    mock_script_proposal.propose.assert_awaited_once()


# ──────────────────────────────────────────────────────────────────
# Test extra (defensa): translate_nl_to_config rechaza target_kind sin factory
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_translate_raises_when_factory_missing_for_target_kind() -> None:
    service = CopilotTranslator(modelo=modelo_de_chat())

    with pytest.raises(ValueError, match="ChartFactory"):
        await service.translate_nl_to_config(
            instruction="bar chart", target_kind="chart_config"
        )
