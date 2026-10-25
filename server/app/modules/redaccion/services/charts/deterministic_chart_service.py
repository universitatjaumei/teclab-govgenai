"""DeterministicChartService — generación de gráficos sin IA (9R.5.7).

Migrado de client_app/app/services/deterministic_graphics_service.py.
In-process con matplotlib Agg: sin subprocess, sin LLM.

PRO.8 — once tipos, orden de categorías y `show_values` implementado (estaba declarado en
`ChartConfiguration` desde 9R.5.7 y el renderizador lo ignoraba, que es peor que no tenerlo:
quien lo pone en una plantilla cree que ha pedido las cifras).
"""
from __future__ import annotations

from typing import Any, cast

import io

import matplotlib
matplotlib.use("Agg")  # backend no interactivo; debe llamarse antes de pyplot
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.ticker import FuncFormatter

from server.app.modules.redaccion.services.charts.chart_configuration import ChartConfiguration

# Tipos en los que el eje X lleva la categoría y el Y el valor. `barh` los cruza y los
# circulares no tienen ejes.
_SIN_EJES = frozenset({"pie", "donut"})

#: Tipos con un eje numérico al que tiene sentido ponerle separadores de millares.
_CON_EJE_DE_VALORES = frozenset({"bar", "barh", "bar_stacked", "line", "histogram", "boxplot"})


def _columna_de_valor(config: ChartConfiguration) -> str | None:
    """La columna que lleva el número, según el eje en que la pone el tipo de gráfico.

    En `barh` las barras son horizontales, así que el valor va en el eje X; en el resto, en el Y.
    """
    if config.chart_type == "barh":
        return config.x_column or config.value_column
    return config.y_column or config.value_column


def formatear_cifra(valor: float, config: ChartConfiguration) -> str:
    """La cifra con los separadores de aquí: `128.340,55`, no `128,340.55`.

    Se descubrió mirando el PNG, no en un test: los tests comprobaban que la cifra estaba, y
    estaba —en formato inglés, en un informe de una institución española—. `format` no sabe de
    convenciones locales y `locale` es estado global del proceso, así que se intercambian los
    separadores sobre el resultado, que es determinista y no depende del entorno.
    """
    texto = config.value_format.format(valor)
    if config.number_format != "es":
        return texto
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


