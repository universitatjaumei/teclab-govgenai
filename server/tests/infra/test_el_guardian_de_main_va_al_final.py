"""Un `if __name__ == "__main__":` con definiciones debajo es un `NameError` en producción.

Lo encontró la revisión de la PR #189 en `ingestion/corpus/actualiza.py`: el refresco de anclas
del diario se definió **después** del guardián, así que `python -m … --confirmar` llamaba a
`main()` antes de que Python hubiera ejecutado esa definición y moría con `NameError`. El
refresco no se aplicaba nunca.

**Y no lo cazó ningún test porque el camino que fallaba era el de `--confirmar`**: un `--dry-run`
no llegaba a llamarlo. Es el peor reparto posible — el modo que se prueba funciona y el que se usa
de verdad, no.

Esto es una comprobación de **forma**, y se reconoce como tal: mira el árbol sintáctico de cada
módulo ejecutable y exige que el guardián sea la última sentencia de nivel superior. Es la única
manera de impedirlo de antemano, porque el defecto no existe hasta que alguien ejecuta la rama
concreta.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_APP = pathlib.Path(__file__).resolve().parents[2] / "app"


def _es_el_guardian(nodo: ast.stmt) -> bool:
    """`if __name__ == "__main__":`, escrito de cualquiera de sus formas habituales."""
    if not isinstance(nodo, ast.If):
        return False
    prueba = nodo.test
    if not isinstance(prueba, ast.Compare) or len(prueba.comparators) != 1:
        return False
    izquierda, derecha = prueba.left, prueba.comparators[0]
    return (
        isinstance(izquierda, ast.Name)
        and izquierda.id == "__name__"
        and isinstance(derecha, ast.Constant)
        and derecha.value == "__main__"
    )


def _modulos_ejecutables() -> list[pathlib.Path]:
    encontrados = []
    for fichero in _APP.rglob("*.py"):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), filename=str(fichero))
        if any(_es_el_guardian(n) for n in arbol.body):
            encontrados.append(fichero)
    return sorted(encontrados)


def test_hay_modulos_que_se_ejecutan_por_linea_de_ordenes():
    """Sin esto, el test de abajo pasaría en verde sobre una lista vacía para siempre."""
    assert _modulos_ejecutables(), "no se encontró ningún módulo con guardián de `__main__`"


@pytest.mark.parametrize("modulo", _modulos_ejecutables(), ids=lambda p: p.name)
def test_el_guardian_es_la_ultima_sentencia_del_modulo(modulo: pathlib.Path):
    arbol = ast.parse(modulo.read_text(encoding="utf-8"), filename=str(modulo))

    posiciones = [i for i, n in enumerate(arbol.body) if _es_el_guardian(n)]
    ultima = len(arbol.body) - 1

    for posicion in posiciones:
        debajo = [
            getattr(n, "name", type(n).__name__) for n in arbol.body[posicion + 1 :]
        ]
        assert posicion == ultima, (
            f"{modulo.name}: el guardián de `__main__` tiene cosas debajo ({debajo}), y "
            f"Python no las ha ejecutado cuando llama a lo que hay dentro. Es un `NameError` "
            f"en cuanto el camino de ejecución las use — el defecto de `actualiza.py` que "
            f"encontró la revisión de la PR #189."
        )
