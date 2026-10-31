"""#346 — el Copilot tiene ayuda para quien lo usa, y en la imagen.

En producción no tenía documentación ninguna: `DocsRetriever` indexaba `Path("docs")`, relativa al
directorio de trabajo, y el `Dockerfile` no copiaba `docs/`. El índice salía vacío y, fuera de un
informe, el Copilot contestaba «No tengo esa información» **sin llamar al modelo**. Se vio al
comprobar #344: un 200 no demostraba nada.

Copiar `docs/` entero no era la solución. Está escrita para quien desarrolla —especificación,
decisiones, mediciones— y lleva material que no debe quedar al alcance de cualquier usuario del
módulo de Informes. La ayuda vive en `docs/ayuda/`, por módulo y por lengua, y es lo único que viaja.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[5]
_AYUDA = _RAIZ / "docs" / "ayuda"


class _Embeddings:
    async def embed(self, text: str, purpose: str = "query") -> list[float]:
        return [float(len(text) % 7), 1.0, 0.5]


def test_la_imagen_copia_la_ayuda_y_nada_mas_de_docs() -> None:
    dockerfile = (_RAIZ / "Dockerfile").read_text(encoding="utf-8")

    copias_de_docs = re.findall(r"^COPY\s+(docs\S*)", dockerfile, flags=re.MULTILINE)

    assert copias_de_docs == ["docs/ayuda/"], (
        "la imagen tiene que llevar la ayuda del Copilot, y sólo la ayuda: el resto de docs/ es "
        f"para quien desarrolla. Copias encontradas: {copias_de_docs}"
    )


def test_el_buscador_apunta_a_la_ayuda_sin_depender_del_directorio_de_trabajo(
    monkeypatch, tmp_path: Path
) -> None:
    from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

    monkeypatch.chdir(tmp_path)  # el contenedor arranca en /app; los tests, en server/

    carpeta = DocsRetriever(embedding_service=_Embeddings())._docs_dir

    assert carpeta.is_absolute()
    assert carpeta.resolve() == _AYUDA.resolve()


@pytest.mark.asyncio
async def test_lo_que_se_indexa_es_la_ayuda_de_los_dos_modulos_en_las_dos_lenguas() -> None:
    from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

    buscador = DocsRetriever(embedding_service=_Embeddings())
    await buscador.index()

    rutas = {Path(c.source_path).resolve() for c in buscador.chunks}
    assert rutas, "la ayuda no puede estar vacía: es lo que hace responder al Copilot"
    fuera = [r for r in rutas if _AYUDA.resolve() not in r.parents]
    assert not fuera, f"se ha indexado algo de fuera de docs/ayuda/: {fuera}"

    modulos = {c.module for c in buscador.chunks}
    assert {"redaccion", "general"} <= modulos, "Informes y Curación, cada una en su módulo"

    lenguas = {r.relative_to(_AYUDA.resolve()).parts[1] for r in rutas}
    assert lenguas == {"es", "val"}


def test_cada_guia_existe_en_las_dos_lenguas() -> None:
    def guias(lengua: str) -> set[str]:
        return {
            f"{p.parent.parent.name}/{p.name}" for p in _AYUDA.glob(f"*/{lengua}/*.md")
        }

    assert guias("es") == guias("val")


def test_el_contexto_de_construccion_no_deja_fuera_la_ayuda() -> None:
    """`.dockerignore` excluye `*.md`. En Docker ese patrón sólo alcanza la raíz, pero basta con que
    alguien lo escriba `**/*.md` para que la imagen lleve la carpeta vacía y el Copilot vuelva a
    callar sin error. La reinclusión explícita, **después** de cualquier exclusión de Markdown,
    lo impide."""
    lineas = [
        linea.strip()
        for linea in (_RAIZ / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.lstrip().startswith("#")
    ]

    assert "!docs/ayuda/" in lineas
    ultima_exclusion_md = max(
        (i for i, linea in enumerate(lineas) if linea.endswith(".md") and not linea.startswith("!")),
        default=-1,
    )
    assert lineas.index("!docs/ayuda/") > ultima_exclusion_md
