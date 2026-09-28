"""Tests para el módulo charts (9R.5.7).

Cubre:
  - DeterministicChartService (5 tipos de gráfico + agregación)
  - ChartBlockConfig / ChartBlock (contratos)
  - render_chart_from_script (sandbox subprocess)
  - ChartFactory._extract_code (extracción de bloques markdown)
  - ChartHandler.to_manifest
"""
from __future__ import annotations

import pytest
import pandas as pd

from server.app.modules.redaccion.services.charts.chart_configuration import ChartConfiguration
from server.app.modules.redaccion.services.charts.deterministic_chart_service import DeterministicChartService
from server.app.modules.redaccion.services.charts.chart_renderer import render_chart_from_script, ChartRenderError
from server.app.modules.redaccion.services.charts.chart_factory import ChartFactory
from server.app.modules.redaccion.contracts.blocks import ChartBlock, ChartBlockConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "category": ["A", "B", "C"],
        "value": [10, 20, 30],
        "group": ["X", "X", "Y"],
    })


def _numeric_df() -> pd.DataFrame:
    return pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [4.0, 3.0, 2.0, 1.0]})


# ---------------------------------------------------------------------------
# DeterministicChartService
# ---------------------------------------------------------------------------

class TestDeterministicChartService:

    def test_bar_chart_returns_png_bytes(self):
        df = _sample_df()
        config = ChartConfiguration(chart_type="bar", x_column="category", y_column="value")
        svc = DeterministicChartService()
        result = svc.render(df, config)
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"  # PNG magic bytes

    def test_line_chart_returns_png_bytes(self):
        df = _numeric_df()
        config = ChartConfiguration(chart_type="line", x_column="x", y_column="y")
        svc = DeterministicChartService()
        result = svc.render(df, config)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_pie_chart_returns_png_bytes(self):
        df = _sample_df()
        config = ChartConfiguration(
            chart_type="pie", label_column="category", value_column="value"
        )
        svc = DeterministicChartService()
        result = svc.render(df, config)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_scatter_chart_returns_png_bytes(self):
        df = _numeric_df()
        config = ChartConfiguration(chart_type="scatter", x_column="x", y_column="y")
        svc = DeterministicChartService()
        result = svc.render(df, config)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_histogram_returns_png_bytes(self):
        df = _numeric_df()
        config = ChartConfiguration(chart_type="histogram", x_column="x")
        svc = DeterministicChartService()
        result = svc.render(df, config)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_aggregation_sum_reduces_rows(self):
        df = pd.DataFrame({
            "category": ["A", "A", "B"],
            "value": [5, 10, 20],
        })
        config = ChartConfiguration(
            chart_type="bar",
            x_column="category",
            y_column="value",
            aggregation="sum",
        )
        svc = DeterministicChartService()
        aggregated = svc._prepare_data(df, config)
        assert len(aggregated) == 2
        assert aggregated[aggregated["category"] == "A"]["value"].values[0] == 15


# ---------------------------------------------------------------------------
# ChartBlockConfig / ChartBlock contracts
# ---------------------------------------------------------------------------

class TestChartContracts:

    def test_chart_block_config_defaults(self):
        cfg = ChartBlockConfig()
        assert cfg.mode == "deterministic"
        assert cfg.chart_type == "bar"
        assert cfg.nl_prompt is None

    def test_chart_block_includes_config_field(self):
        block = ChartBlock(id="ch1", title="Mi gráfico", data_block_ref="data1")
        assert block.config is None  # optional, defaults to None

    def test_chart_block_with_config(self):
        cfg = ChartBlockConfig(mode="ai", nl_prompt="Muestra ventas por mes")
        block = ChartBlock(id="ch1", title="Mi gráfico", data_block_ref="data1", config=cfg)
        assert block.config.mode == "ai"
        assert block.config.nl_prompt == "Muestra ventas por mes"


# ---------------------------------------------------------------------------
# render_chart_from_script
# ---------------------------------------------------------------------------

class TestRenderChartFromScript:

    async def test_valid_script_returns_bytes(self):
        df = _numeric_df()
        code = "fig, ax = plt.subplots()\nax.plot(df['x'], df['y'])"
        # `timeout` explícito y generoso: el default de producción son 30 s, y este test
        # levanta un subprocess con matplotlib que bajo la carga de la suite completa en
        # Windows no llega (visto al cerrar RAG.3; en aislamiento tarda ~10 s). El default de
        # producción NO se toca por un problema del entorno de test, y lo que este test
        # comprueba es que un script válido devuelve un PNG, no cuánto tarda.
        result = await render_chart_from_script(code, df, timeout=180)
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"

    async def test_dangerous_code_raises_chart_render_error(self):
        df = _numeric_df()
        code = "import os\nos.system('echo hacked')"
        with pytest.raises(ChartRenderError, match="Auditoría"):
            await render_chart_from_script(code, df)

    async def test_syntax_error_raises_chart_render_error(self):
        df = _numeric_df()
        code = "this is not python !!!"
        with pytest.raises(ChartRenderError):
            await render_chart_from_script(code, df)


# ---------------------------------------------------------------------------
# ChartFactory._extract_code
# ---------------------------------------------------------------------------

class TestChartFactoryExtractCode:

    def test_extracts_from_markdown_fence(self):
        raw = "```python\nfig, ax = plt.subplots()\n```"
        code = ChartFactory._extract_code(raw)
        assert code == "fig, ax = plt.subplots()"

    def test_returns_raw_when_no_fence(self):
        raw = "fig, ax = plt.subplots()"
        code = ChartFactory._extract_code(raw)
        assert code == raw.strip()
