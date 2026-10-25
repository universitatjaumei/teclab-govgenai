"""#275 — el lint y los tipos cubren el servidor entero, no una parte.

La auditoría del 2026-10-21 midió tres huecos:

* **CI linteaba `app/` y `tests/`**, y `ruff check .` daba 22 errores, todos fuera: en
  `migrations/`, en `scripts/` y en un `drop_table.py` suelto. Dos de los tres guiones ni
  importaban —dependían de símbolos retirados— y se borraron en vez de lintearse.
* **El conjunto de reglas era el mínimo** (`E4, E7, E9, F`). Las familias que cazan defectos y no
  estilo —`B`, `BLE`, `ARG`, `PLW1510`, `RUF100`, `PT`— quedaban fuera, y el propio
  `pyproject.toml` dejaba anotada la medida para decidir.
* **pyright miraba sólo `app/core`**: 0 errores ahí y 263 en el resto.

Este fichero vigila las tres cosas a la vez, porque cada una se puede deshacer sola: basta con
volver a escribir `app/ tests/` en el paso de CI.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
MANIFIESTO = RAIZ / "server" / "pyproject.toml"
CI = RAIZ / ".github" / "workflows" / "ci.yml"

FAMILIAS = {"B", "BLE", "ARG", "PLW1510", "RUF100", "PT"}


def _herramienta(nombre: str) -> dict:
    return tomllib.loads(MANIFIESTO.read_text(encoding="utf-8"))["tool"][nombre]


def _pasos_de_ci() -> list[str]:
    datos = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return [
        paso.get("run") or ""
        for cuerpo in datos["jobs"].values()
        for paso in cuerpo.get("steps", [])
    ]


def test_ci_lintea_el_servidor_entero() -> None:
    lint = [p for p in _pasos_de_ci() if "ruff check" in p]
    assert lint, "ningún paso de CI ejecuta ruff"
    assert any(p.split("ruff check", 1)[1].split()[:1] == ["."] for p in lint), (
        f"CI lintea {lint}: con `app/ tests/`, `migrations/` y los guiones quedan fuera, que es "
        "donde estaban los 22 errores que medía la auditoría."
    )


def test_las_familias_que_cazan_defectos_estan_seleccionadas() -> None:
    seleccion = set(_herramienta("ruff")["lint"]["select"])
    faltan = sorted(FAMILIAS - seleccion)
    assert not faltan, f"faltan en `[tool.ruff.lint] select`: {faltan}"


def test_las_exclusiones_por_fichero_no_apagan_familias_en_app_entero() -> None:
    """Una exclusión `app/**` de `B` o `BLE` devolvería en silencio lo que se acaba de exigir."""
    exclusiones = _herramienta("ruff")["lint"].get("per-file-ignores", {})
    anchas = {
        patron: sorted(set(reglas) & (FAMILIAS - {"PT"}))
        for patron, reglas in exclusiones.items()
        if patron in ("app/**", "**", "*", "app/*")
    }
    assert not any(anchas.values()), f"exclusiones que cubren todo `app/`: {anchas}"


def test_pyright_mira_app_entero() -> None:
    config = _herramienta("pyright")
    assert "app" in config["include"], (
        f"pyright incluye {config['include']}: la auditoría midió 263 errores fuera de "
        "`app/core`, que es donde no miraba nadie."
    )


def test_lo_que_pyright_deja_fuera_esta_declarado_y_existe() -> None:
    """Una exclusión que ya no apunta a nada es una puerta abierta con otro nombre."""
    excluidos = _herramienta("pyright").get("exclude", [])
    inexistentes = [e for e in excluidos if not (MANIFIESTO.parent / e).exists()]
    assert not inexistentes, f"exclusiones de pyright que no existen: {inexistentes}"
