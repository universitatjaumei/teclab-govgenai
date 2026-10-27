"""Tests del orquestador ETLService — 9R.5.8 (RED → GREEN).

ETLService: lee DataFrame, ejecuta operaciones (deterministic) o
genera ops via LLM (ai), aplica y devuelve el DataFrame transformado.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from server.app.modules.redaccion.services.transformation.etl_service import ETLService
from server.app.modules.redaccion.services.transformation.operations import FilterOp
from server.tests.dobles import modelo_de_chat


def _df() -> pd.DataFrame:
    return pd.DataFrame({"region": ["N", "S", "E"], "units": [10, 20, 30]})


def _llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    return resp


class TestETLService:

    @pytest.mark.asyncio
    async def test_etl_service_runs_pipeline_end_to_end_deterministic(self):
        svc = ETLService(llm=None)
        out = await svc.run(
            df=_df(),
            mode="deterministic",
            operations=[FilterOp(col="units", comparator=">", value=15)],
        )
        assert isinstance(out.dataframe, pd.DataFrame)
        assert len(out.dataframe) == 2
        assert out.operations_applied[0].op == "filter"
        assert out.model_used is None

    @pytest.mark.asyncio
    async def test_etl_service_runs_pipeline_end_to_end_ai(self):
        ops_json = json.dumps({
            "mode": "operations",
            "operations": [
                {"op": "filter", "col": "units", "comparator": ">", "value": 15},
            ],
        })
        llm = modelo_de_chat()
        llm.ainvoke = AsyncMock(return_value=_llm_response(ops_json))

        svc = ETLService(llm=llm, model_name="claude-test")
        out = await svc.run(
            df=_df(),
            mode="ai",
            nl_instruction="filtra unidades por encima de 15",
        )
        assert len(out.dataframe) == 2
        assert out.model_used == "claude-test"
        assert out.operations_applied[0].op == "filter"

    @pytest.mark.asyncio
    async def test_etl_service_requires_operations_in_deterministic_mode(self):
        svc = ETLService(llm=None)
        with pytest.raises(ValueError, match="operations"):
            await svc.run(df=_df(), mode="deterministic", operations=None)

    @pytest.mark.asyncio
    async def test_etl_service_requires_llm_in_ai_mode(self):
        svc = ETLService(llm=None)
        with pytest.raises(ValueError, match="llm"):
            await svc.run(df=_df(), mode="ai", nl_instruction="x")
