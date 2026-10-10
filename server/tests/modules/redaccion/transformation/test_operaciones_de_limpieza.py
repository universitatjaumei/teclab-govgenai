"""PRO.4 — las operaciones de limpieza que el legacy tenía y aquí faltaban.

Comparado con `AutomatIA/client_app/app/services/deterministic_etl_service.py` (350 l.): los
dos catálogos no se solapan casi nada. El nuestro **analiza** —filter, aggregate, join, pivot,
normalize, groupby— y el del legacy **limpia**: quitar y renombrar columnas, fusionarlas,
reordenarlas, formatear fechas, sustituir valores, normalizar texto, rellenar nulos, quitar
duplicados y quitar filas vacías.

Y limpiar es lo que hace falta primero: un Excel real llega con columnas que no se usan,
fechas en tres formatos, filas duplicadas y celdas vacías. Sin esas operaciones, «transformar»
en un informe se quedaba en agrupar lo que ya estuviera limpio.

**Una divergencia deliberada con el legacy**: allí, una columna que no existe hace que la
operación no haga nada (`return df`). En una interfaz donde ves el resultado al momento eso es
cómodo; en un informe que se genera en segundo plano es un renombrado que se pierde y un
informe que sale con los datos sin tocar y sin decirlo. Aquí falla con el nombre de la columna
y la lista de las que hay.
"""
from __future__ import annotations

import pandas as pd
import pytest

from server.app.modules.redaccion.services.transformation.deterministic_etl import (
    DeterministicETLService,
)
from server.app.modules.redaccion.services.transformation.operations import parse_operations


def _aplicar(df: pd.DataFrame, *ops: dict) -> pd.DataFrame:
    return DeterministicETLService().execute(df, parse_operations(list(ops)))


@pytest.fixture
def sucio() -> pd.DataFrame:
    return pd.DataFrame({
        "Codigo ": ["A-1", "A-2", "A-2", "A-3"],
        "Nombre": [" ana ", "LUIS", "LUIS", None],
        "importe": [100.0, 200.0, 200.0, None],
        "sobra": [1, 2, 3, 4],
        "fecha": ["01/03/2026", "15/04/2026", "15/04/2026", "31/12/2025"],
    })


class TestColumnas:
    def test_should_quitar_columnas(self, sucio: pd.DataFrame) -> None:
        salida = _aplicar(sucio, {"op": "drop_columns", "columns": ["sobra"]})

        assert "sobra" not in salida.columns
        assert len(salida.columns) == 4

    def test_should_renombrar_columnas(self, sucio: pd.DataFrame) -> None:
        salida = _aplicar(sucio, {"op": "rename_columns", "mapping": {"Nombre": "nombre"}})

        assert "nombre" in salida.columns
        assert "Nombre" not in salida.columns

    def test_should_fusionar_columnas_en_el_sitio_de_la_primera(self, sucio: pd.DataFrame) -> None:
        """El legacy conserva la posición al fusionar, y es lo que hace legible la tabla."""
        salida = _aplicar(sucio, {
            "op": "merge_columns",
            "source_columns": ["Codigo ", "Nombre"],
            "target_column": "referencia",
            "separator": " - ",
            "drop_source": True,
        })

        assert list(salida.columns)[0] == "referencia"
        assert salida["referencia"].iloc[1] == "A-2 - LUIS"
        assert "Codigo " not in salida.columns

    def test_should_dejar_fuera_de_la_fusion_lo_que_esta_vacio(self, sucio: pd.DataFrame) -> None:
        """Una celda vacía no aporta nada a la referencia. Con pandas 2 `astype(str)` la convertía
        en el texto «None» o «nan» y acababa dentro —«A-3 - None»—; con pandas 3 sigue siendo
        nula y el `join` fallaba (2026-10-10, al subir a pandas 3)."""
        salida = _aplicar(sucio, {
            "op": "merge_columns",
            "source_columns": ["Codigo ", "Nombre"],
            "target_column": "referencia",
            "separator": " - ",
        })

        assert salida["referencia"].iloc[3] == "A-3"

    def test_should_conservar_las_de_origen_si_se_pide(self, sucio: pd.DataFrame) -> None:
        salida = _aplicar(sucio, {
            "op": "merge_columns",
            "source_columns": ["Codigo ", "Nombre"],
            "target_column": "referencia",
            "drop_source": False,
        })

        assert "Codigo " in salida.columns
        assert list(salida.columns)[-1] == "referencia"

    def test_should_reordenar_y_dejar_al_final_lo_no_nombrado(self, sucio: pd.DataFrame) -> None:
        salida = _aplicar(sucio, {"op": "reorder_columns", "columns": ["importe", "Nombre"]})

        assert list(salida.columns)[:2] == ["importe", "Nombre"]
        assert set(salida.columns) == set(sucio.columns)

    def test_should_fallar_con_una_columna_que_no_existe(self, sucio: pd.DataFrame) -> None:
        """La divergencia con el legacy: aquí no se calla."""
        from server.app.modules.redaccion.services.transformation.deterministic_etl import (
            ColumnaInexistenteError,
        )

        with pytest.raises(ColumnaInexistenteError) as fallo:
            _aplicar(sucio, {"op": "rename_columns", "mapping": {"Nombrre": "nombre"}})

        assert "Nombrre" in str(fallo.value)
        assert "Nombre" in str(fallo.value), "el mensaje dice qué columnas hay"


