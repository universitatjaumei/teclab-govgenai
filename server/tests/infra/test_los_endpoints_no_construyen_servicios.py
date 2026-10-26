"""#274 — un endpoint recibe sus servicios por `Depends`; no los construye.

La auditoría del 2026-10-21 contó diez servicios instanciados dentro del handler, y al medirlo
con este recorrido salieron veintiuno: `PatService` en `pat_router` y `FeedbackService` en
`api/v1/hub_feedback.py` se le escaparon al recuento a mano. Es la razón de que sea un test y
no una lista: una lista se queda corta el día que alguien añade el siguiente.

Construirlo dentro del handler no es un detalle de estilo. Un servicio construido ahí no se puede
sustituir en un test sin parchear el módulo del router —que es lo que hacían los tests—, y la
dependencia queda escondida en el cuerpo en vez de en la firma, donde se ve qué necesita cada
endpoint.

Se miran sólo las funciones decoradas como endpoint: un proveedor `get_x_service` construye su
servicio, que para eso existe.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
SUPERFICIES = (APP / "routers", APP / "api")
VERBOS = {"get", "post", "put", "patch", "delete", "websocket", "api_route"}


def _es_endpoint(funcion: ast.AST) -> bool:
    return any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in VERBOS
        for d in getattr(funcion, "decorator_list", [])
    )


def _nombre(llamada: ast.Call) -> str | None:
    if isinstance(llamada.func, ast.Name):
        return llamada.func.id
    if isinstance(llamada.func, ast.Attribute):
        return llamada.func.attr
    return None


def _servicios_construidos_en_endpoints() -> tuple[int, list[str]]:
    endpoints, culpables = 0, []
    for raiz in SUPERFICIES:
        for fichero in sorted(raiz.rglob("*.py")):
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not _es_endpoint(nodo):
                    continue
                endpoints += 1
                for llamada in ast.walk(nodo):
                    nombre = isinstance(llamada, ast.Call) and _nombre(llamada)
                    if nombre and nombre[0].isupper() and nombre.endswith("Service"):
                        ruta = fichero.relative_to(APP).as_posix()
                        culpables.append(f"{ruta}:{llamada.lineno} {nodo.name} → {nombre}")
    return endpoints, culpables


def test_el_medidor_encuentra_endpoints() -> None:
    """Sin esto, el test de abajo pasaría en verde sin haber mirado nada."""
    endpoints, _ = _servicios_construidos_en_endpoints()
    assert endpoints > 200, endpoints


def test_ningun_endpoint_construye_un_servicio() -> None:
    _, culpables = _servicios_construidos_en_endpoints()
    assert not culpables, (
        "estos endpoints construyen su servicio en vez de recibirlo por `Depends`:\n  "
        + "\n  ".join(culpables)
    )
