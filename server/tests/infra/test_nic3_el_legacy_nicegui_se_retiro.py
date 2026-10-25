"""NIC.3 — `client_app/` y `_legacy_nicegui/` se retiran completos, y la referencia queda fuera.

**El prompt decía «`client_app/` queda reducido a su única razón de existir»: el agente de
ejecución local.** NIC.2 midió que ese agente **no arranca**: `workflow_engine.py`, el motor por
el que ejecutan los dos vigilantes, importa en sus líneas 1478 y 1604 dos módulos que ya no
existen en `client_app/`, y hay 28 imports más en el mismo estado. Reducir el directorio al agente
habría dejado un agente roto y la impresión de que funciona.

**Decisión del usuario (2026-09-04): se retiran los dos directorios completos**, porque el
repositorio se va a abrir y 500 ficheros de una aplicación que no compila no se distinguen de
código vivo por quien llegue de fuera.

La referencia se conserva en tres sitios, ninguno dentro del repositorio:

1. **El historial de git de este repositorio** — borrar del árbol no borra del historial, y es la
   referencia que viaja con el repositorio y no se puede perder.
2. `C:\\Users\\fabra\\Documents\\AutomatIA`, la aplicación NiceGUI completa.
3. El *bundle* de GenGov.

Y `docs/INVENTARIO_RETIRADA_LEGACY.md` es el mapa: dice fichero a fichero qué tenía equivalente y
dónde, que es lo que hay que leer antes de ir a buscar código a cualquiera de las tres.

**Lo que estos tests vigilan no es el borrado —eso se ve—, sino las dos cosas que se olvidan
después**: que no quede nada apuntando a lo retirado, y que la documentación **deje de prometer un
nodo de ejecución local que ya no tiene código**. Un repositorio que abre limpio y describiendo
algo que no existe es peor que uno que abre sucio.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]

RETIRADOS = ("client_app", "_legacy_nicegui", "_legacy_archive")


def _versionados(*patrones: str) -> list[str]:
    salida = subprocess.run(
        ["git", "ls-files", *patrones],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=True,
    )
    return [linea for linea in salida.stdout.splitlines() if linea.strip()]


class TestLosDirectoriosSeFueron:

    @pytest.mark.parametrize("directorio", RETIRADOS)
    def test_should_have_no_versioned_files_left(self, directorio: str):
        quedan = _versionados(directorio)
        assert quedan == [], (
            f"{directorio}/ sigue teniendo {len(quedan)} ficheros versionados: {quedan[:5]}"
        )

    @pytest.mark.parametrize("directorio", RETIRADOS)
    def test_should_not_exist_on_disk_either(self, directorio: str):
        """Sin restos sin versionar: un directorio con `__pycache__` dentro sigue pareciendo código."""
        ruta = RAIZ / directorio
        assert not ruta.exists(), f"{directorio}/ sigue en el disco"


class TestNadaApuntaALoRetirado:

    def test_should_have_no_python_imports_left(self):
        """Ningún módulo del proyecto importa ya nada del legacy.

        Se buscan **formas de import** y no la mención del nombre: los comentarios de procedencia
        del servidor («Migrado desde `client_app/app/modules/privacy/anonymizer.py`») nombran
        ficheros del legacy a propósito, y son documentación buena que no hay que borrar.
        """
        import re

        ofensores = []
        for fichero in _versionados("*.py"):
            texto = (RAIZ / fichero).read_text(encoding="utf-8", errors="replace")
            if re.search(
                r"^\s*(?:from\s+client_app[\w.]*\s+import|import\s+client_app\b)",
                texto,
                re.MULTILINE,
            ):
                ofensores.append(fichero)

        assert ofensores == [], f"todavía importan del legacy: {ofensores}"

    def test_should_not_be_referenced_by_configuration(self):
        """Ni en `pyproject.toml`, ni en CI, ni en los ficheros de Docker.

        Una ruta muerta en la configuración no falla hoy y falla el día que alguien la use.
        """
        sospechosos = [
            "pyproject.toml",
            ".github/workflows/ci.yml",
            ".github/workflows/deploy.yml",
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "Dockerfile",
        ]
        ofensores = []
        for nombre in sospechosos:
            ruta = RAIZ / nombre
            if not ruta.is_file():
                continue
            for linea in ruta.read_text(encoding="utf-8").splitlines():
                limpia = linea.strip()
                if limpia.startswith("#") or not limpia:
                    continue
                if "client_app" in limpia or "_legacy_nicegui" in limpia:
                    ofensores.append(f"{nombre}: {limpia[:70]}")

        assert ofensores == [], f"la configuración todavía los nombra: {ofensores}"


class TestLaDocumentacionDejaDePrometerElAgente:
    """La mitad que se olvida: si el código se va, los documentos tienen que dejar de afirmarlo."""

    def test_should_say_in_agents_that_the_local_agent_will_not_be_built(self):
        """`AGENTS.md` describía `client_app/` como el agente de ejecución local.

        Si sigue diciéndolo, quien llegue de fuera buscará un directorio que no existe — y quien
        planifique creerá que hay una base sobre la que seguir.

        **La afirmación se endureció el 2026-09-23** (issue #112). Hasta entonces bastaba con
        decir que el agente no tenía código, porque era un hueco; ahora es una **decisión**, y lo
        que hay que impedir es que alguien lo lea como trabajo pendiente y lo proponga. Un test
        que siguiera aceptando «sin código en el repositorio» pasaría en verde con el documento
        diciendo lo contrario de lo que se decidió.
        """
        texto = (RAIZ / "AGENTS.md").read_text(encoding="utf-8")

        assert "client_app/` ← SOLO agente de ejecución local" not in texto, (
            "el mapa de módulos sigue describiendo `client_app/` como si existiera"
        )
        assert "no se hace" in texto, (
            "`AGENTS.md` tiene que decir que el agente local **no se hace** y que no se proponga. "
            "Es una decisión (ESPECIFICACIONES.md §10), no trabajo pendiente."
        )
        assert "No lo propongas" in texto, (
            "`AGENTS.md` tiene que decir que el agente local **no se hace** y que no se proponga. "
            "Es una decisión (ESPECIFICACIONES.md §10), no trabajo pendiente."
        )

    def test_should_record_it_in_the_specification(self):
        """`docs/ESPECIFICACIONES.md` §10 dice qué NO hace la plataforma. Esto va ahí."""
        texto = (RAIZ / "docs" / "ESPECIFICACIONES.md").read_text(encoding="utf-8")
        seccion = texto.split("## 10. Qué NO hace la plataforma", 1)
        assert len(seccion) == 2, "falta la §10"
        cuerpo = seccion[1].split("## 11.", 1)[0]

        assert "agente" in cuerpo.lower(), "§10 tiene que decir que no hay agente de ejecución local"
        assert "local" in cuerpo.lower(), "§10 tiene que decir que no hay agente de ejecución local"

    def test_should_point_at_the_three_references(self):
        """Y decir dónde está el código, o «se retiró» es «se perdió» para quien lea."""
        texto = (RAIZ / "docs" / "INVENTARIO_RETIRADA_LEGACY.md").read_text(encoding="utf-8")

        assert "historial de git" in texto
        assert "AutomatIA" in texto
        assert "GenGov" in texto

    def test_should_not_keep_a_guardrail_that_measures_nothing(self):
        """El guardarraíl de NIC.1 se retiró aquí, y esto impide que vuelva.

        `test_nic1_el_inventario_esta_completo.py` cruzaba `git ls-files client_app/app/ui` y
        `app/services` contra la tabla del inventario: si alguien añadía un fichero sin
        inventariarlo, rojo. Era un buen guardarraíl **mientras hubiera directorio que cruzar**.

        Retirado `client_app/`, `git ls-files` devuelve la lista vacía y sus cuatro tests de cruce
        —«toda ruta tiene fila», «toda fila tiene etiqueta», «ninguna justificación vacía»— iteran
        sobre nada y **pasan en verde sin mirar nada**. Es la peor forma de fallo de un guardarraíl,
        porque el verde se lee como «comprobado».

        Lo que de él seguía significando algo es el test de al lado: que el inventario conserve su
        tabla. Eso no depende de que los ficheros existan, y es lo que hace útiles a las tres
        referencias externas.
        """
        muerto = RAIZ / "server" / "tests" / "infra" / "test_nic1_el_inventario_esta_completo.py"
        assert not muerto.exists(), (
            "el guardarraíl de NIC.1 volvió, y sin `client_app/` cruza la lista vacía: "
            "pasaría en verde sin comprobar nada"
        )

    def test_should_keep_the_inventory_as_the_map(self):
        """El inventario sobrevive a la retirada: es lo que se lee antes de buscar el código.

        Sus filas siguen citando rutas de `client_app/`, y eso es correcto — describen lo que
        había. Lo que no puede es desaparecer, porque entonces las tres referencias son un
        montón de ficheros sin índice.
        """
        inventario = RAIZ / "docs" / "INVENTARIO_RETIRADA_LEGACY.md"
        assert inventario.is_file()
        texto = inventario.read_text(encoding="utf-8")
        assert texto.count("| `client_app/") >= 180, (
            "el inventario tiene que conservar su tabla fichero a fichero"
        )