class TestValoresYTexto:
    def test_should_sustituir_valores(self, sucio: pd.DataFrame) -> None:
        salida = _aplicar(sucio, {
            "op": "replace_values", "column": "Nombre", "replacements": {"LUIS": "Luis"},
        })

        assert salida["Nombre"].iloc[1] == "Luis"

    @pytest.mark.parametrize(
        ("modo", "esperado"),
        [("upper", " ANA "), ("lower", " ana "), ("title", " Ana "), ("strip", "ana")],
    )
    def test_should_normalizar_texto(self, sucio: pd.DataFrame, modo: str, esperado: str) -> None:
        salida = _aplicar(sucio, {"op": "normalize_text", "columns": ["Nombre"], "mode": modo})

        assert salida["Nombre"].iloc[0] == esperado

    def test_should_pasar_a_snake_case(self) -> None:
        df = pd.DataFrame({"c": ["Importe Total", "creditoInicial", "Con-Guion"]})

        salida = _aplicar(df, {"op": "normalize_text", "columns": ["c"], "mode": "snake_case"})

        assert list(salida["c"]) == ["importe_total", "credito_inicial", "con_guion"]

    def test_should_formatear_fechas_a_iso(self, sucio: pd.DataFrame) -> None:
        salida = _aplicar(sucio, {
            "op": "format_dates",
            "column": "fecha",
            "source_format": "%d/%m/%Y",
            "target_format": "ISO8601",
        })

        assert list(salida["fecha"])[:2] == ["2026-03-01", "2026-04-15"]

    def test_should_avisar_de_las_fechas_que_no_se_entienden(self) -> None:
        """El legacy dejaba la columna intacta y escribía un `print`.

        En un informe eso es una fecha sin convertir que nadie ve. Aquí se convierte lo que se
        puede y las que no, quedan vacías: es visible en la tabla del informe.
        """
        df = pd.DataFrame({"fecha": ["01/03/2026", "no es una fecha"]})

        salida = _aplicar(df, {
            "op": "format_dates", "column": "fecha", "target_format": "ISO8601",
        })

        assert pd.isna(salida["fecha"].iloc[1]) or salida["fecha"].iloc[1] in ("", "NaT")

    def test_should_leer_el_dia_primero_cuando_la_fecha_es_ambigua(self) -> None:
        """`01/03/2026` sin formato explícito es el **1 de marzo**, no el 3 de enero.

        Es lo que pandas decide por defecto al contrario (convención de EE. UU.), y
        equivocarse ahí no da error: da un informe con las fechas cambiadas.
        """
        df = pd.DataFrame({"fecha": ["01/03/2026", "13/04/2026"]})

        salida = _aplicar(df, {
            "op": "format_dates", "column": "fecha", "target_format": "ISO8601",
        })

        assert list(salida["fecha"]) == ["2026-03-01", "2026-04-13"]


class TestNulosYDuplicados:
    def test_should_rellenar_nulos(self, sucio: pd.DataFrame) -> None:
        salida = _aplicar(sucio, {"op": "fill_nulls", "columns": ["importe"], "value": 0})

        assert salida["importe"].iloc[3] == 0

    def test_should_quitar_duplicados(self, sucio: pd.DataFrame) -> None:
        salida = _aplicar(sucio, {"op": "remove_duplicates", "subset": ["Codigo "]})

        assert len(salida) == 3

    def test_should_quitar_filas_con_nulos(self, sucio: pd.DataFrame) -> None:
        salida = _aplicar(sucio, {"op": "drop_null_rows", "subset": ["Nombre"], "how": "any"})

        assert len(salida) == 3
        assert salida["Nombre"].isna().sum() == 0


def test_should_encadenar_limpieza_y_analisis(sucio: pd.DataFrame) -> None:
    """Lo que de verdad hace falta en un informe: limpiar y después agrupar."""
    salida = _aplicar(
        sucio,
        {"op": "drop_columns", "columns": ["sobra", "fecha"]},
        {"op": "normalize_text", "columns": ["Nombre"], "mode": "strip"},
        {"op": "remove_duplicates", "subset": ["Codigo "]},
        {"op": "fill_nulls", "columns": ["importe"], "value": 0},
        {"op": "rename_columns", "mapping": {"Codigo ": "codigo"}},
        {"op": "groupby", "cols": ["codigo"], "agg_dict": {"importe": "sum"}},
    )

    assert list(salida.columns) == ["codigo", "importe"]
    assert len(salida) == 3
    assert salida.set_index("codigo").loc["A-1", "importe"] == 100.0
