"""#280 — toda ruta del repositorio citada en la documentación existe en el repositorio.

`test_agents_no_apunta_al_vacio.py` lo comprobaba sólo para `AGENTS.md`, y
`test_el_indice_de_docs_esta_completo.py` sólo para las rutas `docs/…`. Entre los dos quedaba
el resto: la auditoría del 2026-10-21 contó **22 rutas** de `docs/`, `ROADMAP.md` y `README.md`
que no resolvían, y una ruta muerta en un documento de referencia manda a buscar lo que no está
con la autoridad de quien lo escribió.

**Qué se considera ruta.** Lo que va entre acentos graves y empieza por un directorio de primer
nivel del repositorio (`server/`, `frontend/`, `deploy/`, `services/`…), que es inequívoco. La
taquigrafía relativa a un módulo —`tests/…`, `app/…`, `core/…`— queda fuera por el motivo que da
`test_el_indice_de_docs_esta_completo.py`: depende del párrafo y perseguirla da ruido sin señal.
Con una excepción que esta issue destapó: `services/…` **es** un directorio de primer nivel, el
del sandbox, y la taquigrafía `services/script_auditor.py` apuntaba a él sin querer. Se escribe
entera.

**Qué no se comprueba.** Lo retirado que se nombra como retirado: `client_app/` y
`_legacy_nicegui/` ya no son directorios de primer nivel, así que no entran, y el inventario de
la retirada es registro del pasado a propósito. Tampoco `_local/` ni `.claude/`: están en el
repositorio, pero lo que se cita de ellos es lo de cada copia —la carpeta operativa de quien
mantiene, los permisos de cada desarrollador— y no viaja con el clon.
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
assert (RAIZ / "docs").is_dir(), f"la raíz no es la que se cree: {RAIZ}"

#: Registro del pasado: nombra lo retirado porque su función es ésa. La valoración del
#: 2026-08-24 es una auditoría fechada sobre el árbol en `b705bfa`, y lo dice en su cabecera.
_SON_REGISTRO = frozenset({"INVENTARIO_RETIRADA_LEGACY.md", "VALORACION_PROYECTO.md"})

#: Lo que se cita de cada copia y no del repositorio.
_DE_CADA_COPIA = frozenset({"_local", ".claude"})

#: Citas que no resuelven a propósito, una a una y con su razón.
_CITAS_HISTORICAS = {
    ("MCP_SERVER.md", "docs/mcp.md"): (
        "§8 cuenta que `mcp.md` se retiró en REPO.3 por solaparse con este documento"
    ),
    ("Arquitectura.md", "frontend/src/agent"): "la fila de rutas que «ninguna existe»",
    ("Arquitectura.md", "frontend/src/automation"): "la misma fila",
    ("AUDITORIA_PRE_DEPLOY.md", "server/my_errores.txt"): "M6: el residuo «ya no existe»",
    ("AUDITORIA_PRE_DEPLOY.md", "frontend/src/automation"): "I6: «sin router ni» esa carpeta",
}


@lru_cache(maxsize=1)
def _versionados() -> frozenset[str]:
    """Lo que tiene quien clona, preguntado a git y no al disco."""
    salida = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(p for p in salida.split("\0") if p)


@lru_cache(maxsize=1)
def _directorios_versionados() -> frozenset[str]:
    directorios: set[str] = set()
    for fichero in _versionados():
        partes = fichero.split("/")[:-1]
        for i in range(1, len(partes) + 1):
            directorios.add("/".join(partes[:i]))
    return frozenset(directorios)


def _documentos() -> list[Path]:
    raiz = [RAIZ / n for n in ("AGENTS.md", "ROADMAP.md", "README.md")]
    docs = [
        RAIZ / p
        for p in _versionados()
        if p.startswith("docs/") and p.endswith(".md") and Path(p).name not in _SON_REGISTRO
    ]
    return raiz + sorted(docs)


def _rutas_citadas(texto: str) -> list[str]:
    primer_nivel = sorted(
        d for d in _directorios_versionados() if "/" not in d and d not in _DE_CADA_COPIA
    )
    patron = re.compile(r"`((?:" + "|".join(map(re.escape, primer_nivel)) + r")/[^`\s]*)`")
    rutas = []
    for bruta in patron.findall(texto):
        if any(c in bruta for c in "*{}<>$…"):
            continue  # un patrón o una plantilla, no una ruta
        # `fichero.py:120-130` y `fichero.md#ancla` citan un sitio dentro de la ruta.
        rutas.append(re.sub(r"(:\d[\d,-]*|#.*)$", "", bruta).rstrip("/"))
    return rutas


def test_should_find_paths_to_check():
    """Un guardarraíl que no encuentra nada que mirar pasa en verde sin mirar nada."""
    assert len([r for d in _documentos() for r in _rutas_citadas(d.read_text("utf-8"))]) > 200


@pytest.mark.parametrize("documento", _documentos(), ids=lambda p: p.relative_to(RAIZ).as_posix())
def test_should_cite_paths_that_exist(documento: Path):
    existentes = _versionados() | _directorios_versionados()
    rotos = [
        ruta
        for ruta in _rutas_citadas(documento.read_text(encoding="utf-8"))
        if ruta not in existentes and (documento.name, ruta) not in _CITAS_HISTORICAS
    ]
    assert rotos == [], (
        f"`{documento.relative_to(RAIZ).as_posix()}` cita rutas que el repositorio no tiene: "
        f"{rotos}. Corrígela, o si el fichero se retiró, dilo en la prosa sin dar una ruta que "
        "parezca viva; si es una cita histórica deliberada, decláralo en _CITAS_HISTORICAS."
    )


@pytest.mark.parametrize(("documento", "ruta"), sorted(_CITAS_HISTORICAS), ids=str)
def test_should_keep_the_historical_exemptions_honest(documento: str, ruta: str):
    texto = (RAIZ / "docs" / documento).read_text(encoding="utf-8")
    assert f"`{ruta}`" in texto or f"`{ruta}/`" in texto, (
        f"{documento} ya no cita `{ruta}`: retira la exención."
    )
