"""AIS.2 — Lo específico de una institución no vive en el repositorio principal.

`CONTRIBUTING.md` lo dice como regla de gobernanza: *«Lo específico de una institución no entra
en el principal. Se queda en su fork y sube por pull request sólo si se puede generalizar.»* La
auditoría del 2026-08-24 encontró cuatro sitios donde eso no se cumplía, y ninguno es cosmético:

1. **La credencial de desarrollo lleva el correo del mantenedor del principal**
   (`DEV_ADMIN_EMAIL = "fabra@uji.es"`). Sólo se siembra en `development`, pero todo fork que
   arranque en local crea un superadministrador con el correo de otra persona.
2. **El prompt de sistema de Informes presume una universidad** («Eres un redactor de informes
   institucionales de una universidad pública»). El destinatario declarado del proyecto son
   varias administraciones y en particular **entidades locales**: un ayuntamiento que genere un
   informe recibe texto que le dice al modelo que es una universidad.
3. **Los spiders nombran una institución**: `"uji"` en el conjunto de tipos de fuente de
   normativa —con selectores que son un duplicado exacto de los de `boe`— y un spider entero
   dedicado al catálogo de procedimientos de un portal concreto.
4. **Docstrings que afirman cosas falsas** sobre el estado de la seguridad, que es peor que no
   decir nada: `seeds.py` seguía diciendo que el login de administrador no verifica contraseña
   —lo arregló SEC.1 hace bloques— y `main.py` anunciaba como «pendientes de registrar» dos
   routers que se borraron.

Lo que **no** es un hallazgo, y conviene dejarlo escrito para que nadie lo «arregle»: los tests
usan datos de la UJI como fixture, y varios a propósito —`org-uji` junto a `org-dipu` para probar
multitenencia con dos instituciones distintas—. Un fixture no viaja a ningún despliegue.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_APP = Path("app")

#: Instituciones concretas. `generalitat` y `dipu` entran porque el patrón tiene que servir para
#: cualquiera, no sólo para la de esta casa.
_INSTITUCIONES = re.compile(r"\b(uji|jaume|castell[oó]n?|innovap|generalitat)\b", re.IGNORECASE)

#: Separa las palabras pegadas en CamelCase **antes** de buscar la institución.
#:
#: Este guardarraíl estuvo verde durante semanas con tres clases llamadas
#: `UjiDualSourceRetrievalStrategy`, `UjiMergeStrategy` y `UjiAnswerTemplateStrategy` en el
#: perfil agregador. El motivo es que `\b(uji|…)\b` se aplicaba a la línea cruda y **en CamelCase
#: no hay frontera de palabra**: tras «Uji» viene una letra, así que el `\b` final no casa. Lo
#: mismo le pasaría a cualquier `HubUjiAlgo` que se escriba mañana.
#:
#: Se arregla **la entrada y no el patrón**, a propósito. Quitar el `\b` final haría casar
#: «castellano» —que sale por todo el código, es el nombre de una lengua— y a partir de ahí el
#: guardarraíl se desactivaría a base de excepciones. Con la línea ya separada, `\b…\b` sigue
#: siendo legible y sigue descartando «castellano».
#:
#: Las dos alternativas son el par estándar: minúscula→mayúscula (`UjiMerge` → `Uji Merge`) y
#: fin de acrónimo (`UJIMerge` → `UJI Merge`), que sin la segunda también se escaparía.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

#: Ficheros de código de producción, sin tests ni cuarentena.
def _codigo() -> list[Path]:
    return [p for p in _APP.rglob("*.py") if "__pycache__" not in p.parts]


def _lineas_con_institucion(ruta: Path, *, solo_codigo: bool) -> list[str]:
    """Las líneas que nombran una institución. Con `solo_codigo`, ignora comentarios y docstrings.

    La distinción importa: un comentario que explica **de dónde salió** un selector es
    documentación legítima —el portal existe y el dato es verificable—; una cadena en el código
    es comportamiento que se ejecuta en el despliegue de otro.
    """
    fuera = []
    en_docstring = False
    for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        limpia = linea.strip()
        if solo_codigo:
            comillas = limpia.count('"""') + limpia.count("'''")
            if en_docstring:
                if comillas:
                    en_docstring = False
                continue
            if comillas == 1:
                en_docstring = True
                continue
            if comillas >= 2 and (limpia.startswith('"""') or limpia.startswith("'''")):
                continue
            if limpia.startswith("#"):
                continue
            limpia = limpia.split("#", 1)[0]
        # Se busca sobre la línea con el CamelCase separado, pero se REPORTA la original: quien
        # lea el fallo tiene que ver el identificador tal como está escrito en el fichero.
        if _INSTITUCIONES.search(_CAMEL.sub(" ", limpia)):
            fuera.append(f"{ruta.as_posix()}:{numero} → {limpia[:110]}")
    return fuera


