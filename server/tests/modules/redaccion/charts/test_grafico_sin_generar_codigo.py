"""PRO.8 — pedir un gráfico usual no debe costar un script generado.

Este es el ahorro del prompt, y es el mismo patrón que PRO.4 aplicó al ETL: **JSON primero,
script como último recurso**. Antes de PRO.8, `translate_nl_to_config(target_kind="chart_config")`
no devolvía ninguna configuración: llamaba a `ChartFactory.generate_script()`, así que «barras
horizontales del gasto por capítulo» costaba modelo + auditoría + sandbox para lo que es
`chart_type="barh"`.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from server.app.modules.redaccion.services.charts.chart_factory import ChartFactory
from server.app.modules.redaccion.services.copilot.copilot_service import CopilotTranslator


class _LLMQueDevuelve:
    """Un modelo que responde lo que se le diga, y que cuenta cuántas veces se le ha llamado."""

    def __init__(self, *respuestas: str) -> None:
        self._respuestas = list(respuestas)
        self.llamadas: list[list[dict[str, str]]] = []

    async def ainvoke(self, messages: list[dict[str, str]]) -> Any:
        self.llamadas.append(messages)
        texto = self._respuestas.pop(0) if self._respuestas else self._respuestas_agotadas()
        return type("R", (), {"content": texto})()

    @staticmethod
    def _respuestas_agotadas() -> str:
        raise AssertionError("el modelo se ha llamado más veces de las previstas")


_ESQUEMA = {"columns": ["capitulo", "importe"], "dtypes": {"capitulo": "object", "importe": "float64"}}


@pytest.mark.asyncio
async def test_una_peticion_que_cabe_en_el_catalogo_devuelve_configuracion() -> None:
    llm = _LLMQueDevuelve(
        json.dumps(
            {
                "mode": "configuration",
                "configuration": {
                    "chart_type": "barh",
                    "x_column": "capitulo",
                    "y_column": "importe",
                    "aggregation": "sum",
                    "sort": "desc",
                    "title": "Gasto por capítulo",
                    "show_values": True,
                },
            }
        )
    )
    plan = await ChartFactory(llm, "modelo-de-prueba").generate_chart_from_nl(
        nl_prompt="barras horizontales del gasto por capítulo, de mayor a menor, con las cifras",
        schema=_ESQUEMA,
    )

    assert plan.mode == "configuration"
    assert plan.script_code is None, "una petición del catálogo no debe generar código"
    assert plan.configuration is not None
    assert plan.configuration.chart_type == "barh"
    assert plan.configuration.sort == "desc"
    assert plan.configuration.show_values is True
    assert len(llm.llamadas) == 1, "una sola llamada: sin reintentos ni fallback"


@pytest.mark.asyncio
async def test_el_prompt_lleva_el_catalogo_generado_del_contrato() -> None:
    """Un catálogo escrito a mano en el prompt divergiría del renderizador en el primer cambio."""
    llm = _LLMQueDevuelve(
        json.dumps({"mode": "configuration", "configuration": {"chart_type": "bar"}})
    )
    await ChartFactory(llm, "m").generate_chart_from_nl(nl_prompt="algo", schema=_ESQUEMA)

    sistema = llm.llamadas[0][0]["content"]
    for tipo in ("heatmap", "boxplot", "donut", "bubble", "bar_stacked"):
        assert tipo in sistema, f"el modelo no sabe que existe {tipo}"
    assert "show_values" in sistema
    assert "capitulo" in llm.llamadas[0][1]["content"]


@pytest.mark.asyncio
async def test_lo_que_no_cabe_en_el_catalogo_baja_al_script_auditado() -> None:
    """El fallback sigue existiendo: lo que el catálogo no cubre se programa, y se audita.

    Y baja **a la primera**: una `configuration` vacía es la señal deliberada de que la petición
    no encaja, así que reintentarla dos veces más sería quemar dos llamadas para volver a oír lo
    mismo. Sólo se reintenta lo que el modelo puede corregir.
    """
    llm = _LLMQueDevuelve(
        json.dumps({"mode": "configuration", "configuration": {}}),  # vacío = no encaja
        "import pandas as pd\nax = df.plot()\n",
    )
    plan = await ChartFactory(llm, "m").generate_chart_from_nl(
        nl_prompt="un diagrama de Sankey del flujo entre programas", schema=_ESQUEMA
    )

    assert plan.mode == "script"
    assert plan.script_code is not None
    assert plan.script_audit is not None, "un script sin auditar no sale de aquí"
    assert len(llm.llamadas) == 2, "dos llamadas: la que dice que no encaja y la del script"


@pytest.mark.asyncio
async def test_un_json_invalido_se_reintenta_con_el_error_delante() -> None:
    llm = _LLMQueDevuelve(
        "esto no es JSON",
        json.dumps(
            {"mode": "configuration", "configuration": {"chart_type": "line", "x_column": "capitulo"}}
        ),
    )
    plan = await ChartFactory(llm, "m").generate_chart_from_nl(nl_prompt="una línea", schema=_ESQUEMA)

    assert plan.mode == "configuration"
    assert plan.refinement_iterations == 1
    assert "INTENTO ANTERIOR" in llm.llamadas[1][1]["content"].upper()


@pytest.mark.asyncio
async def test_un_tipo_inventado_no_pasa_la_validacion() -> None:
    """El modelo no puede ampliar el catálogo desde su respuesta."""
    llm = _LLMQueDevuelve(
        json.dumps({"mode": "configuration", "configuration": {"chart_type": "sankey"}}),
        json.dumps({"mode": "configuration", "configuration": {"chart_type": "bar"}}),
    )
    plan = await ChartFactory(llm, "m").generate_chart_from_nl(nl_prompt="x", schema=_ESQUEMA)

    assert plan.mode == "configuration"
    assert plan.configuration is not None
    assert plan.configuration.chart_type == "bar"


@pytest.mark.asyncio
async def test_el_copiloto_devuelve_la_configuracion_y_no_el_script() -> None:
    """La puerta por la que se pide un gráfico desde el copiloto, cerrada de punta a punta."""
    llm = _LLMQueDevuelve(
        json.dumps(
            {
                "mode": "configuration",
                "configuration": {"chart_type": "pie", "label_column": "capitulo", "value_column": "importe"},
            }
        )
    )
    servicio = CopilotTranslator(chart_factory=ChartFactory(llm, "m"))
    respuesta = await servicio.translate_nl_to_config(
        instruction="una tarta del reparto por capítulo",
        target_kind="chart_config",
        sample_schema=_ESQUEMA,
    )

    assert respuesta.kind == "chart_config"
    assert respuesta.payload["mode"] == "configuration"
    assert respuesta.payload["configuration"]["chart_type"] == "pie"
    assert respuesta.payload.get("script_code") is None
