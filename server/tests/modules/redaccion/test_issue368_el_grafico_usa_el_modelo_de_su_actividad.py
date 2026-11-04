"""#368 — el nodo de gráficos usa el modelo de `configuracion_de_grafico`, no el del ETL.

El mismo defecto que #366, un nodo más allá: `ChartRenderNode` recibía `etl_llm`, resuelto para
`transformacion_etl`, así que subir el nivel de los gráficos en la biblioteca de prompts no
llegaba al modelo y el gráfico registraba el modelo de la transformación.

El prompt de la actividad **no** entra aquí, y es a propósito: dentro del informe el nodo pide un
script (`ChartFactory.generate_script`, con su prompt propio) y el texto de
`configuracion_de_grafico` es el del camino declarativo, que hoy sólo usa el copiloto —y ése ya
lo resuelve—. Lo que el informe tiene que respetar es el nivel y la organización.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.modules.redaccion.services.actividades_llm import ActividadLLM


@pytest.mark.asyncio
async def test_ejecutar_borrador_pasa_al_grafo_el_modelo_de_los_graficos(monkeypatch) -> None:
    from server.app.modules.redaccion.services import drafting_runner

    organizacion = uuid.uuid4()
    workspace = SimpleNamespace(organizacion_id=organizacion, template_version_id=uuid.uuid4())

    def _repo(devuelve):
        return lambda _session: SimpleNamespace(get=AsyncMock(return_value=devuelve))

    pedidas: list = []

    async def _resolver(_session, actividad, *, organizacion_id):
        pedidas.append((actividad, organizacion_id))
        return f"modelo-{actividad}", f"nombre-{actividad}", f"prompt-{actividad}"

    construido: dict = {}

    def _construir_grafo(_session, _llm, _storage=None, **kwargs):
        construido.update(kwargs)
        raise RuntimeError("basta con saber con qué se construyó")

    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = []
    sesion = SimpleNamespace(execute=AsyncMock(return_value=resultado))

    monkeypatch.setattr(drafting_runner, "WorkspaceRepo", _repo(workspace))
    monkeypatch.setattr(
        drafting_runner, "ReportTemplateVersionRepo", _repo(SimpleNamespace(spec_json={}))
    )
    monkeypatch.setattr(
        drafting_runner, "ReportTemplateSpec", SimpleNamespace(model_validate=lambda _d: None)
    )
    monkeypatch.setattr(drafting_runner, "resolver_modelo_de_actividad", _resolver)
    monkeypatch.setattr(drafting_runner, "construir_grafo", _construir_grafo)
    monkeypatch.setattr(drafting_runner, "marcar_error", AsyncMock())

    await drafting_runner.ejecutar_borrador(uuid.uuid4(), sesion, llm_service=object())

    grafico = ActividadLLM.CONFIGURACION_DE_GRAFICO
    assert (grafico, organizacion) in pedidas
    assert construido["chart_llm"] == f"modelo-{grafico}"
    assert construido["chart_model_name"] == f"nombre-{grafico}"
    etl = ActividadLLM.TRANSFORMACION_ETL
    assert construido["etl_llm"] == f"modelo-{etl}"


def test_el_nodo_de_graficos_recibe_su_modelo_y_no_el_del_etl(monkeypatch) -> None:
    from server.app.modules.redaccion.graph import core_graph

    recibido: dict = {}

    class _Nodo:
        def __init__(self, **kwargs):
            recibido.update(kwargs)

        async def __call__(self, _state):
            return {}

    monkeypatch.setattr(core_graph, "ChartRenderNode", _Nodo)

    core_graph.build_core_graph(
        template_version_repo=MagicMock(),
        storage_service=MagicMock(),
        extraction_factory=MagicMock(),
        llm_service=MagicMock(),
        etl_llm="modelo-etl",
        etl_model_name="nombre-etl",
        chart_llm="modelo-grafico",
        chart_model_name="nombre-grafico",
    )

    assert recibido["llm_service"] == "modelo-grafico"
    assert recibido["model_name"] == "nombre-grafico"


@pytest.mark.asyncio
async def test_subir_el_nivel_de_los_graficos_llega_al_modelo(monkeypatch) -> None:
    from server.app.modules.agents_hub.services import config_provider, model_factory
    from server.app.modules.redaccion.services.drafting_runner import (
        resolver_modelo_de_actividad,
    )

    organizacion = uuid.uuid4()

    class _Proveedor:
        async def get_activity_prompt(self, activity, *, organizacion_id=None):
            if activity == "configuracion_de_grafico":
                return SimpleNamespace(template_text=None, override_tier=3)
            return None

    pedidos: list = []

    async def _modelo_por_nivel(tier, _proveedor, *, organizacion_id):
        pedidos.append((tier, organizacion_id))
        return SimpleNamespace(model_name=f"modelo-nivel-{tier}")

    monkeypatch.setattr(config_provider, "LocalConfigProvider", lambda _s: _Proveedor())
    monkeypatch.setattr(model_factory, "get_model_for_tier", _modelo_por_nivel)

    _, nombre, _ = await resolver_modelo_de_actividad(
        object(), ActividadLLM.CONFIGURACION_DE_GRAFICO, organizacion_id=organizacion
    )

    assert pedidos == [(3, organizacion)]
    assert nombre == "modelo-nivel-3"


# ----------------------------------------------------------------------
# Lo que vio la revisión de la PR #369
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_grafico_de_ia_registra_el_modelo_que_lo_dibujo(monkeypatch) -> None:
    """Llevar el nombre hasta el nodo no servía de nada: `ChartHandler` descartaba
    `model_used`, y el bloque no decía con qué modelo se dibujó."""
    from server.app.modules.redaccion.blocks import handlers
    from server.app.modules.redaccion.graph.nodes.chart_render import ChartRenderNode
    from server.tests.dobles import modelo_de_chat
    from server.tests.modules.redaccion.charts.test_el_grafico_llega_al_informe import (
        _AlmacenEnMemoria,
        _estado,
        _spec_con_grafico,
    )

    llm = modelo_de_chat()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="```python\nplt.bar([1], [2])\n```"))
    monkeypatch.setattr(handlers, "render_chart_from_script", AsyncMock(return_value=b"png"))

    salida = await ChartRenderNode(
        storage_service=_AlmacenEnMemoria(), llm_service=llm, model_name="modelo-nivel-3"
    )(_estado(_spec_con_grafico(mode="ai")))

    bloque = salida["blocks"]["b-grafico"]
    assert bloque.status == "extracted"
    assert bloque.content["chart"]["model_used"] == "modelo-nivel-3"


@pytest.mark.asyncio
async def test_sin_modelo_el_grafico_de_ia_falla_diciendo_por_que() -> None:
    """Fallaba con «'NoneType' object has no attribute 'ainvoke'», que no dice que lo que
    falta es un modelo configurado para el nivel de los gráficos."""
    from server.app.modules.redaccion.graph.nodes.chart_render import ChartRenderNode
    from server.tests.modules.redaccion.charts.test_el_grafico_llega_al_informe import (
        _AlmacenEnMemoria,
        _estado,
        _spec_con_grafico,
    )

    salida = await ChartRenderNode(storage_service=_AlmacenEnMemoria(), llm_service=None)(
        _estado(_spec_con_grafico(mode="ai"))
    )

    bloque = salida["blocks"]["b-grafico"]
    assert bloque.status == "failed"
    assert "configuracion_de_grafico" in (bloque.last_error_message or "")
    assert "NoneType" not in (bloque.last_error_message or "")
