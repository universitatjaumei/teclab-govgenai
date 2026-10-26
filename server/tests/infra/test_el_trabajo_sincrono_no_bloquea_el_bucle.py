"""#274 — leer un Excel, buscar datos personales o escribir a disco no se hace en el bucle.

Una función `async` que llama a `pd.read_excel` no espera a nadie: bloquea el proceso entero
mientras pandas lee, y con un solo trabajador de uvicorn eso es **todas** las peticiones —el
chat, el panel, el login— paradas detrás de un fichero. La auditoría del 2026-10-21 encontró
tres sitios en camino de petición; `utilidades_router.py` ya lo hacía bien con
`asyncio.to_thread`, que es lo que se pide aquí.

El test recorre las funciones `async` de esos ficheros y comprueba que las llamadas que bloquean
sólo aparecen como **argumento** de `asyncio.to_thread`, nunca llamadas directamente. Las
funciones síncronas auxiliares pueden llamarlas: para eso existen.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"

#: Fichero → llamadas que bloquean y que no pueden ir directas en una función `async`.
VIGILADOS: dict[str, set[str]] = {
    "routers/redaccion/llm_drafts_router.py": {"resumen_de_la_muestra"},
    "modules/redaccion/services/test_data_anonymizer.py": {
        "_read_dataframe",
        "_write_dataframe",
        "scan_dataframe",
        "detect_spans",
        "extraer_paginas",
    },
    "modules/redaccion/graph/nodes/file_normalization.py": {"write_bytes"},
    "routers/redaccion/charts_router.py": {"render"},
}


def _nombre(llamada: ast.Call) -> str | None:
    if isinstance(llamada.func, ast.Name):
        return llamada.func.id
    if isinstance(llamada.func, ast.Attribute):
        return llamada.func.attr
    return None


def _llamadas_directas(funcion: ast.AsyncFunctionDef, prohibidas: set[str]) -> list[str]:
    """Las llamadas prohibidas que se ejecutan en el bucle, sin pasar por `to_thread`.

    `asyncio.to_thread(f, x)` no llama a `f`: la recibe como argumento. Por eso basta con mirar
    los nodos `Call` cuyo nombre está en la lista — si va por `to_thread`, es un `Name` o un
    `Attribute` suelto, no una llamada.
    """
    return [
        f"{funcion.name}:{nodo.lineno} {_nombre(nodo)}"
        for nodo in ast.walk(funcion)
        if isinstance(nodo, ast.Call) and _nombre(nodo) in prohibidas
    ]


def _funciones_async(ruta: Path) -> list[ast.AsyncFunctionDef]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    return [n for n in ast.walk(arbol) if isinstance(n, ast.AsyncFunctionDef)]


@pytest.mark.parametrize("relativa", sorted(VIGILADOS))
def test_el_fichero_vigilado_existe_y_tiene_funciones_async(relativa: str) -> None:
    """Sin esto, renombrar un fichero dejaría su comprobación en verde sin mirar nada."""
    assert _funciones_async(APP / relativa), relativa


@pytest.mark.parametrize("relativa", sorted(VIGILADOS))
def test_nada_que_bloquea_va_directo_en_una_funcion_async(relativa: str) -> None:
    culpables = [
        c
        for funcion in _funciones_async(APP / relativa)
        for c in _llamadas_directas(funcion, VIGILADOS[relativa])
    ]
    assert not culpables, (
        f"{relativa}: trabajo síncrono dentro de una función async, en el bucle de eventos: "
        f"{culpables}. Va por `await asyncio.to_thread(...)`."
    )


def test_el_medidor_caza_una_llamada_directa() -> None:
    """Y que, si se escribe mal, lo ve: el caso que el test tiene que cazar."""
    arbol = ast.parse("async def f(x):\n    return pd.read_excel(x)\n")
    funcion = arbol.body[0]
    assert isinstance(funcion, ast.AsyncFunctionDef)
    assert _llamadas_directas(funcion, {"read_excel"})
    bien = ast.parse("async def f(x):\n    return await asyncio.to_thread(pd.read_excel, x)\n")
    assert not _llamadas_directas(bien.body[0], {"read_excel"})  # type: ignore[arg-type]
