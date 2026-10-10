"""DeterministicETLService — ejecuta operaciones declarativas sobre un DataFrame (9R.5.8).

Engine síncrono in-memory: las operaciones se aplican en orden, devolviendo
un DataFrame nuevo. JoinOp usa un resolver inyectado para localizar el otro
DataFrame (típicamente desde `WorkspaceState.block_outputs`).
"""
from __future__ import annotations

import re
from typing import Callable

import pandas as pd

from server.app.modules.redaccion.services.transformation.operations import (
    AggregateOp,
    ComputeColumnOp,
    DropColumnsOp,
    DropNullRowsOp,
    FillNullsOp,
    FilterOp,
    FormatDatesOp,
    GroupByOp,
    JoinOp,
    MergeColumnsOp,
    NormalizeOp,
    NormalizeTextOp,
    Operation,
    PivotOp,
    RemoveDuplicatesOp,
    RenameColumnsOp,
    ReorderColumnsOp,
    ReplaceValuesOp,
    SortRowsOp,
    ToNumberOp,
    UnpivotOp,
)


class UnknownOperationError(TypeError):
    pass


class TransformacionImposibleError(ValueError):
    """La operación está bien escrita pero no puede dar un resultado con estos datos.

    PRO.9 — se distingue de `ColumnaInexistenteError` porque el arreglo es distinto: aquí la
    columna existe y la configuración es la que está mal. El caso que la motiva es `to_number`
    sobre una columna en la que **nada** se convierte: los separadores están al revés, y
    dejarlo pasar vacía la tabla en silencio.
    """


class ColumnaInexistenteError(KeyError):
    """Una operación nombra una columna que la tabla no tiene.

    PRO.4 — el legacy devolvía el DataFrame intacto (`return df`) cuando la columna no
    existía. En una interfaz donde ves el resultado al momento eso es cómodo; en un informe que
    se genera en segundo plano es un renombrado que se pierde y una tabla que sale sin tocar y
    sin decirlo. El nodo convierte esto en un bloque `failed` con su motivo, que es visible.
    """


def _a_snake_case(texto: str) -> str:
    """`Importe Total` → `importe_total`, `creditoInicial` → `credito_inicial`."""
    con_guiones = re.sub(r"[\s\-]+", "_", texto)
    separado = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", con_guiones)
    return separado.lower()


def _exigir_columnas(df: pd.DataFrame, columnas: list[str], operacion: str) -> None:
    faltan = [c for c in columnas if c not in df.columns]
    if faltan:
        raise ColumnaInexistenteError(
            f"{operacion}: la tabla no tiene {faltan}. Columnas disponibles: {list(df.columns)}"
        )


#: Espacios que separan millares en una hoja real, incluido el irrompible que pega Excel.
_ESPACIOS = (" ", " ", " ", "\t")


def _limpiar_numero(valor: str, op: ToNumberOp) -> str:
    """`"(1.234,56 €)"` → `"-1234.56"`, listo para `pd.to_numeric`."""
    texto = valor.strip()
    for simbolo in op.strip:
        texto = texto.replace(simbolo, "")
    for espacio in _ESPACIOS:
        texto = texto.replace(espacio, "")
    # En contabilidad, un importe entre paréntesis es negativo.
    negativo = texto.startswith("(") and texto.endswith(")")
    if negativo:
        texto = texto[1:-1]
    if op.thousands_separator:
        texto = texto.replace(op.thousands_separator, "")
    if op.decimal_separator and op.decimal_separator != ".":
        texto = texto.replace(op.decimal_separator, ".")
    return f"-{texto}" if negativo and texto else texto


def _exigir_separadores_coherentes(texto: pd.Series, columna: str, op: ToNumberOp) -> None:
    """Los separadores declarados al revés dan **otro número**, no un hueco.

    `1,234.56` leído con la coma como decimal sale 1,23456: convierte, no falla, y el informe se
    publica con la cifra mal. Lo que delata la contradicción es la posición: el separador de
    millares nunca va **después** del decimal.
    """
    if not op.thousands_separator or not op.decimal_separator:
        return
    if op.thousands_separator == op.decimal_separator:
        raise TransformacionImposibleError(
            f"to_number: el separador decimal y el de millares no pueden ser el mismo "
            f"({op.decimal_separator!r})"
        )
    for valor in texto:
        decimal = valor.rfind(op.decimal_separator)
        millares = valor.rfind(op.thousands_separator)
        if decimal >= 0 and millares > decimal:
            raise TransformacionImposibleError(
                f"to_number: en {columna!r} el valor {valor!r} lleva el separador de millares "
                f"({op.thousands_separator!r}) después del decimal ({op.decimal_separator!r}). "
                f"Los separadores están declarados al revés: convertirlo daría otra cifra."
            )


