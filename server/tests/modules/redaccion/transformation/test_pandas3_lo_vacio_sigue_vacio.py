"""Pandas 3: `astype(str)` deja de convertir lo vacío en el texto «nan» (2026-10-10).

Con pandas 2, `serie.astype(str)` convertía un nulo en la cadena `"nan"` o `"None"`, y el código
que venía detrás trabajaba con texto. Con pandas 3 el nulo **sigue siendo nulo** —un `float`
`nan`— y lo que esperaba una cadena recibe otra cosa: unas veces falla, otras cuenta mal en
silencio. La suite no lo veía porque sus tablas no tenían celdas vacías en esas columnas.

En los tres sitios la regla es la misma: **lo vacío sigue vacío**. Ni el texto «nan» que salía antes
en las tablas, ni un `NaN` que JSONB no admite.
"""
from __future__ import annotations

import json

import pandas as pd

from server.app.modules.redaccion.services.transformation.deterministic_etl import (
    DeterministicETLService,
)
from server.app.modules.redaccion.services.transformation.operations import parse_operations


def _aplicar(df: pd.DataFrame, *ops: dict) -> pd.DataFrame:
    return DeterministicETLService().execute(df, parse_operations(list(ops)))


def test_una_tabla_del_informe_lleva_lo_vacio_como_texto_vacio_y_es_json_valido():
    from server.app.modules.redaccion.graph.nodes.data_transformation import _tabla_de

    tabla = _tabla_de("t", pd.DataFrame({"a": ["x", None], "b": [1.5, None]}))

    assert tabla["rows"] == [["x", "1.5"], ["", ""]]
    json.dumps(tabla, allow_nan=False)  # JSONB no admite NaN


def test_to_number_no_cuenta_una_celda_vacia_como_dato():
    salida = _aplicar(
        pd.DataFrame({"importe": ["1.234,50", None, "10,00"]}),
        {"op": "to_number", "columns": ["importe"], "decimal_separator": ",", "thousands_separator": "."},
    )

    assert salida["importe"].iloc[0] == 1234.5
    assert pd.isna(salida["importe"].iloc[1])
    assert salida["importe"].iloc[2] == 10.0


def test_normalizar_a_snake_case_deja_vacio_lo_vacio():
    salida = _aplicar(
        pd.DataFrame({"categoria": ["Gasto Corriente", None]}),
        {"op": "normalize_text", "columns": ["categoria"], "mode": "snake_case"},
    )

    assert salida["categoria"].iloc[0] == "gasto_corriente"
    assert pd.isna(salida["categoria"].iloc[1])
