"""APER.16 — todo `conftest` que abra una conexión carga torch primero.

**El defecto.** En Windows, cargar torch **después** de abrir una conexión asyncpg aborta el
proceso con «Windows fatal exception: access violation». Se diagnosticó el 2026-07-29 y se
resolvió poniendo `import langchain_text_splitters` —que arrastra `sentence_transformers` → torch—
como primera línea de los `conftest` que tienen `db_session`.

`tests/modules/redaccion/conftest.py` ganó su `db_session` sin esa línea, así que esa suite podía
tumbar el proceso **en la plataforma de desarrollo de este proyecto**. Lo señaló la revisión
automática de la PR del despliegue; no lo cazó ningún test porque no había ninguno que mirara.

**Por qué un guardarraíl y no sólo la línea.** Porque el defecto no es del fichero: es del patrón.
El siguiente `conftest` que necesite una sesión de base de datos lo va a perder igual, y el
síntoma —un proceso que muere sin traza, sólo en Windows y sólo a veces— es de los que se
investigan durante horas culpando a otra cosa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RAIZ_TESTS = Path(__file__).resolve().parents[1]

#: La línea que tiene que ir delante, y el módulo que la justifica.
GUARDA = "import langchain_text_splitters"


def _conftests_con_sesion() -> list[Path]:
    """Los `conftest.py` que **crean un motor**: son los que tienen el problema.

    Mencionar `db_session` no basta —hay conftest que sólo consumen la fixture de otro— y un
    detector que los incluyera pediría la guarda donde no hace falta. Lo que dispara el fallo es
    abrir la conexión, y eso es `create_async_engine`.

    Tampoco se pide en el conftest raíz, aunque desde #281 define el `db_session` de todos:
    ponerla ahí cargaría torch en **toda** ejecución, también en las suites que no tocan la base
    —segundos de arranque por un riesgo que esas suites no corren—. El orden lo siguen fijando
    los conftest de los directorios cuyos tests cargan torch, que pytest importa al recoger, antes
    de que ningún fixture abra una conexión.
    """
    encontrados = []
    for ruta in sorted(RAIZ_TESTS.rglob("conftest.py")):
        if "__pycache__" in ruta.parts or ruta.parent == RAIZ_TESTS:
            continue
        if "create_async_engine" in ruta.read_text(encoding="utf-8"):
            encontrados.append(ruta)
    return encontrados


def test_hay_conftests_que_abren_conexion() -> None:
    """Si esto da cero, el test de abajo pasa sobre un conjunto vacío y no mira nada."""
    assert _conftests_con_sesion(), (
        "No se ha reconocido ningún conftest con sesión de base de datos. O cambió el patrón, "
        "o esta comprobación ha dejado de mirar."
    )


@pytest.mark.parametrize(
    "ruta", _conftests_con_sesion(), ids=lambda p: p.relative_to(RAIZ_TESTS).as_posix()
)
def test_carga_torch_antes_de_abrir_nada(ruta: Path) -> None:
    lineas = [
        linea.strip()
        for linea in ruta.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.strip().startswith("#")
    ]
    # El docstring y el `from __future__` pueden ir delante; lo que importa es que la guarda
    # esté antes que cualquier otro import de la aplicación.
    posicion_guarda = next(
        (i for i, linea in enumerate(lineas) if linea.startswith(GUARDA)), None
    )
    assert posicion_guarda is not None, (
        f"{ruta.name} abre una conexión y no carga torch antes. En Windows eso aborta el "
        "proceso con «access violation», sin traza y de forma intermitente. La línea es "
        f"`{GUARDA}  # noqa: F401` y va lo primero; sus hermanos la llevan con el porqué."
    )

    primer_import_de_app = next(
        (
            i
            for i, linea in enumerate(lineas)
            if linea.startswith("from server.") or linea.startswith("import server.")
        ),
        None,
    )
    if primer_import_de_app is not None:
        assert posicion_guarda < primer_import_de_app, (
            f"{ruta.name} importa código de la aplicación antes de cargar torch, y ese código "
            "puede abrir una conexión. La guarda va delante de todo."
        )
