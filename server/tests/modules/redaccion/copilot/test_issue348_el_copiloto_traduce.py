"""#348 — los modos de traducción del Copilot (gráfico, ETL, script) daban siempre un 500.

`get_copilot_service` construía el servicio sin ninguna de las tres fábricas, y
`translate_nl_to_config` empieza comprobando la suya: `ValueError`, sin recoger, en cada petición.
Los tests de `test_copilot.py` montaban el servicio a mano con la fábrica puesta, así que nunca
pasaron por la dependencia real. Estos van **por HTTP** y sin sustituir la construcción: lo único
falso son los modelos y la biblioteca de prompts.

Cada modo usa el modelo **de su actividad** —gráfico y ETL son nivel 2; el script, 2 para escribir
y 3 para auditar— y no el del nivel 1 con el que responde el modo pregunta. Tampoco necesita el
servicio de embeddings, que sólo sirve para buscar en la documentación.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from server.app.core.auth.models import UserInfo

pytestmark = pytest.mark.asyncio


class _Respuesta:
    def __init__(self, texto: str) -> None:
        self.content = texto


class _Modelo:
    def __init__(self, nombre: str, texto: str) -> None:
        self.model = nombre
        self._texto = texto
        self.llamadas = 0

    async def ainvoke(self, messages):
        self.llamadas += 1
        return _Respuesta(self._texto)


class _ModeloRetirado:
    model = "gemini-2.0-flash"

    async def ainvoke(self, messages):
        raise RuntimeError("404 NOT_FOUND. models/gemini-2.0-flash is no longer available.")


_GRAFICO = json.dumps({"configuration": {"chart_type": "bar", "x_column": "region", "y_column": "total"}})
_ETL = json.dumps(
    {"mode": "operations", "operations": [{"op": "groupby", "cols": ["mes"], "agg_dict": {"importe": "sum"}}]}
)
_SCRIPT = "```python\ndef extract(df):\n    return df.head()\n```"
_VEREDICTO = json.dumps({"veredicto": "sin_riesgo", "motivos": []})


@pytest.fixture
def niveles(monkeypatch):
    """Qué modelo devuelve cada nivel, y qué niveles se pidieron.

    La biblioteca de prompts devuelve el texto del código: es la que habría sin filas de override.
    """
    from server.app.modules.redaccion.services import actividades_llm
    from server.app.routers.redaccion import scripts_router

    modelos: dict[int, object] = {}
    pedidos: list[int] = []

    async def _resolver(actividad, _proveedor, **_k):
        return actividades_llm.ActividadResuelta(
            actividad=actividad,
            tier=actividades_llm.tier_de(actividad),
            template_text=actividades_llm.PROMPT_POR_ACTIVIDAD[actividad],
            origen_del_tier="codigo",
            origen_del_texto="codigo",
        )

    async def _modelo(tier, _proveedor, **_k):
        pedidos.append(tier)
        if tier not in modelos:
            raise ValueError(f"no hay configuración LLM por defecto para tier {tier}")
        return modelos[tier]

    monkeypatch.setattr(scripts_router, "resolver_actividad", _resolver)
    monkeypatch.setattr(scripts_router, "get_model_for_tier", _modelo)
    return modelos, pedidos


@pytest.fixture(autouse=True)
def sin_embeddings(monkeypatch):
    """Traducir no busca en la documentación: si pidiera embeddings, esto lo tumbaría."""
    from server.app.routers.redaccion import copilot_router

    async def _no(*_a, **_k):
        raise AssertionError("el modo traducción no necesita embeddings")

    monkeypatch.setattr(copilot_router, "resolve_embedding_service", _no)
    monkeypatch.setattr(copilot_router, "_retriever", None)


def _app() -> FastAPI:
    from server.app.api.deps import get_current_user, get_session, modulos_concedidos
    from server.app.core.errores import instalar_errores
    from server.app.routers.redaccion.copilot_router import router

    app = FastAPI()
    instalar_errores(app)
    app.dependency_overrides[get_current_user] = lambda: UserInfo(
        user_id="u1", email="u@uji.es", role="admin", organizacion_ids=()
    )
    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[modulos_concedidos] = lambda: ["informes"]
    app.include_router(router, prefix="/api/v1")
    return app


async def _traducir(target_kind: str, instruccion: str = "Total por región"):
    transporte = ASGITransport(app=_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transporte, base_url="http://t") as c:
        return await c.post(
            "/api/v1/redaccion/copilot/translate",
            json={
                "instruction": instruccion,
                "target_kind": target_kind,
                "sample_schema": {"columns": ["region", "total", "mes", "importe"]},
            },
        )


async def test_el_modo_grafico_devuelve_una_configuracion(niveles) -> None:
    modelos, pedidos = niveles
    modelos[2] = _Modelo("gemini-2.5-flash", _GRAFICO)

    r = await _traducir("chart_config")

    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "chart_config"
    assert r.json()["payload"]["configuration"]["chart_type"] == "bar"
    assert pedidos == [2], "el gráfico es nivel 2, no el nivel 1 del modo pregunta"


async def test_el_modo_etl_devuelve_operaciones(niveles) -> None:
    modelos, pedidos = niveles
    modelos[2] = _Modelo("gemini-2.5-flash", _ETL)

    r = await _traducir("etl_ops", "Agrupa por mes y suma el importe")

    assert r.status_code == 200, r.text
    assert r.json()["payload"]["operations"][0]["op"] == "groupby"
    assert pedidos == [2]


async def test_el_modo_script_escribe_con_un_nivel_y_audita_con_otro(niveles) -> None:
    modelos, pedidos = niveles
    modelos[2] = _Modelo("gemini-2.5-flash", _SCRIPT)
    modelos[3] = _Modelo("gemini-2.5-pro", _VEREDICTO)

    r = await _traducir("script_proposal", "Las cinco primeras filas")

    assert r.status_code == 200, r.text
    assert "def extract" in r.json()["payload"]["code"]
    assert sorted(pedidos) == [2, 3]


async def test_solo_se_resuelve_el_modelo_del_modo_pedido(niveles) -> None:
    """Sin modelo de nivel 3, el gráfico funciona igual: no depende de lo que no usa."""
    modelos, _ = niveles
    modelos[2] = _Modelo("gemini-2.5-flash", _GRAFICO)

    r = await _traducir("chart_config")

    assert r.status_code == 200, r.text


async def test_sin_modelo_del_nivel_es_un_503_que_dice_cual(niveles) -> None:
    r = await _traducir("etl_ops")

    assert r.status_code == 503, r.text
    assert "nivel 2" in r.text
    assert "Modelos IA" in r.text


async def test_un_modelo_que_no_responde_es_un_502_que_dice_cual(niveles, caplog) -> None:
    modelos, _ = niveles
    modelos[2] = _ModeloRetirado()

    with caplog.at_level("WARNING"):
        r = await _traducir("chart_config")

    assert r.status_code == 502, r.text
    assert "gemini-2.0-flash" in r.json()["detail"]["message"]
    assert "no longer available" not in r.text, "el texto del proveedor va al registro"
    assert "no longer available" in caplog.text
