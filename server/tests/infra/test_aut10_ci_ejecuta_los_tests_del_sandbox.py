"""CI ejecuta los tests del sandbox, y no sólo audita sus dependencias y construye su imagen.

**Lo destapó AUT.10 (issue #120).** Las dos funciones del presupuesto propio tienen una prueba
gemela en `services/script_sandbox/tests/`, porque el sandbox corre con pandas 3 y el modo local de
la plataforma con pandas 2: un guion que sólo funcionara con uno pasaría en el otro. Al escribirla
salió que **ningún job ejecutaba ese árbol**: CI exportaba su lock, lo auditaba y construía la
imagen, y nada más. Los tests de #194, del saneado de rutas que pidió CodeQL y de la colisión de
carpetas por slot existían y no los corría nadie.

Es el mismo agujero que el paso «Run the trees the server job does not see» cerró para `shared` y
`mcp_server` en NIC.4: un árbol de tests que ningún job ejecuta envejece en silencio.
"""
from __future__ import annotations

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
CI = RAIZ / ".github" / "workflows" / "ci.yml"


def _ordenes_de_ci() -> list[str]:
    flujo = yaml.safe_load(CI.read_text(encoding="utf-8"))
    ordenes = []
    for trabajo in flujo["jobs"].values():
        for paso in trabajo.get("steps", []):
            if "run" in paso:
                ordenes.append(paso["run"])
    return ordenes


def test_el_medidor_ve_las_ordenes_de_ci() -> None:
    """Si el fichero cambiara de forma y no se viera nada, el test de abajo pasaría por vacío."""
    assert any("pytest" in o for o in _ordenes_de_ci())


def test_algun_paso_ejecuta_los_tests_del_sandbox() -> None:
    ordenes = "\n".join(_ordenes_de_ci())
    assert "--directory services/script_sandbox" in ordenes and any(
        "services/script_sandbox" in linea and "pytest" in linea
        for linea in ordenes.splitlines()
    ), (
        "ningún paso de CI ejecuta `services/script_sandbox/tests`. Exportar su lock y construir "
        "su imagen no ejecuta sus tests, y ahí está la prueba de que un guion funciona con el "
        "pandas del sandbox y no sólo con el del servidor."
    )


def test_y_con_el_extra_que_trae_pytest() -> None:
    """`pytest` está en el extra `dev`: sin pedirlo, `uv run` falla con «Failed to spawn: pytest».

    Pasó con `mcp_server` y está escrito en el propio `ci.yml`: en local funciona porque el venv ya
    tiene pytest de antes, y en CI se crea limpio.
    """
    linea = next(
        linea
        for linea in "\n".join(_ordenes_de_ci()).splitlines()
        if "services/script_sandbox" in linea and "pytest" in linea
    )
    assert "--extra dev" in linea
