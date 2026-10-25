"""Tests del ETLFactory (NL→operations + refinamiento + fallback script) — 9R.5.8 (RED → GREEN)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from server.app.modules.redaccion.services.transformation.etl_factory import (
    ETLFactory,
    ETLPlan,
    MAX_REFINEMENT_ITERATIONS,
)
from server.app.modules.redaccion.services.transformation.operations import (
    AggregateOp,
    FilterOp,
)


def _schema_of(df: pd.DataFrame) -> dict:
    return {
        "columns": list(df.columns),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
    }


def _sales_df() -> pd.DataFrame:
    return pd.DataFrame({
        "region":  ["N", "S", "E"],
        "units":   [10, 20, 30],
        "revenue": [100, 200, 300],
    })


def _llm_response(content: str) -> MagicMock:
    """Construye una respuesta tipo LangChain con .content."""
    resp = MagicMock()
    resp.content = content
    return resp


def _ainvoke_mock(*responses: str) -> AsyncMock:
    return AsyncMock(side_effect=[_llm_response(c) for c in responses])


class TestETLFactoryOperations:

    @pytest.mark.asyncio
    async def test_etl_factory_generates_operations_from_nl(self):
        ops_json = json.dumps({
            "mode": "operations",
            "operations": [
                {"op": "filter", "col": "units", "comparator": ">", "value": 15},
                {"op": "aggregate", "col": "revenue", "function": "sum"},
            ],
        })
        llm = MagicMock()
        llm.ainvoke = _ainvoke_mock(ops_json)

        factory = ETLFactory(llm, model_name="claude-test")
        plan = await factory.generate_operations_from_nl(
            "Filtrar unidades > 15 y sumar ingresos", _schema_of(_sales_df()),
        )

        assert isinstance(plan, ETLPlan)
        assert plan.mode == "operations"
        assert len(plan.operations) == 2
        assert isinstance(plan.operations[0], FilterOp)
        assert isinstance(plan.operations[1], AggregateOp)
        assert plan.model_used == "claude-test"
        assert plan.refinement_iterations == 0

    @pytest.mark.asyncio
    async def test_etl_factory_refines_when_validation_fails(self):
        # First reply: invalid operation (unknown comparator). Second reply: valid.
        invalid_payload = json.dumps({
            "mode": "operations",
            "operations": [{"op": "filter", "col": "units", "comparator": "BOGUS", "value": 5}],
        })
        valid_payload = json.dumps({
            "mode": "operations",
            "operations": [{"op": "filter", "col": "units", "comparator": ">", "value": 5}],
        })

        llm = MagicMock()
        llm.ainvoke = _ainvoke_mock(invalid_payload, valid_payload)

        factory = ETLFactory(llm, model_name="m")
        plan = await factory.generate_operations_from_nl("filtrar", _schema_of(_sales_df()))

        assert plan.mode == "operations"
        assert plan.refinement_iterations == 1
        assert llm.ainvoke.await_count == 2

    @pytest.mark.asyncio
    async def test_etl_factory_falls_back_to_script_when_operations_unsupported(self):
        # All retries produce invalid plans. Factory then asks LLM for a Python script.
        invalid_payload = json.dumps({
            "mode": "operations",
            "operations": [{"op": "filter", "col": "units", "comparator": "BOGUS", "value": 1}],
        })
        script_payload = (
            "```python\n"
            "def transform(df):\n"
            "    return df[df['units'] > 15]\n"
            "```"
        )
        llm = MagicMock()
        # MAX_REFINEMENT_ITERATIONS attempts at operations + 1 fallback script.
        llm.ainvoke = _ainvoke_mock(
            *([invalid_payload] * MAX_REFINEMENT_ITERATIONS),
            script_payload,
        )

        factory = ETLFactory(llm, model_name="m")
        plan = await factory.generate_operations_from_nl(
            "imposible de mapear a operaciones", _schema_of(_sales_df()),
        )

        assert plan.mode == "script"
        assert plan.script_code is not None
        assert "def transform" in plan.script_code
        assert plan.script_audit is not None
        assert plan.script_audit.approved is True
        assert plan.refinement_iterations == MAX_REFINEMENT_ITERATIONS

    @pytest.mark.asyncio
    async def test_etl_factory_rejects_unsafe_fallback_script(self):
        invalid_payload = json.dumps({
            "mode": "operations",
            "operations": [{"op": "filter", "col": "units", "comparator": "BOGUS"}],
        })
        unsafe_script = (
            "```python\n"
            "import os\n"
            "def transform(df):\n"
            "    os.system('rm -rf /')\n"
            "    return df\n"
            "```"
        )
        llm = MagicMock()
        llm.ainvoke = _ainvoke_mock(
            *([invalid_payload] * MAX_REFINEMENT_ITERATIONS),
            unsafe_script,
        )

        factory = ETLFactory(llm, model_name="m")
        plan = await factory.generate_operations_from_nl("x", _schema_of(_sales_df()))

        assert plan.mode == "script"
        assert plan.script_audit is not None
        assert plan.script_audit.approved is False


# ──────────────────────────────────────────────────────────────────
# PRO.9 — «no encaja» es una respuesta, no un fallo que reintentar
# ──────────────────────────────────────────────────────────────────


class _LLMContado:
    def __init__(self, *respuestas: str) -> None:
        self._respuestas = list(respuestas)
        self.llamadas = 0

    async def ainvoke(self, messages):
        self.llamadas += 1
        if not self._respuestas:
            raise AssertionError("el modelo se ha llamado más veces de las previstas")
        return type("R", (), {"content": self._respuestas.pop(0)})()


@pytest.mark.asyncio
async def test_una_lista_vacia_baja_al_script_a_la_primera() -> None:
    """El prompt le dice al modelo que devuelva `operations: []` cuando la petición no encaja.

    Hasta PRO.9 esa respuesta deliberada se trataba como un plan inválido y se reintentaba dos
    veces más: tres llamadas para volver a oír lo mismo, y sólo entonces el script. Se reintenta
    lo que el modelo puede corregir; no lo que ha decidido.
    """
    llm = _LLMContado(
        json.dumps({"mode": "operations", "operations": []}),
        "def transform(df):\n    return df\n",
    )
    plan = await ETLFactory(llm, "m").generate_operations_from_nl(
        nl_prompt="haz un análisis de series temporales con ARIMA", schema={"columns": ["a"]}
    )

    assert plan.mode == "script"
    assert llm.llamadas == 2


@pytest.mark.asyncio
async def test_un_json_roto_si_se_reintenta() -> None:
    llm = _LLMContado(
        "esto no es JSON",
        json.dumps({"mode": "operations", "operations": [{"op": "sort_rows", "by": ["a"]}]}),
    )
    plan = await ETLFactory(llm, "m").generate_operations_from_nl(
        nl_prompt="ordena por a", schema={"columns": ["a"]}
    )

    assert plan.mode == "operations"
    assert plan.refinement_iterations == 1
    assert llm.llamadas == 2
