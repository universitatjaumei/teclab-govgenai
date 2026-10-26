"""Tests del motor ETL determinista — 9R.5.8 (RED → GREEN).

Cubren:
  - Operation discriminated union (filter, aggregate, join, pivot, normalize, groupby).
  - DeterministicETLService.execute() para cada tipo de operación.
"""
from __future__ import annotations

import pandas as pd
import pytest

from server.app.modules.redaccion.services.transformation.operations import (
    AggregateOp,
    FilterOp,
    GroupByOp,
    JoinOp,
    NormalizeOp,
    Operation,
    PivotOp,
    parse_operations,
)
from server.app.modules.redaccion.services.transformation.deterministic_etl import (
    DeterministicETLService,
    UnknownOperationError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sales_df() -> pd.DataFrame:
    return pd.DataFrame({
        "region":   ["N", "N", "S", "S", "E"],
        "product":  ["A", "B", "A", "B", "A"],
        "units":    [10,  20,  30,  40,  50],
        "revenue": [100, 200, 300, 400, 500],
    })


def _employees_df() -> pd.DataFrame:
    return pd.DataFrame({
        "region": ["N", "S", "E"],
        "manager": ["Alice", "Bob", "Carol"],
    })


# ---------------------------------------------------------------------------
# Operation contract (discriminated union)
# ---------------------------------------------------------------------------

class TestOperationContract:

    def test_filter_op_discriminator(self):
        op = FilterOp(col="units", comparator=">", value=15)
        assert op.op == "filter"

    def test_aggregate_op_discriminator(self):
        op = AggregateOp(col="revenue", function="sum")
        assert op.op == "aggregate"

    def test_join_op_requires_other_block_ref(self):
        with pytest.raises(ValueError, match="other_block_ref"):
            JoinOp(on="region")  # type: ignore[call-arg]

    def test_pivot_op_basic(self):
        op = PivotOp(index="region", columns="product", values="revenue")
        assert op.op == "pivot"

    def test_filter_op_rejects_unknown_comparator(self):
        with pytest.raises(ValueError, match="comparator"):
            FilterOp(col="x", comparator="bogus", value=1)  # type: ignore[arg-type]

    def test_parse_operations_from_dict_list(self):
        payload = [
            {"op": "filter",    "col": "units", "comparator": ">", "value": 15},
            {"op": "aggregate", "col": "revenue", "function": "sum"},
        ]
        ops = parse_operations(payload)
        assert isinstance(ops[0], FilterOp)
        assert isinstance(ops[1], AggregateOp)


# ---------------------------------------------------------------------------
# DeterministicETLService.execute
# ---------------------------------------------------------------------------

class TestDeterministicETL:

    def test_deterministic_etl_filter(self):
        df = _sales_df()
        ops: list[Operation] = [FilterOp(col="units", comparator=">", value=15)]
        out = DeterministicETLService().execute(df, ops)
        assert len(out) == 4
        assert (out["units"] > 15).all()

    def test_deterministic_etl_aggregate(self):
        df = _sales_df()
        ops: list[Operation] = [AggregateOp(col="revenue", function="sum")]
        out = DeterministicETLService().execute(df, ops)
        assert len(out) == 1
        assert out["revenue_sum"].iloc[0] == 1500

    def test_deterministic_etl_join(self):
        sales = _sales_df()
        employees = _employees_df()
        joined = DeterministicETLService(
            joinable_resolver=lambda ref: employees
        ).execute(
            sales,
            [JoinOp(other_block_ref="b_employees", on="region", how="left")],
        )
        # All 5 sales rows are kept with their manager attached.
        assert len(joined) == 5
        assert "manager" in joined.columns
        assert set(joined["manager"].unique()) == {"Alice", "Bob", "Carol"}

    def test_deterministic_etl_pivot(self):
        df = _sales_df()
        ops: list[Operation] = [
            PivotOp(index="region", columns="product", values="revenue", aggfunc="sum"),
        ]
        out = DeterministicETLService().execute(df, ops)
        assert "A" in out.columns
        assert "B" in out.columns
        # Region "S" → product A=300, B=400.
        s_row = out[out["region"] == "S"].iloc[0]
        assert s_row["A"] == 300
        assert s_row["B"] == 400

    def test_deterministic_etl_groupby_with_multiple_aggs(self):
        df = _sales_df()
        ops: list[Operation] = [
            GroupByOp(cols=["region"], agg_dict={"units": "sum", "revenue": "mean"}),
        ]
        out = DeterministicETLService().execute(df, ops)
        n_row = out[out["region"] == "N"].iloc[0]
        assert n_row["units"] == 30
        assert n_row["revenue"] == 150  # (100+200)/2

    def test_deterministic_etl_normalize_min_max(self):
        df = _sales_df()
        ops: list[Operation] = [NormalizeOp(cols=["units"], method="min_max")]
        out = DeterministicETLService().execute(df, ops)
        assert out["units"].min() == pytest.approx(0.0)
        assert out["units"].max() == pytest.approx(1.0)

    def test_deterministic_etl_chains_operations_in_order(self):
        df = _sales_df()
        ops: list[Operation] = [
            FilterOp(col="region", comparator="!=", value="E"),
            GroupByOp(cols=["region"], agg_dict={"revenue": "sum"}),
        ]
        out = DeterministicETLService().execute(df, ops)
        assert set(out["region"].unique()) == {"N", "S"}
        assert out[out["region"] == "S"]["revenue"].iloc[0] == 700

    def test_deterministic_etl_join_without_resolver_raises(self):
        df = _sales_df()
        ops: list[Operation] = [JoinOp(other_block_ref="b_x", on="region")]
        with pytest.raises(ValueError, match="resolver"):
            DeterministicETLService().execute(df, ops)

    def test_deterministic_etl_rejects_non_operation(self):
        df = _sales_df()
        with pytest.raises(UnknownOperationError):
            DeterministicETLService().execute(df, [object()])  # type: ignore[list-item]
