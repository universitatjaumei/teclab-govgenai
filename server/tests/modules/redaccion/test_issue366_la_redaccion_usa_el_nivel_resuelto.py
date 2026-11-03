"""#366 — la redacción usa el nivel y la organización que resuelve la biblioteca de prompts.

La biblioteca deja subir el nivel de `valoracion_de_tendencia` y `resumen_de_resultados`, y el
catálogo lo anuncia como «una decisión legítima de cada organización, que se puede tomar sin
desplegar». No llegaba al modelo: `_redactor_de_bloques` pedía siempre el nivel 1 y la
generación en segundo plano resolvía sin organización. Nada fallaba —el informe salía igual de
bien escrito con el modelo barato y el manifiesto lo registraba—, y por eso no lo cazaba nadie.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.app.modules.redaccion.services.redactor_de_bloques import (
    PROMPT_RESUMEN_DE_RESULTADOS,
    PROMPT_VALORACION_DE_TENDENCIA,
    RedactorDeBloques,
)
from server.tests.dobles import modelo_de_chat


def _modelo(texto: str):
    modelo = modelo_de_chat()
    modelo.ainvoke = AsyncMock(return_value=SimpleNamespace(content=texto))
    return modelo


# ----------------------------------------------------------------------
# El redactor: un modelo por instrucción
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cada_instruccion_va_al_modelo_de_su_actividad() -> None:
    barato, superior = _modelo("del barato"), _modelo("del superior")
    redactor = RedactorDeBloques(
        barato,
        "modelo-nivel-1",
        modelos={PROMPT_VALORACION_DE_TENDENCIA: (superior, "modelo-nivel-3")},
    )

    valoracion = await redactor.generate(prompt=PROMPT_VALORACION_DE_TENDENCIA, context="t")
    resumen = await redactor.generate(prompt=PROMPT_RESUMEN_DE_RESULTADOS, context="t")

    assert valoracion == "del superior"
    assert resumen == "del barato"


def test_el_nombre_del_modelo_es_el_de_quien_redacta_ese_bloque() -> None:
    """`model_used` va al manifiesto: con dos modelos, un solo nombre mentiría en uno."""
    redactor = RedactorDeBloques(
        _modelo(""),
        "modelo-nivel-1",
        modelos={PROMPT_VALORACION_DE_TENDENCIA: (_modelo(""), "modelo-nivel-3")},
    )

    assert redactor.nombre_del_modelo_para(PROMPT_VALORACION_DE_TENDENCIA) == "modelo-nivel-3"
    assert redactor.nombre_del_modelo_para(PROMPT_RESUMEN_DE_RESULTADOS) == "modelo-nivel-1"
    assert redactor.nombre_del_modelo_para("generic_report_v1") == "modelo-nivel-1"


# ----------------------------------------------------------------------
# El nodo registra el modelo de cada bloque
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_nodo_registra_el_modelo_que_redacto_cada_bloque() -> None:
    from server.tests.modules.redaccion.test_valoracion_anclada_a_su_tabla import (
        _apartado,
        _estado,
        _spec,
    )
    from server.app.modules.redaccion.contracts.blocks import AIAssistedTextBlock
    from server.app.modules.redaccion.graph.nodes.ai_assist_draft import AIAssistDraftNode

    spec = _spec(
        AIAssistedTextBlock(
            id="valoracion", title="Valoración",
            ai_prompt_template_id=PROMPT_VALORACION_DE_TENDENCIA, review_policy_id="required",
        ),
        AIAssistedTextBlock(
            id="resumen", title="Resumen",
            ai_prompt_template_id=PROMPT_RESUMEN_DE_RESULTADOS, review_policy_id="required",
        ),
    )
    estado = _estado(spec, {
        "valoracion": _apartado("valoracion"),
        "resumen": _apartado("resumen"),
    })
    redactor = RedactorDeBloques(
        _modelo("texto"),
        "modelo-nivel-1",
        modelos={PROMPT_VALORACION_DE_TENDENCIA: (_modelo("texto"), "modelo-nivel-3")},
    )

    salida = await AIAssistDraftNode(redactor)(estado)

    assert salida["blocks"]["valoracion"].content["model_used"] == "modelo-nivel-3"
    assert salida["blocks"]["resumen"].content["model_used"] == "modelo-nivel-1"


# ----------------------------------------------------------------------
# La resolución: nivel de la biblioteca y organización del informe
# ----------------------------------------------------------------------


class _Proveedor:
    """Un `ConfigProvider` con overrides de actividad y un modelo por nivel."""

    def __init__(self, overrides: dict[str, int]):
        self._overrides = overrides
        self.organizaciones_pedidas: list = []

    async def get_activity_prompt(self, activity, *, organizacion_id=None):
        self.organizaciones_pedidas.append(organizacion_id)
        tier = self._overrides.get(activity)
        if tier is None:
            return None
        return SimpleNamespace(template_text=None, override_tier=tier)


@pytest.fixture
def niveles(monkeypatch):
    """Sustituye proveedor y fábrica: devuelve un modelo distinto por nivel y anota quién pide."""
    from server.app.modules.agents_hub.services import config_provider, model_factory

    estado = SimpleNamespace(proveedor=None, pedidos=[])

    def _proveedor(_session):
        return estado.proveedor

    async def _modelo_por_nivel(tier, _proveedor, *, organizacion_id):
        estado.pedidos.append((tier, organizacion_id))
        modelo = _modelo(f"nivel {tier}")
        modelo.model_name = f"modelo-nivel-{tier}"
        return modelo

    monkeypatch.setattr(config_provider, "LocalConfigProvider", _proveedor)
    monkeypatch.setattr(model_factory, "get_model_for_tier", _modelo_por_nivel)
    return estado


@pytest.mark.asyncio
async def test_subir_el_nivel_de_la_valoracion_llega_al_modelo(niveles) -> None:
    """Es el defecto: el nivel se resolvía y se descartaba."""
    from server.app.routers.redaccion.workspaces_router import _redactor_de_bloques

    niveles.proveedor = _Proveedor({"valoracion_de_tendencia": 3})

    redactor = await _redactor_de_bloques(object(), organizacion_id=None)

    assert await redactor.generate(PROMPT_VALORACION_DE_TENDENCIA, "t") == "nivel 3"
    assert await redactor.generate(PROMPT_RESUMEN_DE_RESULTADOS, "t") == "nivel 1"


@pytest.mark.asyncio
async def test_sin_overrides_todo_sigue_en_el_nivel_1(niveles) -> None:
    from server.app.routers.redaccion.workspaces_router import _redactor_de_bloques

    niveles.proveedor = _Proveedor({})

    redactor = await _redactor_de_bloques(object(), organizacion_id=None)

    assert {tier for tier, _ in niveles.pedidos} == {1}
    assert redactor.nombre_del_modelo_para(PROMPT_VALORACION_DE_TENDENCIA) == "modelo-nivel-1"


@pytest.mark.asyncio
async def test_el_modelo_y_el_prompt_se_resuelven_con_la_organizacion(niveles) -> None:
    from server.app.routers.redaccion.workspaces_router import _redactor_de_bloques

    organizacion = uuid.uuid4()
    niveles.proveedor = _Proveedor({"resumen_de_resultados": 2})

    await _redactor_de_bloques(object(), organizacion_id=organizacion)

    assert {org for _, org in niveles.pedidos} == {organizacion}
    assert set(niveles.proveedor.organizaciones_pedidas) == {organizacion}


@pytest.mark.asyncio
async def test_la_generacion_en_segundo_plano_usa_la_organizacion_del_informe(monkeypatch) -> None:
    """Pasaba `None` con un comentario de antes de MT.4: el informe ya tiene organización."""
    import server.app.routers.redaccion.workspaces_router as router_modulo
    from server.app.modules.redaccion.services import drafting_runner

    organizacion = uuid.uuid4()
    workspace = SimpleNamespace(organizacion_id=organizacion)
    sesion = SimpleNamespace(get=AsyncMock(return_value=workspace))

    async def _sesiones():
        yield sesion

    pedidas: list = []

    async def _redactor(_session, *, organizacion_id):
        pedidas.append(organizacion_id)
        return object()

    monkeypatch.setattr(router_modulo, "get_session", _sesiones)
    monkeypatch.setattr(router_modulo, "_redactor_de_bloques", _redactor)
    monkeypatch.setattr(drafting_runner, "ejecutar_borrador", AsyncMock())

    await router_modulo.generar_borrador_en_segundo_plano(uuid.uuid4())

    assert pedidas == [organizacion]


@pytest.mark.asyncio
async def test_el_etl_se_resuelve_con_la_organizacion(niveles) -> None:
    from server.app.modules.redaccion.services.drafting_runner import resolver_modelo_de_etl

    organizacion = uuid.uuid4()
    niveles.proveedor = _Proveedor({})

    await resolver_modelo_de_etl(object(), organizacion_id=organizacion)

    assert niveles.proveedor.organizaciones_pedidas == [organizacion]
    assert niveles.pedidos == [(2, organizacion)]
