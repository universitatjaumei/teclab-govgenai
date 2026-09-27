"""NIC.4 — cuando NiceGUI se va, se queda colgando el entorno que sólo existía por él.

**Lo que NIC.4 mide y retira** son las cuatro piezas que el prompt nombra: el `pyproject.toml` de
la raíz —cuya primera dependencia era `nicegui==3.4.1`— con su `uv.lock` de 1,6 MB, el árbol de
`tests/` de la raíz, el `translations.json` de 158 KB con su `i18n.py`, y `arranque.bat`.

**Dos de las cuatro no eran lo que el prompt suponía, y eso lo dijo la medición**, que es la razón
por la que el prompt exige medir antes de tocar:

* **`arranque.bat` ya estaba limpio.** LEG.5 lo arregló cuando movió el `main.py` del lanzador:
  hoy invoca `uv run --project server uvicorn server.app.main:app`, que es el arranque vigente. No
  se toca.
* **`tests/` de la raíz no es un bloque.** De sus 32 ficheros, unos prueban código vivo del
  servidor y otros son el mundo SQLModel *Brain/partner/licencia* que vino de AutomatIA y que
  **nada importa**. Retirarlos juntos habría perdido tests buenos; migrarlos juntos habría traído
  a `server/tests/` seis ficheros que no compilan.

**El guardarraíl que importa es el primero**, y no por el peso: `nicegui` como dependencia
declarada significa que un `uv sync` en la raíz vuelve a instalar la aplicación retirada, y a
partir de ahí «funciona en mi máquina» deja de significar nada.
"""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]

def _proyectos_uv() -> list[str]:
    """Los `pyproject.toml` que git conoce, que es la lista que no se puede discutir.

    **No se escribe a mano.** Una tupla literal con los cuatro que hay hoy —`server`, `shared`,
    `mcp_server`, `services/script_sandbox`— deja de cubrir al quinto en cuanto alguien lo cree, y
    lo hace en silencio y en verde: el peor modo de fallo de un guardarraíl.

    Y `git ls-files` en vez de `rglob`, porque un `rglob` recoge los `pyproject.toml` de dentro de
    los `.venv` y del `node_modules`, y esto acabaría midiendo las dependencias de terceros.
    """
    return sorted(set(_versionados("*pyproject.toml")))


def _versionados(*patrones: str) -> list[str]:
    salida = subprocess.run(
        ["git", "ls-files", *patrones],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=True,
    )
    return [linea for linea in salida.stdout.splitlines() if linea.strip()]


class TestNiceGuiNoEsDependenciaDeNadie:

    def test_should_have_no_nicegui_in_any_pyproject(self):
        """La condición de done del prompt: `grep -ri nicegui` a cero en dependencias.

        Se lee el TOML en vez de hacer `grep`, porque `grep` no distingue una dependencia de un
        comentario que explique por qué no la hay — y esa explicación es justamente lo que conviene
        poder escribir.
        """
        culpables = []
        proyectos = _proyectos_uv()
        assert len(proyectos) >= 3, (
            f"sólo se ven {proyectos}: el guardarraíl estaría midiendo casi nada"
        )
        for relativa in proyectos:
            ruta = RAIZ / relativa
            datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
            declaradas = list(datos.get("project", {}).get("dependencies", []))
            for grupo in datos.get("dependency-groups", {}).values():
                declaradas += [d for d in grupo if isinstance(d, str)]
            for extra in datos.get("project", {}).get("optional-dependencies", {}).values():
                declaradas += list(extra)
            for dependencia in declaradas:
                if "nicegui" in dependencia.lower():
                    culpables.append(f"{relativa}: {dependencia}")

        assert culpables == [], (
            f"NiceGUI vuelve a ser dependencia declarada: {culpables}. Un `uv sync` reinstala "
            "entonces la aplicación que NIC.3 retiró"
        )

    def test_should_have_no_root_pyproject_left(self):
        """El de la raíz se llamaba `automatia` y se describía como «aplicación NiceGUI legada».

        No lo usaba ningún workflow: CI y `deploy.yml` corren `uv sync` con
        `working-directory: server`, el `Dockerfile` copia `server/pyproject.toml` y el paso de
        colección de la suite raíz invoca `uv run --project server`. Lo único que aportaba era su
        `[tool.pytest.ini_options]`, y eso se va con el árbol de tests que configuraba.
        """
        assert not (RAIZ / "pyproject.toml").exists(), (
            "el `pyproject.toml` de la raíz volvió. Si hace falta un proyecto uv en la raíz, "
            "tiene que decir para qué sirve: el anterior declaraba 60 dependencias, incluido "
            "NiceGUI, y nadie lo instalaba salvo un desarrollador escribiendo `uv sync` sin `-p`"
        )

    def test_should_have_no_root_lock_left(self):
        """1,6 MB de lock resuelto de un manifiesto que ya no existe."""
        assert not (RAIZ / "uv.lock").exists(), "el `uv.lock` de la raíz volvió sin su manifiesto"


