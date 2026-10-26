"""El índice de `docs/` los lista a todos, y ninguna página manda a leer lo que no está.

`test_repo3_el_indice_de_docs_no_miente.py` comprueba que los **enlaces markdown** de `docs/`
resuelven. Es media pregunta, y la otra media es la que se escapó: el 2026-09-19 había **nueve
documentos sin indexar** —`MULTITENENCIA.md`, `CATALOGO_FUNCIONES.md`,
`REGISTRO_ACTIVIDAD_IA.md`, `WIDGET_INCRUSTACION.md` y cinco más— y **dos referencias muertas**
en la portada que lee quien llega de fuera.

Las dos muertas enseñan por qué hacía falta otro test y no un enlace mejor escrito:
`PRESENTACION_PROYECTO.md` §10 mandaba a `docs/EU_GOVERNANCE_CONCEPT_NOTE.md` —que existe en el
disco del mantenedor y **no en el repositorio**, excluido a propósito— y a
`docs/INFORME_CHATBOTS_NORMATIVA_Y_GERENCIA.html`, que no existe en ninguna parte. Ninguna de
las dos estaba escrita como enlace markdown sino como ruta entre acentos graves, así que el test
de REPO.3 **pasaba en verde** mirando a otro lado. Es el patrón que este proyecto llama «el
medidor miente antes que el sistema»: un guardarraíl sólo ve la pregunta que le hicieron.

Dos propiedades, las dos permanentes —no listas de lo que había hoy, que caducarían—:

1. Todo `docs/*.md` aparece en `docs/README.md`.
2. Toda ruta `docs/...` citada entre acentos graves en un documento activo existe **en el
   repositorio**, que no es lo mismo que en el disco de quien ejecuta los tests.
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

_DOCS = Path("../docs")
_RAIZ = Path("..")

#: El índice no se indexa a sí mismo.
_NO_SE_INDEXAN = frozenset({"README.md"})

#: Ficheros que son REGISTRO del pasado: nombran lo retirado porque su función es ésa.
_SON_REGISTRO = frozenset({"INVENTARIO_RETIRADA_LEGACY.md"})

#: Citas históricas legítimas: el documento dice que ese fichero **se retiró**, y decir dónde
#: estaba es justamente su contenido. Se listan una a una, con su razón, en lugar de inventar
#: una heurística sobre la prosa que la rodea —que fallaría en los dos sentidos—.
_CITAS_HISTORICAS = {
    ("MCP_SERVER.md", "docs/mcp.md"): (
        "§8 cuenta que `mcp.md` se retiró en REPO.3 por solaparse con este documento"
    ),
}

#: Rutas `docs/...` escritas entre acentos graves. Sólo `docs/`: una ruta con ese prefijo es
#: inequívocamente del repositorio, mientras que `services/foo.py` suele ser taquigrafía
#: relativa al módulo del que habla el párrafo, y perseguirla daría ruido sin señal.
_RUTA_ENTRE_ACENTOS = re.compile(r"`(docs/[A-Za-z0-9_./-]+\.(?:md|html))`")


@lru_cache(maxsize=1)
def _versionados() -> frozenset[str]:
    """Lo que tiene quien clona, preguntado a git y no al disco.

    Mismo motivo que en `test_repo3_el_indice_de_docs_no_miente.py`: hay documentos excluidos
    por `.git/info/exclude`, que es por clon y no viaja. Preguntar al disco haría pasar en
    local lo que en CI —y en el repositorio público— es un enlace muerto.
    """
    salida = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_RAIZ,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return frozenset(p for p in salida.split("\0") if p)


def _documentos_de_primer_nivel() -> list[Path]:
    """Sólo el primer nivel: los subdirectorios se indexan como carpeta, no fichero a fichero."""
    return sorted(p for p in _DOCS.glob("*.md") if p.name not in _NO_SE_INDEXAN)


def _documentos_activos() -> list[Path]:
    return sorted(
        p
        for p in _DOCS.rglob("*.md")
        if "node_modules" not in p.parts and p.name not in _SON_REGISTRO
    )


@pytest.fixture(scope="module")
def indice() -> str:
    readme = _DOCS / "README.md"
    assert readme.is_file(), "no hay docs/README.md, que es el índice"
    return readme.read_text(encoding="utf-8")


class TestElIndiceLosListaATodos:
    """Un documento que no está en el índice no lo encuentra nadie que no lo sepa de memoria."""

    @pytest.mark.parametrize(
        "documento", _documentos_de_primer_nivel(), ids=lambda p: p.name
    )
    def test_should_be_listed_in_the_index(self, documento: Path, indice: str):
        assert documento.name in indice, (
            f"docs/{documento.name} no aparece en docs/README.md. Un documento sin indexar "
            "existe para quien lo escribió y para nadie más: añádelo a la tabla que le "
            "corresponda por clase (referencia viva, decisión o instantánea)."
        )

    # El error simétrico —que el índice ENLACE algo que no existe— ya lo cubre
    # `test_repo3_el_indice_de_docs_no_miente.py`, y aquí no se repite. Comprobarlo sobre los
    # nombres sueltos, y no sobre los enlaces, sería además incorrecto: el índice **nombra a
    # propósito** los cuatro documentos que REPO.3 retiró, para decir dónde se leen, y cita
    # `PROJECT_STATE.md` y `HISTORIAL.md`, que viven en `planificacion/`.


class TestNadieMandaALeerLoQueNoEsta:
    """Una ruta entre acentos graves es un enlace igual, sólo que sin comprobar.

    Es la forma en que `PRESENTACION_PROYECTO.md` mandó durante meses a dos documentos que
    quien clonara el repositorio no iba a encontrar.
    """

    def test_should_resolve_every_backticked_docs_path(self):
        rotos: list[str] = []
        for doc in _documentos_activos():
            for ruta in _RUTA_ENTRE_ACENTOS.findall(doc.read_text(encoding="utf-8")):
                if (doc.name, ruta) in _CITAS_HISTORICAS:
                    continue
                if ruta not in _versionados():
                    rotos.append(f"{doc.as_posix()} → {ruta}")

        assert rotos == [], (
            "documentos que citan rutas de `docs/` que el repositorio no tiene:\n  "
            + "\n  ".join(rotos)
            + "\n\nSi el documento es deliberadamente no versionado, dilo en la prosa en vez de "
            "dar una ruta; si es una cita histórica, declárala en _CITAS_HISTORICAS con su razón."
        )

    @pytest.mark.parametrize(
        ("documento", "ruta"), sorted(_CITAS_HISTORICAS), ids=lambda v: str(v)
    )
    def test_should_keep_the_historical_exemptions_honest(self, documento: str, ruta: str):
        """Una exención que ya no se usa es una excepción heredada, y esas nunca se revisan."""
        texto = (_DOCS / documento).read_text(encoding="utf-8")
        assert f"`{ruta}`" in texto, (
            f"{documento} ya no cita `{ruta}`: retira la entrada de _CITAS_HISTORICAS en vez de "
            "dejar una exención que no exime de nada"
        )
