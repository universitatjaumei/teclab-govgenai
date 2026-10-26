"""PRO.8 — lo usual se elige de forma determinista, sin generar código.

Tres cosas se comprueban aquí, en orden de importancia:

1. Que una **plantilla** pueda pedir la presentación completa (título, etiquetas de eje, cifras
   encima de las barras, orden). Antes de PRO.8 `ChartConfiguration` sabía hacerlo pero
   `ChartBlockConfig` —que es lo que una plantilla expresa— no lo exponía, así que un gráfico
   con título exigía generar un script.
2. Que `show_values` haga algo. Estaba declarado en el contrato y el renderizador lo ignoraba.
3. Que los tipos usuales rendericen sin pasar por ningún modelo.
"""
from __future__ import annotations

import pandas as pd
import pytest

from server.app.modules.redaccion.blocks.handlers import ChartHandler
from server.app.modules.redaccion.contracts.blocks import ChartBlockConfig
from server.app.modules.redaccion.services.charts.chart_configuration import ChartConfiguration
from server.app.modules.redaccion.services.charts.deterministic_chart_service import (
    DeterministicChartService,
)


@pytest.fixture
def datos() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "capitulo": ["Cap. 1", "Cap. 2", "Cap. 4", "Cap. 6"],
            "anyo": [2024, 2024, 2025, 2025],
            "importe": [120.0, 340.5, 80.25, 500.0],
            "ejecucion": [0.91, 0.55, 0.78, 0.40],
        }
    )


# ----------------------------------------------------------------------
# 1. La presentación es expresable desde una plantilla
# ----------------------------------------------------------------------


def test_el_bloque_de_plantilla_puede_pedir_titulo_y_etiquetas() -> None:
    """El hueco de PRO.5: el renderizador sabía poner título; la plantilla no podía pedirlo."""
    cfg = ChartBlockConfig(
        chart_type="bar",
        x_axis="capitulo",
        y_axis="importe",
        title="Ejecución del presupuesto 2025",
        x_label="Capítulo presupuestario",
        y_label="Importe (€)",
        show_values=True,
        sort="desc",
        show_legend=False,
        show_grid=False,
        size=(8.0, 4.5),
    )
    convertida = ChartHandler._to_chart_config(cfg)

    assert convertida.title == "Ejecución del presupuesto 2025"
    assert convertida.x_label == "Capítulo presupuestario"
    assert convertida.y_label == "Importe (€)"
    assert convertida.show_values is True
    assert convertida.sort == "desc"
    assert convertida.show_legend is False
    assert convertida.show_grid is False
    assert tuple(convertida.size) == (8.0, 4.5)


def test_show_values_pinta_las_cifras_encima_de_las_barras(datos: pd.DataFrame) -> None:
    """Un campo del contrato que no hace nada es peor que no tenerlo."""
    svc = DeterministicChartService()
    con_cifras = svc.render_figure(
        datos,
        ChartConfiguration(
            chart_type="bar", x_column="capitulo", y_column="importe", show_values=True
        ),
    )
    etiquetas = [t.get_text() for t in con_cifras.axes[0].texts]
    assert etiquetas, "show_values=True no ha escrito ninguna cifra"
    assert any("500" in t for t in etiquetas)
    # Un informe de aquí escribe 340,50 — no 340.50. Esto no lo cazó ningún test: se vio
    # mirando el PNG, y hasta entonces las cifras salían en formato inglés.
    assert any("340,50" in t for t in etiquetas), etiquetas

    sin_cifras = svc.render_figure(
        datos,
        ChartConfiguration(
            chart_type="bar", x_column="capitulo", y_column="importe", show_values=False
        ),
    )
    assert not [t.get_text() for t in sin_cifras.axes[0].texts if t.get_text()]


def test_sort_ordena_las_barras_de_mayor_a_menor(datos: pd.DataFrame) -> None:
    svc = DeterministicChartService()
    fig = svc.render_figure(
        datos,
        ChartConfiguration(
            chart_type="bar", x_column="capitulo", y_column="importe", sort="desc"
        ),
    )
    etiquetas_eje = [t.get_text() for t in fig.axes[0].get_xticklabels()]
    assert etiquetas_eje[0] == "Cap. 6"  # 500.0, el mayor
    assert etiquetas_eje[-1] == "Cap. 4"  # 80.25, el menor


def test_el_titulo_llega_a_la_figura(datos: pd.DataFrame) -> None:
    fig = DeterministicChartService().render_figure(
        datos,
        ChartConfiguration(
            chart_type="bar", x_column="capitulo", y_column="importe", title="Un título"
        ),
    )
    assert fig.axes[0].get_title() == "Un título"


