"""#261 — el barrido de fuentes huérfanas sólo corre donde la lista de chatbots manda.

El barrido de #258 borra `ingestion/{chatbot}/` de los chatbots que no encuentra. En un edge, la
configuración llega por sincronización: si `hub_chatbots` estuviera incompleto, vería huérfanas las
fuentes de chatbots vivos y las borraría sin vuelta atrás. Preguntar a `ConfigProvider` no lo
arregla, porque el local lee esa misma tabla. Decisión del 2026-10-29: **sólo con
`DEPLOY_MODE=all`**. En `cloud` no hay fuentes de ingesta que barrer.

El camino bueno —con `all` sí borra— lo cubre `test_issue258_lo_que_no_se_pudo_borrar.py`.
"""
from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

from server.app.modules.agents_hub.services import corpus_purge


class _AlmacenQueApunta:
    def __init__(self, nombres):
        self._nombres = nombres
        self.borrados: list[str] = []

    async def listar(self, _prefijo):
        return self._nombres

    async def delete_prefix(self, prefijo):
        self.borrados.append(prefijo)


class _SesionQueNoSeToca:
    async def execute(self, _consulta):
        raise AssertionError("fuera de `all` el barrido no pregunta qué chatbots existen")


@pytest.mark.asyncio
@pytest.mark.parametrize("modo", ["edge", "cloud", "EDGE"])
async def test_fuera_de_all_el_barrido_no_borra_nada(monkeypatch, modo):
    monkeypatch.setenv("DEPLOY_MODE", modo)
    almacen = _AlmacenQueApunta([str(uuid.uuid4())])

    retirados = await corpus_purge.barrer_fuentes_huerfanas(_SesionQueNoSeToca(), almacen)

    assert retirados == 0
    assert almacen.borrados == []


def test_el_barrido_pregunta_por_config_provider_y_no_por_el_modelo():
    """AGENTS.md: los servicios edge leen la configuración por `ConfigProvider`."""
    arbol = ast.parse(Path(corpus_purge.__file__).read_text(encoding="utf-8"))
    importados = {
        alias.name
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.ImportFrom)
        for alias in nodo.names
    }
    assert "HubChatbot" not in importados