class TestLaCredencialDeDesarrolloNoEsDeNadie:

    def test_should_read_the_dev_superadmin_email_from_the_environment(self, monkeypatch):
        """Lo que vigila AIS.2 es el valor POR DEFECTO, no el que resuelve esta máquina.

        La versión anterior leía `seeds.DEV_ADMIN_EMAIL` ya resuelto, y `core/config.py` vuelca
        `server/.env` al entorno del proceso: un desarrollador que ponga
        `DEV_ADMIN_EMAIL=alguien@su-universidad.es` en su `.env` —que está en `.gitignore` y es
        **exactamente** lo que el propio AIS.2 manda hacer al fork— ponía este guardarraíl en
        rojo sin que el repositorio publicara nada institucional.

        El defecto era del test, no del código: confundía «lo que se publica» con «lo que corre
        aquí», que es justo la distinción que AIS.2 existe para mantener. Se comprueba sin
        entorno, que es lo que ve quien clona.
        """
        import importlib

        monkeypatch.delenv("DEV_ADMIN_EMAIL", raising=False)
        from server.app.database import seeds

        por_defecto = importlib.reload(seeds).DEV_ADMIN_EMAIL
        assert not _INSTITUCIONES.search(por_defecto), (
            f"el DEV_ADMIN_EMAIL por defecto vale {por_defecto!r}: todo fork que arranque en "
            "local sin configurar nada crea un superadministrador con el correo del mantenedor "
            "del principal"
        )

    def test_should_let_a_fork_choose_its_own_dev_credential(self, monkeypatch):
        monkeypatch.setenv("DEV_ADMIN_EMAIL", "admin@ayuntamiento.example")
        import importlib

        from server.app.database import seeds

        recargado = importlib.reload(seeds)
        assert recargado.DEV_ADMIN_EMAIL == "admin@ayuntamiento.example"
        # Y se deja como estaba para no contaminar a los demás tests del proceso.
        monkeypatch.delenv("DEV_ADMIN_EMAIL")
        importlib.reload(seeds)


class TestElPromptNoPresumeUnaUniversidad:

    def test_should_not_assume_the_kind_of_administration(self):
        from server.app.modules.redaccion.services.redactor_de_bloques import (
            SISTEMA_POR_DEFECTO,
        )

        assert "universidad" not in SISTEMA_POR_DEFECTO.lower(), (
            "el prompt de sistema presume una universidad, y el destinatario declarado del "
            "proyecto son varias administraciones y en particular entidades locales"
        )

    def test_should_offer_the_report_prompts_as_overridable_activities(self):
        """Los dos prompts de SEG.2 entran en el catálogo, así que una organización puede
        cambiarlos sin desplegar — que es el mecanismo que MT.6 ya construyó para los demás."""
        from server.app.modules.redaccion.services.actividades_llm import (
            ActividadLLM,
            PARA_QUE_SIRVE,
            PROMPT_POR_ACTIVIDAD,
            TIER_POR_ACTIVIDAD,
        )

        esperadas = {"valoracion_de_tendencia", "resumen_de_resultados"}
        declaradas = {str(a) for a in ActividadLLM}
        faltan = esperadas - declaradas
        assert faltan == set(), f"actividades sin declarar: {faltan}"

        for actividad in ActividadLLM:
            if str(actividad) not in esperadas:
                continue
            assert actividad in PROMPT_POR_ACTIVIDAD
            assert actividad in TIER_POR_ACTIVIDAD
            assert actividad in PARA_QUE_SIRVE

    def test_should_let_the_redactor_receive_resolved_instructions(self):
        """Sin esto el catálogo sería decorativo: `RedactorDeBloques` resolvía el prompt con un
        `dict` del módulo, así que el override de la base de datos no llegaba nunca."""
        from server.app.modules.redaccion.services.redactor_de_bloques import RedactorDeBloques

        redactor = RedactorDeBloques(
            object(), "m", instrucciones={"valoracion_de_tendencia_v1": "EL DE LA ORGANIZACIÓN"}
        )
        assert redactor.instruccion("valoracion_de_tendencia_v1") == "EL DE LA ORGANIZACIÓN"
        # Lo que el override no define sigue saliendo del catálogo del módulo.
        assert "sección" in redactor.instruccion("generic_report_v1").lower()


class TestLosSpidersNoNombranUnPortal:

    def test_should_not_name_an_institution_in_the_source_types(self):
        from server.app.modules.curation import spider_factory

        tipos = {
            t.lower()
            for t in getattr(spider_factory, "_NORMATIVA_SOURCE_TYPES", set())
        }
        assert not any(_INSTITUCIONES.search(t) for t in tipos), (
            f"tipos de fuente con nombre de institución: {tipos}. El tipo describe la FORMA "
            "del portal, no de quién es; y los selectores de esa entrada eran un duplicado "
            "exacto de los de `boe`."
        )

    def test_should_not_ship_a_spider_for_one_institution_portal(self):
        rutas = list(Path("app/modules/curation/spiders").glob("*.py"))
        culpables = [
            r.as_posix()
            for r in rutas
            if _lineas_con_institucion(r, solo_codigo=True)
        ]
        assert culpables == [], (
            f"código de spider que nombra una institución: {culpables}. Un portal concreto es "
            "material de fork (CONTRIBUTING.md): sus selectores son configuración del sitio."
        )


class TestNingunDocstringMienteSobreLaSeguridad:

    @pytest.mark.parametrize(
        ("ruta", "frase"),
        [
            ("app/database/seeds.py", "no verifica pwd"),
            ("app/main.py", "pendientes de registrar"),
        ],
    )
    def test_should_not_describe_a_state_that_no_longer_exists(self, ruta: str, frase: str):
        texto = Path(ruta).read_text(encoding="utf-8")
        assert frase not in texto, (
            f"{ruta} sigue diciendo «{frase}», que dejó de ser cierto. Un comentario que "
            "describe un agujero ya cerrado hace perder el tiempo a quien audita, y uno que "
            "describe trabajo ya hecho manda a buscar lo que no está."
        )


class TestElCodigoDeProduccionEstaLimpio:
    """El barrido general. Se mira **sólo el código**: los comentarios de procedencia —de qué
    portal salió un selector, qué acrónimos manda un IdP— son documentación verificable."""

    def test_should_not_name_an_institution_in_production_code(self):
        culpables: list[str] = []
        for ruta in _codigo():
            culpables += _lineas_con_institucion(ruta, solo_codigo=True)

        assert culpables == [], (
            "código de producción que nombra una institución concreta:\n  "
            + "\n  ".join(culpables)
        )