# ----------------------------------------------------------------------
# 2. Los tipos usuales, sin modelo
# ----------------------------------------------------------------------

_TIPOS = {
    "bar": {"x_column": "capitulo", "y_column": "importe"},
    "barh": {"x_column": "capitulo", "y_column": "importe"},
    "bar_stacked": {"x_column": "anyo", "y_column": "importe", "color_column": "capitulo"},
    "line": {"x_column": "anyo", "y_column": "importe"},
    "pie": {"label_column": "capitulo", "value_column": "importe"},
    "donut": {"label_column": "capitulo", "value_column": "importe"},
    "scatter": {"x_column": "ejecucion", "y_column": "importe"},
    "bubble": {"x_column": "ejecucion", "y_column": "importe", "size_column": "importe"},
    "histogram": {"x_column": "importe", "bins": 4},
    "boxplot": {"x_column": "anyo", "y_column": "importe"},
    "heatmap": {"x_column": "anyo", "y_column": "capitulo", "value_column": "importe"},
}


@pytest.mark.parametrize("tipo", sorted(_TIPOS))
def test_cada_tipo_renderiza_una_imagen_de_verdad(tipo: str, datos: pd.DataFrame) -> None:
    imagen = DeterministicChartService().render(
        datos, ChartConfiguration(chart_type=tipo, **_TIPOS[tipo])
    )
    assert imagen.startswith(b"\x89PNG"), f"{tipo} no devolvió un PNG"
    assert len(imagen) > 2_000, f"{tipo} devolvió un lienzo sospechosamente vacío"


@pytest.mark.parametrize("tipo", sorted(_TIPOS))
def test_la_plantilla_puede_pedir_cualquiera_de_los_tipos(tipo: str) -> None:
    """El Literal de `ChartBlockConfig` tiene que cubrir lo mismo que el renderizador."""
    assert ChartBlockConfig(chart_type=tipo).chart_type == tipo


def test_barh_pone_la_categoria_en_el_eje_y(datos: pd.DataFrame) -> None:
    """`barh` es `bar` con las columnas en el otro eje, y **quien lo dice es la configuración**.

    GUI.4 — este test exigía lo contrario: que `x_column` fuera la categoría en los dos tipos y
    que el renderizador cruzara los ejes por detrás. Esa convención se cayó en la primera
    petición real: el modelo puso el valor en `x_axis` —porque su `x_label` habla del eje X, que
    es lo que dice el nombre— y los dos cruces se anularon. El gráfico salió vertical, con el
    índice en el eje y las etiquetas al revés.
    """
    svc = DeterministicChartService()
    vertical = svc.render_figure(
        datos, ChartConfiguration(chart_type="bar", x_column="capitulo", y_column="importe")
    )
    horizontal = svc.render_figure(
        datos, ChartConfiguration(chart_type="barh", x_column="importe", y_column="capitulo")
    )
    vertical.canvas.draw()
    horizontal.canvas.draw()
    assert [t.get_text() for t in vertical.axes[0].get_xticklabels()][0] == "Cap. 1"
    assert [t.get_text() for t in horizontal.axes[0].get_yticklabels()][0] == "Cap. 1"


def test_los_graficos_de_exploracion_estadistica_se_quedan_fuera() -> None:
    """`violin` y `pairplot` no entran: `pairplot` devuelve un grid que no cabe en `fig, ax`."""
    for excluido in ("violin", "pairplot"):
        with pytest.raises(ValueError, match="chart_type"):
            ChartConfiguration(chart_type=excluido)


def test_el_eje_numerico_separa_los_millares(datos: pd.DataFrame) -> None:
    """`120.000` en el eje, no `120000`."""
    fig = DeterministicChartService().render_figure(
        pd.DataFrame({"c": ["A", "B"], "v": [120000.0, 45000.0]}),
        ChartConfiguration(chart_type="bar", x_column="c", y_column="v"),
    )
    fig.canvas.draw()
    etiquetas = [t.get_text() for t in fig.axes[0].get_yticklabels()]
    assert any("120.000" == t for t in etiquetas), etiquetas


def test_una_hoja_en_ingles_puede_pedir_su_convencion(datos: pd.DataFrame) -> None:
    fig = DeterministicChartService().render_figure(
        datos,
        ChartConfiguration(
            chart_type="bar", x_column="capitulo", y_column="importe",
            show_values=True, number_format="en",
        ),
    )
    assert any("340.50" in t.get_text() for t in fig.axes[0].texts)
