"""#274 — en los routers grandes, el handler traduce HTTP y la lógica vive en un servicio.

Medido el 2026-10-25: `agentes_router.py` tenía 33 operaciones `session.*` en 2.024 líneas,
`hub_ingestion_router.py` 31, `hub_users_router.py` 30, `hub_chatbots_router.py` 25,
`hub_sites_router.py` 22 y `redaccion/funciones_router.py` 19. Un handler que consulta, decide y
escribe no se puede probar sin HTTP ni reutilizar desde otro sitio —el servidor MCP, un trabajo de
fondo—, y por eso cada uno acababa con su copia de la misma consulta. `chat_stream` y
`ejecutar_funcion_por_api` salieron primero (da9eb072); éstos son el resto.

El test cuenta llamadas a la sesión en el fichero del router. **Cero**, no «pocas»: un techo deja
crecer lo que vigila hasta el techo, y la regla es que la base se toca en el servicio.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROUTERS = Path(__file__).resolve().parents[2] / "app" / "routers"

VIGILADOS = (
    "agentes_router.py",
    "hub_ingestion_router.py",
    "hub_users_router.py",
    "hub_chatbots_router.py",
    "hub_chatbots_corpus_router.py",
    "hub_organizaciones_router.py",
    "hub_sites_router.py",
    "redaccion/funciones_router.py",
)

_OPERACIONES = {
    "execute", "get", "add", "add_all", "delete", "commit", "refresh", "flush",
    "scalar", "scalars", "rollback", "merge", "exec",
}


def _llamadas_a_la_sesion(ruta: Path) -> list[str]:
    encontradas = []
    for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
        if (
            isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Attribute)
            and nodo.func.attr in _OPERACIONES
            and isinstance(nodo.func.value, ast.Name)
            and nodo.func.value.id in {"session", "sesion", "db"}
        ):
            encontradas.append(f"{ruta.name}:{nodo.lineno} {ast.unparse(nodo.func)}")
    return encontradas


def test_el_detector_ve_una_llamada_a_la_sesion(tmp_path):
    """Sanidad del medidor: si no viera nada, el test de abajo pasaría sin mirar."""
    falso = tmp_path / "r.py"
    falso.write_text("async def h(session):\n    await session.execute(1)\n", encoding="utf-8")
    assert _llamadas_a_la_sesion(falso) == ["r.py:2 session.execute"]


@pytest.mark.parametrize("router", VIGILADOS)
def test_el_router_no_toca_la_base(router):
    ruta = ROUTERS / router
    assert ruta.is_file(), f"{router} no existe: corrige la lista"
    llamadas = _llamadas_a_la_sesion(ruta)
    assert llamadas == [], (
        f"{router} toca la base desde el handler: {llamadas}. La consulta va a un servicio, y el "
        "router le pasa la sesión."
    )
