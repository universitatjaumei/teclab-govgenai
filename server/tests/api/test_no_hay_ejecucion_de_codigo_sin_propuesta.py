"""El único camino para ejecutar un guion escrito por alguien es la propuesta de script.

`POST /redaccion/charts/preview/script` ejecutaba en el sandbox el código que llegaba en la
petición —en la *query string*, así que además quedaba en los registros de acceso— con sólo el
módulo de informes, sin propuesta, sin auditoría registrada y sin revisión. No lo usaba nada: ni
una pantalla, ni el servidor MCP, ni un test. Se retira.

Los gráficos con código siguen existiendo por el camino gobernado: el bloque de gráfico en modo
IA genera el guion y lo audita (`ChartHandler`), y el código de una persona entra por la
propuesta de script.

Las rutas se leen del esquema OpenAPI y no de `app.routes`: con esta versión de FastAPI los
routers incluidos aparecen como `_IncludedRouter` y no se aplanan, así que mirar `app.routes`
no veía ninguna ruta de gráficos y los dos tests pasaban o fallaban sin medir nada.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def rutas() -> set[str]:
    from server.app.main import app

    return set(app.openapi()["paths"])


def test_the_meter_sees_the_chart_routes(rutas):
    assert any("/redaccion/charts/" in r for r in rutas), "no se ve ninguna ruta de gráficos"


def test_should_not_expose_a_raw_script_preview(rutas):
    assert not any(r.endswith("/charts/preview/script") for r in rutas)


def test_should_keep_the_deterministic_preview(rutas):
    """Lo que no ejecuta código de nadie se queda."""
    assert any(r.endswith("/charts/preview/deterministic") for r in rutas)
