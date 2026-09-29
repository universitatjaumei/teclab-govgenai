"""AUT.9 (issue #119) — el ecosistema autorizado vive en tres sitios y ninguno puede irse solo.

**Qué es «el ecosistema autorizado».** La lista de módulos que una función del catálogo puede
importar. La fija la institución (hito «Automatización gobernada 4») y la plataforma la aplica.

**Y está escrita tres veces**, porque la defensa en profundidad lo exige:

1. `server/app/modules/redaccion/services/script_auditor.py` — la audita la API, antes de
   enviar nada al sandbox.
2. `services/script_sandbox/sandbox/auditor.py` — la copia defensiva, autocontenida, que
   vuelve a auditar **justo antes del `exec`**. Su contrato (`docs/SANDBOX_SECURITY.md`) es ser
   **más** estricta que la de la API, nunca menos.
3. `services/script_sandbox/pyproject.toml` — lo que la imagen instala de verdad, que es lo
   único que un `import` encuentra a las tres de la mañana.

Las tres pueden divergir, y **divergían**: `fitz` —PyMuPDF— estaba permitido en las dos listas
y **no instalado** en la imagen. Un guion que lo importara pasaba las dos auditorías y moría con
`ModuleNotFoundError` dentro del sandbox, que es el peor sitio para enterarse: el error no dice
«esto no está autorizado», dice «esto está roto».

**Los dos sentidos importan, y por motivos distintos.** Permitir lo que no está instalado
promete una capacidad que no existe. Instalar lo que no está permitido deja código alcanzable
que nadie ha revisado — y ahí no vale el `ModuleNotFoundError` como red, porque no salta.

**Esta lista sigue en código y no en tabla**, a diferencia del vocabulario del corpus. La regla
«vocabulario como dato» es para taxonomías que se revisan a menudo; una lista blanca de
seguridad cambia por despliegue y con revisión, y así queda auditada en el historial de git.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import tomllib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]
SANDBOX = RAIZ / "services" / "script_sandbox"


def DISTRIBUCION_DE() -> dict[str, str | None]:
    """De qué distribución instalable viene cada módulo permitido (`None` si es estándar).

    **Esto nació como una tabla en este fichero y duró una hora.** La escribí aquí y acto seguido
    el mismo dato hizo falta en el contrato, porque quien escribe el guion fuera necesita saber
    que `import fitz` se instala como `pymupdf`. Un dato que la aplicación sirve no puede tener
    su copia en un test: serían dos listas más que pueden divergir, y este fichero existe
    precisamente para que no haya listas que divergen en silencio.

    Así que se lee de `CATALOGO_DE_MODULOS`, que es producción. Y el test de que está **completa**
    se queda, sólo que ahora vigila la ficha de verdad: un módulo permitido sin ficha se queda
    fuera de esta comprobación, que es exactamente cómo `fitz` pasó meses permitido y ausente.
    """
    from server.app.modules.redaccion.services.script_auditor import CATALOGO_DE_MODULOS

    return {ficha.modulo: ficha.instala for ficha in CATALOGO_DE_MODULOS}


#: Dependencias que la imagen instala **para el servicio**, no para los guiones: son el propio
#: microservicio HTTP. No están en la lista blanca, y no deben estarlo — `fastapi` y `uvicorn`
#: están además en la lista de prohibidos explícitos.
DEL_SERVICIO: frozenset[str] = frozenset({"fastapi", "pydantic", "uvicorn"})

_NOMBRE = re.compile(r"^[A-Za-z0-9._-]+")


def _lista_de_la_api() -> frozenset[str]:
    from server.app.modules.redaccion.services.script_auditor import WHITELIST_MODULES

    return WHITELIST_MODULES


def _lista_del_sandbox() -> frozenset[str]:
    """Se carga **por ruta**, no por import.

    `services/script_sandbox` es otro proyecto con su propio entorno y no está en el `sys.path`
    de la suite. Cargarlo así es justamente lo que mantiene la copia autocontenida: si algún día
    dejara de poder cargarse suelta, es que ha empezado a importar cosas de `server/app`, y el
    fichero dice en su primera línea que no debe.
    """
    ruta = SANDBOX / "sandbox" / "auditor.py"
    spec = importlib.util.spec_from_file_location("_sandbox_auditor_aut9", ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    try:
        spec.loader.exec_module(modulo)
        return modulo.WHITELIST_MODULES
    finally:
        sys.modules.pop(spec.name, None)


def _del_ecosistema() -> set[str]:
    """Las distribuciones que hay que instalar **porque** un módulo permitido las necesita."""
    return {
        distribucion.replace("_", "-").lower()
        for modulo, distribucion in DISTRIBUCION_DE().items()
        if distribucion is not None and modulo in _lista_de_la_api()
    }


def _dependencias_de_la_imagen() -> set[str]:
    """Las dependencias **directas** del `pyproject.toml`, normalizadas.

    Directas y no el árbol entero resuelto: lo que se vigila es lo que alguien declara a mano.
    Una transitiva que aparezca sola no es una decisión de nadie, y exigir clasificarlas todas
    convertiría este guardarraíl en ruido que se apaga.
    """
    datos = tomllib.loads((SANDBOX / "pyproject.toml").read_text(encoding="utf-8"))
    crudas = datos["project"]["dependencies"]
    nombres = set()
    for cruda in crudas:
        casado = _NOMBRE.match(cruda.strip())
        assert casado, f"no sé leer la dependencia «{cruda}»"
        # `uvicorn[standard]` → `uvicorn`; los guiones y los puntos se normalizan como en PEP 503.
        nombres.add(casado.group(0).split("[")[0].replace("_", "-").lower())
    return nombres


class TestLaTablaSeMantieneCompleta:
    """Sin esto, lo demás se cumple por no mirar: un módulo sin ficha no se comprueba.

    Que la ficha **exista** para cada módulo permitido, que **diga para qué sirve** y que no
    sobre ninguna lo comprueba el contrato, en
    `tests/modules/redaccion/test_aut9_la_caja_dice_para_que_sirve_cada_modulo.py`. Aquí se
    vuelve a mirar sólo lo que este fichero necesita para que su conclusión valga: que no haya
    un permitido del que no sepamos qué se instala. Es una línea, y es la que sostiene todo lo
    de abajo.
    """

    def test_todo_modulo_permitido_dice_de_donde_sale(self):
        sin_clasificar = sorted(_lista_de_la_api() - DISTRIBUCION_DE().keys())

        assert not sin_clasificar, (
            f"estos módulos están permitidos y no dicen de qué distribución vienen: "
            f"{sin_clasificar}. Les falta la ficha en CATALOGO_DE_MODULOS —con `instala=None` si "
            f"son de la biblioteca estándar— y sin ella el resto de este fichero no los mira."
        )


class TestLoPermitidoEstaInstalado:

    def test_toda_distribucion_de_un_modulo_permitido_la_declara_la_imagen(self):
        """El caso de `fitz`: permitido, prometido en la API, y ausente de la imagen."""
        declaradas = _dependencias_de_la_imagen()

        faltan = sorted(_del_ecosistema() - declaradas)

        assert not faltan, (
            f"la lista blanca permite importar módulos que la imagen del sandbox no instala: "
            f"{faltan}. Un guion que los importe pasa las dos auditorías y muere con "
            f"ModuleNotFoundError dentro del sandbox."
        )


class TestLoInstaladoEstaClasificado:

    def test_ninguna_dependencia_de_la_imagen_queda_sin_explicar(self):
        """El sentido contrario: código alcanzable que nadie ha decidido que lo sea.

        Aquí no hay `ModuleNotFoundError` que avise. Si alguien añade una dependencia al
        `pyproject.toml` del sandbox, queda importable desde dentro del contenedor, y lo único
        que lo separa de un guion es que el auditor no la tenga en la lista blanca.
        """
        sin_explicar = sorted(_dependencias_de_la_imagen() - _del_ecosistema() - DEL_SERVICIO)

        assert not sin_explicar, (
            f"la imagen del sandbox instala {sin_explicar} y nadie dice para qué. O es del "
            f"ecosistema autorizado —y va a la lista blanca del auditor— o es del servicio, y "
            f"entonces va a DEL_SERVICIO **y no** a la lista blanca."
        )

    def test_lo_que_solo_sirve_al_servicio_no_se_puede_importar_desde_un_guion(self):
        permitidos = _lista_de_la_api()

        coladas = sorted(DEL_SERVICIO & permitidos)

        assert not coladas, (
            f"{coladas} son el microservicio, no el ecosistema: un guion de usuario que pueda "
            f"importarlos puede levantar un servidor dentro del sandbox."
        )


class TestLasDosCopiasDelAuditor:
    """El contrato de `docs/SANDBOX_SECURITY.md`: el sandbox es **más** estricto, nunca menos."""

    def test_el_sandbox_no_permite_nada_que_la_api_no_permita(self):
        de_mas = sorted(_lista_del_sandbox() - _lista_de_la_api())

        assert not de_mas, (
            f"la copia defensiva del sandbox permite {de_mas}, que la API no permite. La "
            f"duplicación sólo es segura en un sentido: si divergen, el sandbox es el estricto."
        )

    @pytest.mark.parametrize("modulo", sorted(DISTRIBUCION_DE()))
    def test_y_hoy_permiten_exactamente_lo_mismo(self, modulo):
        """Ser más estricto está permitido; serlo **por olvido** es lo que se quiere cazar.

        Se comprueba módulo a módulo para que el fallo diga cuál falta, y no «los conjuntos no
        son iguales». El día que se decida restringir el sandbox de verdad, este test se ajusta
        con el motivo escrito — que es precisamente lo que no pasó cuando divergieron.
        """
        assert (modulo in _lista_de_la_api()) == (modulo in _lista_del_sandbox())
