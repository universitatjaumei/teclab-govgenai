"""APER.18 — la pila de modelos locales se elige al desplegar, no editando el `Dockerfile`.

**De dónde sale.** `local-models` —`torch`, `torchvision`, `sentence-transformers`— es la pila que
hace funcionar los embeddings BGE-M3 y el reranker **en la propia máquina**, sin que los datos
salgan a una API. Se queda en el proyecto porque es lo que permite que otra administración
despliegue con modelos locales; pero no se instala en el despliegue estándar, porque son cientos
de megas y una VM mayor.

Eso último **ya era cierto**: la imagen hace `uv sync --frozen --no-dev --no-editable`, sin
extras. Lo que faltaba era el interruptor: para tener una imagen con modelos locales había que
editar el `Dockerfile`.

**Y la trampa que había que resolver de paso.** `construir_si_falta` no reconstruye si la
etiqueta ya está publicada, y la etiqueta es el SHA del commit. Sin meter la variante en la
etiqueta, activar el interruptor y redespliegar el mismo SHA se habría llevado **la imagen
anterior** — la sin modelos— sin decir nada. Es el fallo que se diagnostica una hora buscando en
el sitio equivocado.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
DOCKERFILE = RAIZ / "Dockerfile"
DEPLOY = RAIZ / ".github" / "workflows" / "deploy.yml"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def paso_de_construccion() -> str:
    """El paso que construye y publica las imágenes, buscado por lo que hace y no por su nombre.

    Buscarlo por el nombre falló al escribir esto —el job se llama `desplegar`, no `deploy`— y
    un guardarraíl que no encuentra su objeto da error en vez de comprobar nada.
    """
    datos = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    for cuerpo in datos["jobs"].values():
        for paso in cuerpo.get("steps", []):
            if "docker build" in (paso.get("run") or ""):
                return paso["run"]
    raise AssertionError("no encuentro el paso que construye las imágenes")


class TestLaImagenAdmiteElExtra:

    def test_declara_el_argumento(self, dockerfile: str) -> None:
        assert "ARG EXTRAS_APP" in dockerfile, (
            "El `Dockerfile` no admite extras como argumento de construcción, así que la única "
            "forma de tener modelos locales es editarlo."
        )

    def test_el_sync_lo_usa(self, dockerfile: str) -> None:
        linea = next(
            (linea for linea in dockerfile.splitlines() if linea.startswith("RUN uv sync")), None
        )
        assert linea is not None, "no encuentro el `uv sync` de la imagen"
        assert "${EXTRAS_APP}" in linea, (
            f"El `uv sync` no usa el argumento: «{linea}». Declararlo y no usarlo es peor que "
            "no tenerlo, porque parece configurable."
        )

    def test_por_omision_no_instala_nada_extra(self, dockerfile: str) -> None:
        """El despliegue estándar se queda como está: sin `torch` y sin VM mayor."""
        declaracion = next(
            linea.strip() for linea in dockerfile.splitlines() if linea.strip().startswith("ARG EXTRAS_APP")
        )
        assert declaracion in ('ARG EXTRAS_APP=""', "ARG EXTRAS_APP="), (
            f"El valor por omisión no está vacío: «{declaracion}». El despliegue estándar no "
            "puede engordar por un interruptor que nadie ha tocado."
        )


class TestElDespliegueLoPasa:

    def test_pasa_el_build_arg(self, paso_de_construccion: str) -> None:
        assert "--build-arg" in paso_de_construccion, (
            "El workflow no pasa el extra a `docker build`, así que el argumento del "
            "`Dockerfile` no se puede activar desde el despliegue."
        )
        assert "EXTRAS_APP" in paso_de_construccion, (
            "El workflow no pasa el extra a `docker build`, así que el argumento del "
            "`Dockerfile` no se puede activar desde el despliegue."
        )

    def test_sale_de_una_variable_del_repositorio(self, paso_de_construccion: str) -> None:
        """La elección es de cada despliegue, así que vive en su configuración y no en el código."""
        assert "vars." in paso_de_construccion, (
            "El extra no sale de una variable del repositorio: habría que cambiar código para "
            "cambiar de despliegue."
        )
        assert "EXTRAS" in paso_de_construccion, (
            "El extra no sale de una variable del repositorio: habría que cambiar código para "
            "cambiar de despliegue."
        )


class TestLaVarianteVaEnLaEtiqueta:
    """La trampa: sin esto, activar el interruptor no cambia la imagen que se despliega."""

    def test_la_etiqueta_distingue_la_variante(self, paso_de_construccion: str) -> None:
        assert "SUFIJO" in paso_de_construccion or "VARIANTE" in paso_de_construccion, (
            "La etiqueta de la imagen no distingue si lleva modelos locales. "
            "`construir_si_falta` no reconstruye si la etiqueta ya existe, y la etiqueta es el "
            "SHA: activar el extra y redespliegar el mismo commit se llevaría la imagen "
            "anterior, sin modelos, y sin decir nada."
        )

    def test_se_despliega_la_etiqueta_que_se_ha_publicado(
        self, paso_de_construccion: str
    ) -> None:
        """La que se construye y la que se le anuncia al despliegue tienen que ser **la misma**.

        Es el agujero que dejó la primera versión de APER.18: el sufijo estaba en la etiqueta
        que se **publica** y no en la que se **anuncia**, así que con el interruptor puesto se
        subía `app:$SHA-local-models` y a la VM se le pasaba `app:$SHA`. El mismo fallo que el
        sufijo venía a cerrar, una línea más abajo.

        Y con la misma forma traicionera: si un despliegue estándar anterior del mismo commit
        publicó `app:$SHA`, activar el interruptor arrastraría **esa** imagen —la que no lleva
        modelos— sin decir nada; y si no lo publicó, el despliegue se cae tirando de una
        etiqueta que esta ejecución no ha construido.

        Se comprueba **comparando las dos expresiones de etiqueta**, no buscando `SUFIJO` en la
        segunda: lo que importa es que coincidan, se llame como se llame la variable.
        """
        construida = re.search(
            r"^\s*construir_si_falta\s+app\s+\S+\s+\S+\s+\"([^\"]+)\"",
            paso_de_construccion,
            re.MULTILINE,
        )
        assert construida, "no encuentro con qué etiqueta se construye la imagen del servidor"

        anunciada = re.search(
            r"^\s*echo\s+\"app=[^:\"]+:([^\"]+)\"", paso_de_construccion, re.MULTILINE
        )
        assert anunciada, "no encuentro qué etiqueta se le anuncia al paso de despliegue"

        assert construida.group(1) == anunciada.group(1), (
            f"Se publica `app:{construida.group(1)}` y se despliega `app:{anunciada.group(1)}`. "
            "Con el interruptor de modelos locales puesto son etiquetas distintas, así que la "
            "VM tira de una imagen que esta ejecución no ha construido: o falla, o arrastra en "
            "silencio la imagen sin modelos de un despliegue anterior del mismo commit."
        )

    def test_solo_la_imagen_del_servidor_lo_recibe(self, paso_de_construccion: str) -> None:
        """El frontend, el sandbox y el MCP no tienen ese extra: pasárselo sería ruido."""
        lineas = [
            linea.strip() for linea in paso_de_construccion.splitlines()
            if linea.strip().startswith("construir_si_falta")
        ]
        assert lineas, "no encuentro las llamadas que construyen cada imagen"
        con_extra = [linea for linea in lineas if "EXTRAS" in linea or "SUFIJO" in linea or "VARIANTE" in linea]
        assert len(con_extra) <= 1, (
            f"Más de una imagen recibe el extra: {con_extra}. Sólo la del servidor lo tiene."
        )
