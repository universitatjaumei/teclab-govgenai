"""APER.6 — `dependabot.yml` vigila rutas que existen y no despliega al mezclarse.

**Hallazgo B4 de la auditoría previa a abrir el repositorio**: no había nada que avisara de una
dependencia vulnerable. Las dos que se encontraron a mano —`js-yaml` por `orval` y
`@vitest/mocker` por `vitest`— llevaban meses ahí.

**Por qué hace falta un test para un fichero de configuración.** Porque una configuración de
Dependabot inválida **no hace nada y no avisa**: no rompe ningún build, no pone rojo ningún job,
simplemente no se abren PR. Es exactamente la forma de fallar que este proyecto ya conoce —«un
guardarraíl que no mira nada pasa en verde»—, y con un fichero que nadie vuelve a abrir en un año
es la más probable.

Lo que este test **sí** puede comprobar: que cada ruta vigilada existe y contiene el manifiesto
que su ecosistema necesita, que no falta ninguno de los proyectos del repositorio, y que las
actualizaciones de versión van a `desarrollo` y no a `main`.

Lo que **no** puede: que GitHub acepte los nombres de ecosistema. Eso se ve en la pestaña
Dependabot del repositorio después del primer push, y está dicho en el propio fichero.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
CONFIG = RAIZ / ".github" / "dependabot.yml"

#: Los nombres que GitHub documenta y que este repositorio usa, copiados el 2026-09-18. La lista
#: está para cazar un typo (`github_actions` por `github-actions`), no para ser exhaustiva: un
#: nombre que GitHub no reconoce deja su entrada sin efecto **y no avisa**, que es el modo de
#: fallo del §9.8 del marco. La fecha está para saber contra qué documentación se comparó.
#: `docker-compose` se añadió con #268: el ecosistema `docker` sólo lee los Dockerfile.
ECOSISTEMAS_CONOCIDOS = {"uv", "pip", "npm", "github-actions", "docker", "docker-compose"}

#: Qué fichero tiene que haber en la ruta para que vigilarla signifique algo.
MANIFIESTO_DE = {
    "uv": ("pyproject.toml", "uv.lock"),
    "pip": ("pyproject.toml",),
    "npm": ("package.json",),
    "docker": ("Dockerfile",),
    "docker-compose": ("docker-compose.yml", "docker-compose.vm.yml"),
    "github-actions": (".github/workflows",),
}


@pytest.fixture(scope="module")
def entradas() -> list[dict]:
    assert CONFIG.is_file(), (
        "No hay .github/dependabot.yml. Sin él nada avisa de una dependencia vulnerable: "
        "las cinco de la auditoría llevaban meses ahí."
    )
    datos = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert datos.get("version") == 2, "dependabot.yml tiene que declarar `version: 2`"
    return datos["updates"]


def _rutas_de(entrada: dict) -> list[str]:
    """`directory` o `directories`: Dependabot admite las dos formas."""
    if "directories" in entrada:
        return list(entrada["directories"])
    return [entrada["directory"]]


class TestVigilaRutasQueExisten:

    def test_cada_ecosistema_tiene_un_nombre_conocido(self, entradas: list[dict]) -> None:
        for entrada in entradas:
            eco = entrada["package-ecosystem"]
            assert eco in ECOSISTEMAS_CONOCIDOS, (
                f"«{eco}» no es un ecosistema que este repositorio use. Un nombre que GitHub no "
                "entiende deja la configuración inválida, y una configuración inválida no abre "
                "ninguna PR sin decir nada."
            )

    def test_cada_ruta_existe_y_lleva_su_manifiesto(self, entradas: list[dict]) -> None:
        for entrada in entradas:
            eco = entrada["package-ecosystem"]
            for ruta in _rutas_de(entrada):
                carpeta = RAIZ / ruta.lstrip("/")
                assert carpeta.is_dir(), f"{eco}: la ruta vigilada «{ruta}» no existe"
                esperados = MANIFIESTO_DE[eco]
                assert any((carpeta / nombre).exists() for nombre in esperados), (
                    f"{eco}: «{ruta}» no contiene ninguno de {esperados}, así que vigilarla no "
                    "puede encontrar nada."
                )


class TestNoSeQuedaNingunProyectoFuera:
    """Si mañana nace un proyecto con su lock, tiene que entrar aquí o este test se pone rojo."""

    def test_todos_los_proyectos_con_uv_lock_estan_vigilados(
        self, entradas: list[dict]
    ) -> None:
        vigiladas = {
            ruta.rstrip("/") or "/"
            for entrada in entradas
            if entrada["package-ecosystem"] in {"uv", "pip"}
            for ruta in _rutas_de(entrada)
        }
        for lock in RAIZ.glob("*/uv.lock"):
            ruta = "/" + lock.parent.relative_to(RAIZ).as_posix()
            assert ruta in vigiladas, f"{ruta} tiene uv.lock y nadie vigila sus dependencias"
        for lock in RAIZ.glob("*/*/uv.lock"):
            ruta = "/" + lock.parent.relative_to(RAIZ).as_posix()
            assert ruta in vigiladas, f"{ruta} tiene uv.lock y nadie vigila sus dependencias"

    def test_todos_los_dockerfile_estan_vigilados(self, entradas: list[dict]) -> None:
        vigiladas = {
            ruta.rstrip("/") or "/"
            for entrada in entradas
            if entrada["package-ecosystem"] == "docker"
            for ruta in _rutas_de(entrada)
        }
        for dockerfile in (*RAIZ.glob("Dockerfile"), *RAIZ.glob("*/Dockerfile"),
                           *RAIZ.glob("*/*/Dockerfile")):
            relativa = dockerfile.parent.relative_to(RAIZ).as_posix()
            ruta = "/" if relativa == "." else "/" + relativa
            assert ruta in vigiladas, (
                f"{dockerfile.relative_to(RAIZ)} declara una imagen base y nadie la vigila. "
                "Con el repositorio público, una base sin actualizar es superficie."
            )


class TestNoDespliegaAlMezclarse:
    """La regla dura del proyecto, aplicada a las PR que abre un robot."""

    def test_las_actualizaciones_de_version_van_a_desarrollo(
        self, entradas: list[dict]
    ) -> None:
        for entrada in entradas:
            eco = entrada["package-ecosystem"]
            assert entrada.get("target-branch") == "desarrollo", (
                f"{eco} no fija `target-branch: desarrollo`. `deploy.yml` dispara con "
                "`push: branches: [main]`, así que una PR de actualización contra `main` "
                "despliega producción al mezclarse."
            )

    def test_el_fichero_dice_que_las_de_seguridad_van_por_otro_sitio(self) -> None:
        """La trampa de `target-branch`: no gobierna las PR de seguridad.

        Sin esto escrito, quien lea sólo la configuración concluirá que **ninguna** PR de
        Dependabot puede tocar `main`, y eso es falso: las de seguridad las abre GitHub contra
        la rama por omisión. Es justo el tipo de suposición que hace que se mezcle una sin
        mirar.
        """
        # La prosa de un comentario va partida en líneas y con `#` delante, así que buscar la
        # frase tal cual falla por el sitio donde cayó el salto — y no por lo que dice. Es el
        # mismo tropiezo que tuvo el guardarraíl de FUN.7, resuelto igual.
        prosa = " ".join(
            linea.lstrip("# ").strip()
            for linea in CONFIG.read_text(encoding="utf-8").splitlines()
            if linea.lstrip().startswith("#")
        )
        prosa = " ".join(prosa.split())
        assert "seguridad" in prosa and "rama por omisión" in prosa, (
            "dependabot.yml no advierte de que las actualizaciones de seguridad no obedecen a "
            "`target-branch`."
        )


class TestLlegaEnLotesRevisables:

    def test_cada_entrada_agrupa_sus_actualizaciones(self, entradas: list[dict]) -> None:
        """Veinte PR sueltas a la semana se revisan como se revisa el correo basura."""
        for entrada in entradas:
            eco = entrada["package-ecosystem"]
            assert entrada.get("groups"), f"{eco} no agrupa: llegaría como PR sueltas"

    def test_los_grupos_no_se_llevan_los_saltos_de_version_mayor(
        self, entradas: list[dict]
    ) -> None:
        """APER.13 — agrupar **todo** produjo un lote que no se podía revisar ni mezclar.

        La primera tanda llegó con `patterns: ["*"]` sin límite de tipo: una PR con **33
        paquetes**, seis saltos de versión mayor y **dos rebajas** que no se veían en el muro de
        changelogs —`browser-use` de 0.11.3 a 0.5.5 habiendo 0.13.10, y `ragas` de 0.4.3 a
        0.3.1 cuando 0.4.3 es la última—. No eran actualizaciones: eran el precio de resolver 33
        cosas a la vez, y el resolutor sacrificó esas dos para encajar el resto.

        Con el límite, un mayor llega en su propia PR y se juzga solo. Es la única forma de
        decidir sobre un `openai` 2→3.
        """
        for entrada in entradas:
            eco = entrada["package-ecosystem"]
            for nombre, grupo in entrada["groups"].items():
                tipos = grupo.get("update-types")
                assert tipos, (
                    f"{eco}/{nombre} agrupa sin declarar `update-types`, así que se llevaría "
                    "también los saltos de versión mayor."
                )
                assert set(tipos) <= {"minor", "patch"}, (
                    f"{eco}/{nombre} agrupa {tipos}. Un `major` dentro de un grupo hace el lote "
                    "irrevisable y puede arrastrar rebajas de otros paquetes."
                )