class DeterministicChartService:
    """Genera gráficos a partir de configuración explícita del usuario."""

    def render(self, df: pd.DataFrame, config: ChartConfiguration) -> bytes:
        """Renderiza el gráfico y devuelve bytes PNG o SVG.

        Síncrono: CPU-bound, sin I/O externo.
        """
        fig = self.render_figure(df, config)
        return self._to_bytes(fig, config.output_format)

    def render_figure(self, df: pd.DataFrame, config: ChartConfiguration):
        """La figura de matplotlib, sin serializar.

        Existe para que los tests puedan mirar lo que se ha dibujado —un título, una cifra
        encima de una barra, el orden del eje— en vez de conformarse con «devuelve bytes».
        """
        sns.set_style(cast(Any, config.style))
        fig, ax = plt.subplots(figsize=config.size)

        plot_df = self._prepare_data(df, config)

        renderizadores = {
            "bar": self._render_bar,
            "barh": self._render_bar,
            "bar_stacked": self._render_bar_stacked,
            "line": self._render_line,
            "pie": self._render_pie,
            "donut": self._render_pie,
            "scatter": self._render_scatter,
            "bubble": self._render_scatter,
            "histogram": self._render_histogram,
            "boxplot": self._render_boxplot,
            "heatmap": self._render_heatmap,
        }
        renderizadores[config.chart_type](plot_df, ax, config)

        self._apply_styling(ax, config, plot_df)
        return fig

    # ------------------------------------------------------------------
    # Data preparation
    # ------------------------------------------------------------------

    def _prepare_data(self, df: pd.DataFrame, config: ChartConfiguration) -> pd.DataFrame:
        preparado = self._agregar(df, config)
        return self._ordenar(preparado, config)

    def _agregar(self, df: pd.DataFrame, config: ChartConfiguration) -> pd.DataFrame:
        if config.aggregation == "none":
            return df.copy()
        group_cols = [c for c in [config.x_column, config.color_column] if c and c in df.columns]
        value_col = config.y_column or config.value_column
        if not group_cols or not value_col or value_col not in df.columns:
            return df.copy()
        agg_map = {"sum": "sum", "mean": "mean", "count": "count", "min": "min", "max": "max"}
        func = agg_map.get(config.aggregation, "sum")
        return cast(pd.DataFrame, df.groupby(group_cols, as_index=False).agg({value_col: func}))

    @staticmethod
    def _ordenar(df: pd.DataFrame, config: ChartConfiguration) -> pd.DataFrame:
        """Orden de las categorías por su valor.

        Una tabla de informe se lee ordenada, y ordenarla no es un tipo de gráfico nuevo.

        GUI.4 — ordenaba siempre por `y_column`, que en un `barh` es la **categoría**: «de mayor
        a menor» acababa siendo un orden alfabético por el nombre del capítulo.
        """
        if config.sort == "none":
            return df
        columna = _columna_de_valor(config)
        if not columna or columna not in df.columns:
            return df
        return df.sort_values(columna, ascending=config.sort == "asc").reset_index(drop=True)

    # ------------------------------------------------------------------
    # Chart renderers
    # ------------------------------------------------------------------

    def _render_bar(self, df: pd.DataFrame, ax, config: ChartConfiguration) -> None:
        """`bar` y `barh` son el mismo gráfico; lo que cambia es qué columna va en cada eje.

        GUI.4 — aquí se cruzaban los ejes por detrás, tratando `x_column` como «la categoría».
        Con eso, quien rellena el contrato leyendo los nombres —el modelo, o una persona— pone
        el valor en `x_axis` porque su `x_label` habla del eje X, y **los dos cruces se anulan**:
        se pidió un barh de conceptos y salió un gráfico vertical con el índice en el eje. Ahora
        `x_column` es el eje X y `y_column` el Y, sin más.
        """
        comun = {"data": df, "x": config.x_column, "y": config.y_column, "ax": ax}
        if config.color_column and config.color_column in df.columns:
            sns.barplot(**comun, hue=config.color_column, palette=config.palette)
        else:
            sns.barplot(**comun, color=sns.color_palette(config.palette)[0])
        self._pintar_cifras(ax, config)

    def _render_bar_stacked(self, df: pd.DataFrame, ax, config: ChartConfiguration) -> None:
        """Barras apiladas: una fila por categoría y una capa por cada valor de `color_column`."""
        tabla = self._tabla_cruzada(
            df, indice=config.x_column, columnas=config.color_column, valores=config.y_column
        )
        if tabla is None:
            ax.text(0.5, 0.5, "Apiladas: faltan x/y/color", ha="center", va="center")
            return
        acumulado = None
        colores = sns.color_palette(config.palette, len(tabla.columns))
        for color, columna in zip(colores, tabla.columns, strict=True):
            valores = tabla[columna]
            ax.bar(
                tabla.index.astype(str), valores, bottom=acumulado,
                label=str(columna), color=color,
            )
            acumulado = valores if acumulado is None else acumulado + valores
        ax.legend()
        self._pintar_cifras(ax, config)

    def _render_line(self, df: pd.DataFrame, ax, config: ChartConfiguration) -> None:
        if config.color_column and config.color_column in df.columns:
            sns.lineplot(
                data=df, x=config.x_column, y=config.y_column,
                hue=config.color_column, palette=config.palette, marker="o", ax=ax,
            )
        else:
            sns.lineplot(data=df, x=config.x_column, y=config.y_column, marker="o", ax=ax)
        self._pintar_cifras(ax, config)

    def _render_pie(self, df: pd.DataFrame, ax, config: ChartConfiguration) -> None:
        label_col = config.label_column or config.x_column
        value_col = config.value_column or config.y_column
        if not label_col or not value_col:
            ax.text(0.5, 0.5, "Pie: faltan label_column/value_column", ha="center", va="center")
            return
        labels = df[label_col].tolist() if label_col in df.columns else []
        values = df[value_col].tolist() if value_col in df.columns else []
        colors = sns.color_palette(config.palette, len(labels))
        # El donut es la misma tarta con el centro hueco.
        wedgeprops = (
            {"width": 1.0 - config.donut_ratio} if config.chart_type == "donut" else None
        )
        ax.pie(
            values, labels=labels, autopct="%1.1f%%", colors=colors,
            startangle=90, wedgeprops=wedgeprops,
        )
        ax.axis("equal")

    def _render_scatter(self, df: pd.DataFrame, ax, config: ChartConfiguration) -> None:
        """`scatter`, y `bubble` cuando el tamaño del punto lleva una tercera variable."""
        comun = {"data": df, "x": config.x_column, "y": config.y_column, "ax": ax}
        tamanyo = config.size_column if config.chart_type == "bubble" else None
        if tamanyo and tamanyo in df.columns:
            comun["size"] = tamanyo
            comun["sizes"] = (40, 400)
        else:
            comun["s"] = 60
        if config.color_column and config.color_column in df.columns:
            sns.scatterplot(**comun, hue=config.color_column, palette=config.palette)
        else:
            sns.scatterplot(**comun)

    def _render_histogram(self, df: pd.DataFrame, ax, config: ChartConfiguration) -> None:
        bins: int | str = config.bins or "auto"
        if config.color_column and config.color_column in df.columns:
            sns.histplot(
                data=df, x=config.x_column, hue=config.color_column,
                bins=bins, palette=config.palette, ax=ax, alpha=0.7,
            )
        else:
            color = sns.color_palette(config.palette)[0]
            sns.histplot(data=df, x=config.x_column, bins=bins, ax=ax, color=color)

    def _render_boxplot(self, df: pd.DataFrame, ax, config: ChartConfiguration) -> None:
        """Dispersión del valor dentro de cada grupo: mediana, cuartiles y atípicos."""
        comun = {"data": df, "x": config.x_column, "y": config.y_column, "ax": ax}
        if config.color_column and config.color_column in df.columns:
            sns.boxplot(**comun, hue=config.color_column, palette=config.palette)
        else:
            sns.boxplot(**comun, palette=config.palette, hue=config.x_column, legend=False)

    def _render_heatmap(self, df: pd.DataFrame, ax, config: ChartConfiguration) -> None:
        """Matriz `y_column` × `x_column` con el valor en color. Capítulo × año."""
        tabla = self._tabla_cruzada(
            df, indice=config.y_column, columnas=config.x_column,
            valores=config.value_column or config.y_column,
        )
        if tabla is None:
            ax.text(0.5, 0.5, "Heatmap: faltan x/y/value", ha="center", va="center")
            return
        sns.heatmap(
            tabla, ax=ax, cmap=config.palette, annot=True,
            fmt=".2f", cbar=config.show_legend,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tabla_cruzada(
        df: pd.DataFrame, indice: str | None, columnas: str | None, valores: str | None
    ) -> pd.DataFrame | None:
        if not all([indice, columnas, valores]):
            return None
        if not {indice, columnas, valores} <= set(df.columns):
            return None
        cruzada = df.pivot_table(
            index=indice, columns=columnas, values=valores, aggfunc="sum", fill_value=0
        )
        return cruzada if not cruzada.empty else None

    def _pintar_cifras(self, ax, config: ChartConfiguration) -> None:
        """Las cifras encima de las barras.

        En un informe presupuestario son la norma, no un adorno: quien lee la tabla quiere el
        número, y el gráfico sin él obliga a mirar dos sitios.
        """
        if not config.show_values:
            return
        for contenedor in ax.containers:
            try:
                ax.bar_label(
                    contenedor,
                    labels=[formatear_cifra(v, config) for v in self._alturas(contenedor)],
                    padding=2, fontsize=9,
                )
            except (TypeError, ValueError, AttributeError):
                # Un contenedor sin alturas legibles (líneas, errorbars) no se etiqueta.
                continue

    @staticmethod
    def _alturas(contenedor) -> list[float]:
        datavalues = getattr(contenedor, "datavalues", None)
        if datavalues is None:
            raise AttributeError("contenedor sin datavalues")
        return [float(v) for v in datavalues]

    # ------------------------------------------------------------------
    # Styling / output
    # ------------------------------------------------------------------

    def _apply_styling(self, ax, config: ChartConfiguration, df: pd.DataFrame) -> None:
        if config.title:
            ax.set_title(config.title, fontsize=14, fontweight="bold", pad=15)
        self._etiquetar_ejes(ax, config)
        self._formatear_eje_de_valores(ax, config, df)
        if not config.show_grid:
            ax.grid(False)
        if not config.show_legend:
            legend = ax.get_legend()
            if legend:
                legend.remove()
        plt.tight_layout()

    @staticmethod
    def _formatear_eje_de_valores(ax, config: ChartConfiguration, df: pd.DataFrame) -> None:
        """`120.000` en el eje, no `120000`. Es lo que separa un gráfico de un boceto.

        GUI.4 — decidía cuál es el eje numérico **por el tipo de gráfico**, así que en cuanto las
        columnas no seguían la convención interna escribía `0, 1, 2, 3` **encima de los nombres
        de las categorías**: el gráfico salía ilegible y sin nada que delatara por qué. Ahora se
        decide por los datos, que es lo único que no puede mentir.
        """
        if config.chart_type not in _CON_EJE_DE_VALORES:
            return
        columna = _columna_de_valor(config)
        if not columna or columna not in df.columns:
            return
        if not pd.api.types.is_numeric_dtype(df[columna]):
            return
        eje = ax.xaxis if columna == config.x_column else ax.yaxis
        eje.set_major_formatter(
            FuncFormatter(
                lambda valor, _: formatear_cifra(
                    valor, config.model_copy(update={"value_format": "{:,.0f}"})
                )
            )
        )

    @staticmethod
    def _etiquetar_ejes(ax, config: ChartConfiguration) -> None:
        """La etiqueta explícita manda; si falta, el nombre de la columna que va en ese eje.

        GUI.4 — cruzaba los defectos en `barh`, coherente con el cruce del renderizador. Ya no
        hay cruce en ninguno de los dos sitios: `x_label` es la etiqueta del eje X.
        """
        if config.chart_type in _SIN_EJES:
            return
        if etiqueta := (config.x_label or config.x_column):
            ax.set_xlabel(etiqueta)
        if etiqueta := (config.y_label or config.y_column):
            ax.set_ylabel(etiqueta)

    def _to_bytes(self, fig, output_format: str) -> bytes:
        buf = io.BytesIO()
        fig.savefig(buf, format=output_format, dpi=150, bbox_inches="tight", facecolor="white")
        buf.seek(0)
        plt.close(fig)
        return buf.read()