class TestLosTestsDeLaRaizSeRepartieron:
    """El árbol de la raíz no era un bloque, y se reparte según qué prueba cada fichero."""

    def test_should_have_no_root_tests_tree(self):
        assert not (RAIZ / "tests").exists(), (
            "`tests/` de la raíz volvió. La suite del servidor vive en `server/tests/`, que es "
            "la que CI ejecuta; un segundo árbol que CI sólo colecta acumuló durante meses doce "
            "rojos sin que ningún check se enterara"
        )

    #: Los dieciséis ficheros que probaban código vivo y se migraron, con su destino. Se listan
    #: por su nombre y no por su directorio a propósito: lo que hay que vigilar es que **estos**
    #: sigan estando, porque son la parte del árbol de la raíz que valía la pena y la que se
    #: perdería sin ruido si alguien limpiara «los tests duplicados».
    MIGRADOS = {
        "server/tests/modules/redaccion": (
            "test_block_handlers.py",
            "test_block_input_ui_contracts.py",
            # `test_block_topology.py` estuvo aquí y se retiró con su módulo el 2026-09-27
            # (issue #153): `block_topology` no tenía ningún importador vivo y sus tres trabajos
            # estaban cubiertos —el orden lo fija la plantilla, los fallos por dependencia los
            # propaga `block_executor`, y las proyecciones las resuelve `citation_traceability`—.
            #
            # **Quitarlo de esta lista es el único camino de salida, y está bien que lo sea**:
            # esta lista existe para que un test migrado no desaparezca en silencio, así que
            # retirarlo a propósito obliga a escribir por qué. Lo que no vale es bajar el número
            # sin decir nada.
            "test_draft_validator.py",
            "test_hub_redaccion_router.py",
            "test_llm_drafts_router.py",
            "test_llm_spec_service.py",
            "test_redaccion_models.py",
            "test_report_profile_registry.py",
            "test_report_template_contract.py",
            "test_runtime_and_drafts.py",
            "test_template_migration_service.py",
        ),
        "server/tests/public_graphs": (
            "test_9b2_models.py",
            "test_config_resolver.py",
            "test_registry.py",
        ),
        "server/tests/modules/agents_hub/unit": ("test_html_analyzer.py",),
    }

    def test_should_have_moved_the_live_ones_to_the_server_suite(self):
        """Los que prueban código vivo se migran, no se borran.

        **Se funden con las carpetas que ya existían**, no en una segunda `redaccion/` al lado:
        `server/tests/modules/redaccion/` cubría el mismo módulo, y dos directorios con el mismo
        nombre garantizan que la mitad de las búsquedas mire en el que no toca. Se comprobó antes
        de mover que no hubiera **ninguna colisión de nombre de fichero**, y tampoco de nombre de
        test: cero de los 128 tests de `tests/redaccion/` y cero de los 22 de
        `tests/public_graphs/` coincidían con ninguno de los 3.630 de `server/tests/`. No eran
        duplicados; era cobertura que CI nunca ejecutó.
        """
        faltan = []
        for destino, ficheros in self.MIGRADOS.items():
            presentes = {
                r.rsplit("/", 1)[-1] for r in _versionados(f"{destino}/test_*.py")
            }
            faltan += [f"{destino}/{f}" for f in ficheros if f not in presentes]

        assert faltan == [], (
            f"estos tests migrados desde el árbol de la raíz han desaparecido: {faltan}. "
            "No eran duplicados de `server/tests/`: ninguno de sus nombres de test coincidía"
        )


class TestElI18nDelLegacySeFue:
    """158 KB de traducciones de la interfaz NiceGUI, y el gestor que las leía."""

    def test_should_have_no_root_translations_file(self):
        assert not (RAIZ / "translations.json").exists(), (
            "`translations.json` volvió. El i18n de la plataforma es i18next, en "
            "`frontend/src/shared/i18n/`"
        )

    def test_should_have_no_legacy_i18n_module(self):
        assert not (RAIZ / "shared" / "automatia_shared" / "core" / "i18n.py").exists(), (
            "`automatia_shared.core.i18n` volvió: leía el `translations.json` de NiceGUI"
        )

    def test_should_not_be_re_exported_by_the_shared_package(self):
        """El `__init__.py` de `automatia_shared.core` lo re-exportaba.

        Un símbolo re-exportado desde un `__init__` sobrevive a que nadie lo importe por su
        nombre: `from automatia_shared.core import t` seguiría funcionando, y el módulo seguiría
        pareciendo vivo.

        **APER.12 retiró `automatia_shared/core/` entero**, así que hoy esto se cumple por la vía
        más contundente: no hay paquete del que re-exportar. La comprobación se queda —y admite
        las dos situaciones— porque lo que afirma es la garantía, no la forma de cumplirla: si
        alguien reconstruyera ese paquete, esto tiene que seguir mirando.
        """
        init = RAIZ / "shared" / "automatia_shared" / "core" / "__init__.py"
        if not init.exists():
            return

        texto = init.read_text(encoding="utf-8")
        for simbolo in ("i18n", "I18nManager"):
            assert f"import {simbolo}" not in texto and f" {simbolo}," not in texto, (
                f"`automatia_shared.core` sigue re-exportando `{simbolo}`"
            )


class TestElArranqueSigueArrancandoAlgoQueExiste:
    """El prompt pedía «comprobar si sigue arrancando algo que exista». Sí, y por eso se queda."""

    # `staticmethod` porque `pytest` 9.1 deprecó las *fixtures* de ámbito de clase declaradas
    # como método de instancia, y ésta no usa `self`.
    @staticmethod
    @pytest.fixture(scope="class")
    def arranque() -> str:
        return (RAIZ / "arranque.bat").read_text(encoding="latin-1")

    def test_should_launch_the_server_project(self, arranque: str):
        assert "uv run --project server uvicorn server.app.main:app" in arranque, (
            "`arranque.bat` tiene que invocar el proyecto uv del servidor por su nombre. Sin "
            "`--project server` dependía del `pyproject.toml` de la raíz, que NIC.4 retira"
        )

    def test_should_launch_the_react_frontend(self, arranque: str):
        assert "npm run dev" in arranque

    def test_should_not_offer_the_retired_desktop_app(self, arranque: str):
        """Tuvo una opción 3 que ejecutaba `uv run main.py`, el lanzador NiceGUI."""
        assert "main.py" not in arranque
        assert "nicegui" not in arranque.lower()
