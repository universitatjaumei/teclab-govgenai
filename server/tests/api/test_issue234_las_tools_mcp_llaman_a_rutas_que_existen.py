"""#234 — las herramientas MCP sólo llaman a rutas que existen.

**Cómo salió.** Haciendo #214: `list_clients` llamaba a `/api/v1/hub/clients`, una ruta que no
existía desde el renombrado a «organización», y respondía 404 siempre. Sus tests pasaban, porque
simulaban con `respx` la ruta que la herramienta creía que existía. Lo mismo con el filtro de
`list_chatbots`, que buscaba un campo `client_id` que el contrato ya llama `organizacion_id`: con
filtro, la lista salía vacía siempre.

El servidor MCP no importa `server/app` (es otro despliegue), así que el cruce se hace aquí: cada
ruta escrita en `mcp_server/` tiene que estar en la aplicación.
"""
from __future__ import annotations

import re
from pathlib import Path

from server.app.api import deps
from server.tests.api.test_issue214_un_token_solo_donde_se_declara import _rutas

MCP = Path(__file__).resolve().parents[3] / "mcp_server"
_RUTA_EN_EL_CODIGO = re.compile(r'"/api/v1(/[^"]*)"')


def _normaliza(ruta: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", ruta)


def _las_del_mcp() -> dict[str, str]:
    encontradas: dict[str, str] = {}
    for fichero in MCP.rglob("*.py"):
        if "tests" in fichero.parts:
            continue
        for ruta in _RUTA_EN_EL_CODIGO.findall(fichero.read_text(encoding="utf-8")):
            encontradas[_normaliza(ruta)] = fichero.relative_to(MCP).as_posix()
    return encontradas


def test_el_mcp_llama_a_alguna_ruta():
    """Que el guardarraíl mire algo: sin rutas encontradas, pasaría en verde sin comprobar nada."""
    assert len(_las_del_mcp()) > 20


def test_toda_ruta_que_llama_el_mcp_existe():
    existentes = {_normaliza(r.path) for r in _rutas()}
    faltan = {ruta: donde for ruta, donde in _las_del_mcp().items() if ruta not in existentes}
    assert not faltan, f"Rutas que el MCP llama y el servidor no tiene: {faltan}"


def test_las_organizaciones_se_leen_con_chatbots_read():
    """`create_chatbot` pide la organización: el agente tiene que poder saber cuáles hay."""
    for ruta in _rutas():
        if ruta.path == "/hub/organizaciones" and "GET" in ruta.methods:
            assert "chatbots:read" in deps.alcances_de_la_ruta(ruta)
            return
    raise AssertionError("no existe GET /hub/organizaciones")