def _operando(df: pd.DataFrame, valor: str | float, operacion: str) -> "pd.Series | float":
    """Una columna si es texto, una constante si es número.

    Un texto es **siempre** un nombre de columna: si no existe, falla. Tomarlo por una constante
    de texto daría una columna de basura sin decir nada.
    """
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    _exigir_columnas(df, [str(valor)], operacion)
    return pd.to_numeric(df[str(valor)], errors="coerce")


JoinableResolver = Callable[[str], pd.DataFrame]


class DeterministicETLService:
    """Aplica una lista de Operation a un DataFrame, en orden."""

    def __init__(self, joinable_resolver: JoinableResolver | None = None) -> None:
        self._joinable_resolver = joinable_resolver

    def execute(self, df: pd.DataFrame, operations: list[Operation]) -> pd.DataFrame:
        result = df.copy()
        for op in operations:
            if isinstance(op, FilterOp):
                result = self._filter(result, op)
            elif isinstance(op, AggregateOp):
                result = self._aggregate(result, op)
            elif isinstance(op, JoinOp):
                result = self._join(result, op)
            elif isinstance(op, PivotOp):
                result = self._pivot(result, op)
            elif isinstance(op, NormalizeOp):
                result = self._normalize(result, op)
            elif isinstance(op, GroupByOp):
                result = self._groupby(result, op)
            # PRO.4 — limpieza, portada del legacy.
            elif isinstance(op, DropColumnsOp):
                _exigir_columnas(result, op.columns, "drop_columns")
                result = result.drop(columns=op.columns)
            elif isinstance(op, RenameColumnsOp):
                _exigir_columnas(result, list(op.mapping), "rename_columns")
                result = result.rename(columns=op.mapping)
            elif isinstance(op, MergeColumnsOp):
                result = self._merge_columns(result, op)
            elif isinstance(op, ReorderColumnsOp):
                _exigir_columnas(result, op.columns, "reorder_columns")
                resto = [c for c in result.columns if c not in op.columns]
                result = result[op.columns + resto]
            elif isinstance(op, FormatDatesOp):
                result = self._format_dates(result, op)
            elif isinstance(op, ReplaceValuesOp):
                _exigir_columnas(result, [op.column], "replace_values")
                result = result.copy()
                result[op.column] = result[op.column].replace(op.replacements)
            elif isinstance(op, NormalizeTextOp):
                result = self._normalize_text(result, op)
            elif isinstance(op, FillNullsOp):
                _exigir_columnas(result, op.columns, "fill_nulls")
                result = result.copy()
                result[op.columns] = result[op.columns].fillna(op.value)
            elif isinstance(op, RemoveDuplicatesOp):
                if op.subset:
                    _exigir_columnas(result, op.subset, "remove_duplicates")
                result = result.drop_duplicates(subset=op.subset, keep=op.keep)
            elif isinstance(op, DropNullRowsOp):
                if op.subset:
                    _exigir_columnas(result, op.subset, "drop_null_rows")
                result = result.dropna(subset=op.subset, how=op.how)
            # PRO.9 — lo que una hoja de cálculo necesita para llegar a un informe.
            elif isinstance(op, ToNumberOp):
                result = self._to_number(result, op)
            elif isinstance(op, ComputeColumnOp):
                result = self._compute_column(result, op)
            elif isinstance(op, SortRowsOp):
                _exigir_columnas(result, op.by, "sort_rows")
                result = result.sort_values(op.by, ascending=op.ascending).reset_index(drop=True)
            elif isinstance(op, UnpivotOp):
                result = self._unpivot(result, op)
            else:
                raise UnknownOperationError(f"Unknown operation type: {type(op).__name__}")
        return result

    # ------------------------------------------------------------------
    # Limpieza (PRO.4)
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_columns(df: pd.DataFrame, op: MergeColumnsOp) -> pd.DataFrame:
        _exigir_columnas(df, op.source_columns, "merge_columns")
        # Lo vacío se queda fuera. Con pandas 2 `astype(str)` lo convertía en «None» o «nan» y
        # acababa dentro de la referencia; con pandas 3 sigue siendo nulo y el `join` fallaba.
        valores = df[op.source_columns].apply(
            lambda fila: op.separator.join(str(v) for v in fila if pd.notna(v)), axis=1
        )
        if not op.drop_source:
            salida = df.copy()
            salida[op.target_column] = valores
            return salida

        # La posición de la primera columna fusionada se conserva: si la referencia acabara al
        # final de la tabla, habría que reordenar después en otra operación.
        posicion = min(list(df.columns).index(c) for c in op.source_columns)
        salida = df.drop(columns=op.source_columns)
        salida.insert(posicion, op.target_column, valores)
        return salida

    @staticmethod
    def _format_dates(df: pd.DataFrame, op: FormatDatesOp) -> pd.DataFrame:
        _exigir_columnas(df, [op.column], "format_dates")
        salida = df.copy()
        # `errors="coerce"`: lo que no se entiende como fecha queda vacío, y eso **se ve** en la
        # tabla del informe. El legacy dejaba la columna entera intacta y escribía un `print`,
        # así que una fecha sin convertir pasaba desapercibida.
        #
        # `dayfirst=True` en la detección automática: `01/03/2026` es ambiguo y pandas lo lee
        # como **3 de enero** (convención de EE. UU.). En un fichero de esta institución es el
        # 1 de marzo, y equivocarse ahí no da error: da un informe con las fechas cambiadas.
        # Con `source_format` explícito manda el formato, que es lo inequívoco.
        if op.source_format:
            fechas = pd.to_datetime(salida[op.column], format=op.source_format, errors="coerce")
        else:
            fechas = pd.to_datetime(salida[op.column], errors="coerce", dayfirst=True)
        formato = "%Y-%m-%d" if op.target_format.upper() == "ISO8601" else op.target_format
        salida[op.column] = fechas.dt.strftime(formato)
        return salida

    @staticmethod
    def _normalize_text(df: pd.DataFrame, op: NormalizeTextOp) -> pd.DataFrame:
        _exigir_columnas(df, op.columns, "normalize_text")
        salida = df.copy()
        for col in op.columns:
            texto = salida[col].astype(str)
            if op.mode == "upper":
                salida[col] = texto.str.upper()
            elif op.mode == "lower":
                salida[col] = texto.str.lower()
            elif op.mode == "title":
                salida[col] = texto.str.title()
            elif op.mode == "strip":
                salida[col] = texto.str.strip()
            elif op.mode == "snake_case":
                # Con pandas 3 lo vacío sigue siendo nulo tras `astype(str)`, y no es texto.
                salida[col] = texto.map(_a_snake_case, na_action="ignore")
        return salida

    # ------------------------------------------------------------------
    # De una hoja de cálculo a los datos del informe (PRO.9)
    # ------------------------------------------------------------------

    @staticmethod
    def _to_number(df: pd.DataFrame, op: ToNumberOp) -> pd.DataFrame:
        """Texto con formato de aquí → número.

        Callarse cuando **nada** se convierte sería lo peor: la tabla saldría vacía y el
        informe con ella. Una celda suelta ilegible sí es un dato ausente, y se ve.
        """
        _exigir_columnas(df, op.columns, "to_number")
        salida = df.copy()
        for col in op.columns:
            if pd.api.types.is_numeric_dtype(salida[col]):
                continue
            # Con pandas 3 lo vacío sigue siendo nulo tras `astype(str)`: no es texto que
            # limpiar ni cuenta como un valor que se intentó convertir.
            texto = salida[col].astype(str)
            _exigir_separadores_coherentes(texto.dropna(), col, op)
            tenia_valor = salida[col].notna() & ~texto.str.strip().str.lower().isin(
                ["", "nan", "none", "<na>"]
            )
            convertida = pd.to_numeric(
                texto.map(lambda v: _limpiar_numero(v, op), na_action="ignore"), errors="coerce"
            )
            if tenia_valor.any() and convertida.notna().sum() == 0:
                raise TransformacionImposibleError(
                    f"to_number: no se ha podido convertir ni un valor de {col!r} con "
                    f"decimal={op.decimal_separator!r} y millares={op.thousands_separator!r}. "
                    f"Ejemplo del contenido: {texto.iloc[0]!r}"
                )
            salida[col] = convertida
        return salida

    @staticmethod
    def _compute_column(df: pd.DataFrame, op: ComputeColumnOp) -> pd.DataFrame:
        salida = df.copy()
        izquierda = _operando(salida, op.left, "compute_column")
        derecha = _operando(salida, op.right, "compute_column")
        if op.operator == "+":
            valores = izquierda + derecha
        elif op.operator == "-":
            valores = izquierda - derecha
        elif op.operator == "*":
            valores = izquierda * derecha
        else:
            valores = izquierda / derecha
        valores = valores * op.scale
        # Un `inf` en una tabla de informe es basura publicada; un hueco se ve y se pregunta.
        valores = pd.to_numeric(valores, errors="coerce").replace(
            [float("inf"), float("-inf")], pd.NA
        )
        if op.round_to is not None:
            valores = valores.round(op.round_to)
        salida[op.target] = valores
        return salida

    @staticmethod
    def _unpivot(df: pd.DataFrame, op: UnpivotOp) -> pd.DataFrame:
        _exigir_columnas(df, op.id_columns, "unpivot")
        valores = op.value_columns or [c for c in df.columns if c not in op.id_columns]
        _exigir_columnas(df, valores, "unpivot")
        return df.melt(
            id_vars=op.id_columns,
            value_vars=valores,
            var_name=op.variable_name,
            value_name=op.value_name,
        )

    # ------------------------------------------------------------------
    # Operadores
    # ------------------------------------------------------------------

    @staticmethod
    def _filter(df: pd.DataFrame, op: FilterOp) -> pd.DataFrame:
        if op.col not in df.columns:
            return df
        series = df[op.col]
        comp = op.comparator
        if comp == "==":
            mask = series == op.value
        elif comp == "!=":
            mask = series != op.value
        elif comp == ">":
            mask = series > op.value
        elif comp == "<":
            mask = series < op.value
        elif comp == ">=":
            mask = series >= op.value
        elif comp == "<=":
            mask = series <= op.value
        elif comp == "contains":
            mask = series.astype(str).str.contains(str(op.value), na=False)
        elif comp == "not_contains":
            mask = ~series.astype(str).str.contains(str(op.value), na=False)
        elif comp == "in":
            values = op.value if isinstance(op.value, (list, tuple, set)) else [op.value]
            mask = series.isin(values)
        elif comp == "isnull":
            mask = series.isnull()
        elif comp == "notnull":
            mask = series.notnull()
        else:  # pragma: no cover — schema lo impide
            raise ValueError(f"Unsupported comparator: {comp!r}")
        return df.loc[mask].reset_index(drop=True)

    @staticmethod
    def _aggregate(df: pd.DataFrame, op: AggregateOp) -> pd.DataFrame:
        if op.col not in df.columns:
            return pd.DataFrame({f"{op.col}_{op.function}": []})
        value = getattr(df[op.col], op.function)()
        return pd.DataFrame({f"{op.col}_{op.function}": [value]})

    def _join(self, df: pd.DataFrame, op: JoinOp) -> pd.DataFrame:
        if self._joinable_resolver is None:
            raise ValueError(
                f"JoinOp on {op.other_block_ref!r} requires a joinable_resolver, "
                "but none was injected into DeterministicETLService."
            )
        other = self._joinable_resolver(op.other_block_ref)
        return df.merge(other, on=op.on, how=op.how)

    @staticmethod
    def _pivot(df: pd.DataFrame, op: PivotOp) -> pd.DataFrame:
        pivoted = pd.pivot_table(
            df,
            index=op.index,
            columns=op.columns,
            values=op.values,
            aggfunc=op.aggfunc,
            fill_value=0,
        )
        pivoted = pivoted.reset_index()
        pivoted.columns.name = None
        pivoted.columns = [str(c) for c in pivoted.columns]
        return pivoted

    @staticmethod
    def _normalize(df: pd.DataFrame, op: NormalizeOp) -> pd.DataFrame:
        result = df.copy()
        for col in op.cols:
            if col not in result.columns:
                continue
            series = result[col].astype(float)
            if op.method == "min_max":
                rng = series.max() - series.min()
                if rng == 0:
                    result[col] = 0.0
                else:
                    result[col] = (series - series.min()) / rng
            else:  # z_score
                std = series.std(ddof=0)
                if std == 0:
                    result[col] = 0.0
                else:
                    result[col] = (series - series.mean()) / std
        return result

    @staticmethod
    def _groupby(df: pd.DataFrame, op: GroupByOp) -> pd.DataFrame:
        return df.groupby(op.cols, as_index=False).agg(op.agg_dict)
