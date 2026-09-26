"""Issue #18 — lo que corre dentro del servidor no imprime: registra.

**El defecto, y por qué no es cosmético.** En producción un `print()` sale por la salida
estándar **sin nivel, sin marca de tiempo y sin nombre de módulo**. No se puede filtrar por
severidad, ni subir el detalle de un servicio sin subirlo de todos, ni silenciar lo ruidoso sin
perder lo importante. Es la diferencia entre poder mirar qué pasó y tener que reproducirlo: los
50 minutos caídos del 2026-09-24 y los 35 del incidente de `uvicorn` se fueron en averiguar la
causa, no en arreglarla.

**Y crecía.** 157 en agosto, 186 en septiembre, 187 hoy. Por eso la issue pide una comprobación
y no sólo una limpieza: una cifra que sube sola vuelve a subir en cuanto nadie mire.

**Lo que este guardarraíl NO prohíbe, que es la mitad del diseño.** Hay sitios donde imprimir es
exactamente lo correcto: una herramienta de consola le habla a la persona que la acaba de
ejecutar, y mandarle su salida a un `logger` la escondería. `corpus/load.py`, `run_golden.py` o
`detectar_derogados.py` **tienen que** imprimir. Un guardarraíl que los prohibiera se desactivaría
el primer día, que es como muere un guardarraíl.

**Cómo se distingue, y por qué así.** Un módulo puede imprimir si es **estructuralmente** una
herramienta de consola —define un `typer.Typer()`, un `if __name__ == "__main__"` o usa
`argparse`—, porque eso es un hecho del módulo y no una opinión que alguien escriba encima. Para
el caso que la estructura no ve —un sembrado que no tiene punto de entrada propio porque lo
invoca otro que sí lo tiene— hay una declaración explícita **con su razón**, igual que el
`recorrido-acotado:` de la issue #159. La salida es declarar, no apagar la comprobación.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2] / "app"

#: La declaración para lo que la estructura no puede ver. Lleva razón detrás, a la vista de
#: quien lea el módulo después.
MARCA = "salida-por-consola:"

#: Lo que hace de un módulo una herramienta de consola, como hecho y no como opinión.
_SEÑALES_DE_CONSOLA = (
    "typer.Typer(",
    'if __name__ == "__main__"',
    "if __name__ == '__main__'",
    "import argparse",
)


def _imprime(texto: str) -> int:
    """Cuántas llamadas a `print()` hay. Con AST, no con `grep`: «print(» aparece en cadenas,
    en docstrings y en comentarios, y contarlas daría una cifra que no es la que importa."""
    try:
        arbol = ast.parse(texto)
    except SyntaxError:  # pragma: no cover - no hay ficheros así en el árbol
        return 0
    return sum(
        1
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Name)
        and nodo.func.id == "print"
    )


def _es_de_consola(texto: str) -> bool:
    return MARCA in texto or any(s in texto for s in _SEÑALES_DE_CONSOLA)


def _modulos_que_imprimen_sin_ser_consola() -> dict[str, int]:
    hallazgos: dict[str, int] = {}
    for fichero in sorted(RAIZ.rglob("*.py")):
        texto = fichero.read_text(encoding="utf-8")
        if _es_de_consola(texto):
            continue
        cuantos = _imprime(texto)
        if cuantos:
            hallazgos[fichero.relative_to(RAIZ).as_posix()] = cuantos
    return hallazgos


def test_ningun_modulo_del_servidor_imprime_por_la_salida_estandar() -> None:
    sin_registrar = _modulos_que_imprimen_sin_ser_consola()

    assert not sin_registrar, (
        "Estos módulos corren dentro del servidor y escriben por la salida estándar:\n  - "
        + "\n  - ".join(f"{k} ({v})" for k, v in sin_registrar.items())
        + "\n\nEn producción eso sale sin nivel, sin marca de tiempo y sin nombre de módulo: "
        "no se puede filtrar por severidad ni subir el detalle de un servicio sin subirlo de "
        "todos. Usa `logging.getLogger(__name__)` y elige el nivel — `debug` para el detalle "
        "de una pasada, `info` para lo que hace el servicio, `warning` para lo degradado, "
        "`error` para lo que falló.\n\n"
        f"Si el módulo le habla a una persona en una consola, declara por qué: un comentario "
        f"con «{MARCA} <razón>». Las herramientas con `typer.Typer()`, `__main__` o `argparse` "
        "no necesitan declararlo: ya se ven."
    )


def test_el_guardarrail_sabe_distinguir_las_dos_cosas() -> None:
    """Un guardarraíl que no encuentra nada pasa en verde sin haber mirado, y ya pasó aquí.

    Se demuestra que cuenta lo que hay que contar —y no lo que se le parece— y que las dos
    salidas, la estructural y la declarada, funcionan.
    """
    assert _imprime("print('hola')\nprint(x)") == 2
    # Lo que `grep` contaría y no es una llamada: una cadena y un docstring.
    assert _imprime('msg = "print(algo)"\n') == 0
    assert _imprime('"""Ejemplo: print(x)."""\n') == 0
    # Un método que se llama igual no es la función incorporada.
    assert _imprime("consola.print('hola')") == 0

    assert _es_de_consola("app = typer.Typer()\nprint('x')")
    assert _es_de_consola('if __name__ == "__main__":\n    print("x")')
    assert _es_de_consola(f"# {MARCA} lo invoca el bootstrap\nprint('x')")
    assert not _es_de_consola("def servicio():\n    print('x')")


def test_el_guardarrail_mira_donde_hay_codigo() -> None:
    """Y que la raíz exista, que es la otra forma silenciosa de no comprobar nada."""
    assert RAIZ.is_dir(), f"{RAIZ} no existe: este test no está mirando ningún código"
    assert len(list(RAIZ.rglob("*.py"))) > 100
