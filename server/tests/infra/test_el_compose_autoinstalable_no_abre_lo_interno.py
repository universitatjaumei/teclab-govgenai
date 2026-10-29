"""#269 — el compose que `docs/INSTALACION.md` propone no deja abiertos los servicios internos.

Publicaba en todas las interfaces la API sin TLS (saltándose nginx), la consola de MinIO con las
credenciales del almacenamiento, Langfuse y Ollama. Sólo el panel necesita puerto; lo demás o no
se publica o se publica en `127.0.0.1`, para administrarlo desde la propia máquina.

Y tres cosas más de la misma familia —arrancar sin quejarse con una configuración que no es la
que se cree—: los secretos de Langfuse arrancaban vacíos, dos imágenes iban por etiqueta flotante
y sólo el sandbox tenía techo de memoria. El Postgres de desarrollo, con contraseña por omisión,
escuchaba en todas las interfaces.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
PROD = RAIZ / "docker-compose.prod.yml"
DEV = RAIZ / "docker-compose.yml"

#: Lo único que se publica hacia fuera: el panel, que es quien termina las peticiones.
PUBLICOS = {"frontend"}
#: Ollama no lleva techo a propósito: su memoria es la del modelo que elige quien instala.
SIN_TECHO = {"ollama"}
SECRETO = re.compile(r"PASSWORD|SECRET|SALT|ENCRYPTION|_KEY$|POSTGRES_(USER|DB)|ROOT_USER|ADMIN_EMAIL")


@pytest.fixture(scope="module")
def prod() -> dict:
    return yaml.safe_load(PROD.read_text(encoding="utf-8"))


def _puertos(servicio: dict) -> list[str]:
    return [str(p) for p in servicio.get("ports", [])]


def test_solo_el_panel_se_publica_hacia_fuera(prod) -> None:
    abiertos = [
        f"{nombre}: {puerto}"
        for nombre, servicio in prod["services"].items()
        if nombre not in PUBLICOS
        for puerto in _puertos(servicio)
        if not puerto.startswith("127.0.0.1:")
    ]
    assert not abiertos, "servicios internos publicados en todas las interfaces:\n" + "\n".join(abiertos)


def test_hay_un_panel_publicado(prod) -> None:
    """Sanidad: sin esto, el test de arriba pasaría con un compose que no publica nada."""
    assert _puertos(prod["services"]["frontend"])


#: Secretos de un perfil opcional. Compose interpola el fichero entero, perfiles inactivos
#: incluidos, así que con `:?` un `.env` sin ellos tumbaba también la aplicación (revisión de la
#: PR #313). No arrancan vacíos igualmente: los exige el entrypoint de su servicio, y el test de
#: abajo lo comprueba, así que la excepción deja de valer si alguien quita la guarda.
#:
#: Variable del `.env` → (servicio, nombre con que le llega al contenedor), que es el que mira la
#: guarda: los de Langfuse se renombran al entrar (#318).
EXIGIDOS_AL_ARRANCAR = {
    "CLICKHOUSE_PASSWORD": ("clickhouse", "CLICKHOUSE_PASSWORD"),
    "LANGFUSE_NEXTAUTH_SECRET": ("langfuse", "NEXTAUTH_SECRET"),
    "LANGFUSE_SALT": ("langfuse", "SALT"),
    "LANGFUSE_ENCRYPTION_KEY": ("langfuse", "ENCRYPTION_KEY"),
    "LANGFUSE_PUBLIC_KEY": ("langfuse", "LANGFUSE_INIT_PROJECT_PUBLIC_KEY"),
    "LANGFUSE_SECRET_KEY": ("langfuse", "LANGFUSE_INIT_PROJECT_SECRET_KEY"),
    "LANGFUSE_ADMIN_EMAIL": ("langfuse", "LANGFUSE_INIT_USER_EMAIL"),
    "LANGFUSE_ADMIN_PASSWORD": ("langfuse", "LANGFUSE_INIT_USER_PASSWORD"),
}


def test_ningun_secreto_arranca_vacio() -> None:
    texto = PROD.read_text(encoding="utf-8")
    sueltos = sorted({
        # `$${X}` no cuenta: es el shell del contenedor quien lo resuelve, con su propio entorno.
        nombre for nombre in re.findall(r"(?<!\$)\$\{(\w+)\}", texto)
        if SECRETO.search(nombre) and nombre != "GOOGLE_API_KEY" and nombre not in EXIGIDOS_AL_ARRANCAR
    })
    assert not sueltos, f"secretos sin `:?` en el compose autoinstalable: {sueltos}"


@pytest.mark.parametrize(("variable", "destino"), sorted(EXIGIDOS_AL_ARRANCAR.items()))
def test_los_secretos_de_un_perfil_los_exige_su_servicio(prod, variable, destino) -> None:
    servicio, en_el_contenedor = destino
    assert prod["services"][servicio]["environment"][en_el_contenedor] == f"${{{variable}}}", (
        f"{servicio} no recibe {variable} como {en_el_contenedor}: la guarda miraría otra cosa"
    )
    guarda = " ".join(prod["services"][servicio].get("entrypoint") or [])
    assert f'test -n "$${{{en_el_contenedor}}}"' in guarda, f"{servicio} arrancaría con {variable} vacío"
    assert "exit 1" in guarda


def _exigidos_con_interrogacion(servicio: dict) -> set[str]:
    return set(re.findall(r"\$\{(\w+):\?", yaml.safe_dump(servicio.get("environment") or {})))


def test_un_perfil_no_exige_nada_a_quien_no_lo_levanta(prod) -> None:
    """#318 — `:?` en una variable que sólo usa un servicio de perfil tumba el `up` de todos.

    Compose interpola el fichero entero, perfiles inactivos incluidos: un `.env` sin los secretos
    de Langfuse impedía arrancar la aplicación a quien no quiere observabilidad.
    """
    sin_perfil = set().union(*(
        _exigidos_con_interrogacion(s) for s in prod["services"].values() if not s.get("profiles")
    ))
    solo_de_perfil = sorted(
        f"{nombre}: {variable}"
        for nombre, servicio in prod["services"].items()
        if servicio.get("profiles")
        for variable in _exigidos_con_interrogacion(servicio) - sin_perfil
    )
    assert not solo_de_perfil, (
        "variables con `:?` que sólo usa un servicio de perfil; van sin modificador y con guarda "
        "en el entrypoint (EXIGIDOS_AL_ARRANCAR):\n" + "\n".join(solo_de_perfil)
    )


def test_la_guarda_de_langfuse_no_pierde_su_arranque(prod) -> None:
    """Un `entrypoint` en Compose también borra el `command` de la imagen: la guarda tiene que
    acabar cediendo al arranque original de Langfuse, el de `dumb-init` y su servidor."""
    guarda = " ".join(prod["services"]["langfuse"]["entrypoint"])
    assert "exec dumb-init -- ./web/entrypoint.sh node ./web/server.js" in guarda


@pytest.mark.parametrize("fichero", [PROD, DEV], ids=["prod", "dev"])
def test_cada_imagen_tiene_version_fija(fichero) -> None:
    datos = yaml.safe_load(fichero.read_text(encoding="utf-8"))
    flotantes = [
        f"{nombre}: {servicio['image']}"
        for nombre, servicio in datos["services"].items()
        # MinIO publica por fecha (`RELEASE.2025-09-07T…`), que también es una versión fija.
        if "image" in servicio
        and not re.search(r":[^:]*(\d+\.\d+|RELEASE\.\d{4}-)", servicio["image"])
    ]
    assert not flotantes, "imágenes por etiqueta flotante:\n" + "\n".join(flotantes)


def test_cada_servicio_tiene_techo_de_memoria(prod) -> None:
    sin_techo = [
        nombre for nombre, servicio in prod["services"].items()
        if nombre not in SIN_TECHO
        and not servicio.get("deploy", {}).get("resources", {}).get("limits", {}).get("memory")
    ]
    assert not sin_techo, f"servicios sin techo de memoria: {sin_techo}"


def test_el_postgres_de_desarrollo_solo_escucha_en_la_maquina() -> None:
    datos = yaml.safe_load(DEV.read_text(encoding="utf-8"))
    abiertos = [
        f"{nombre}: {puerto}"
        for nombre, servicio in datos["services"].items()
        for puerto in _puertos(servicio)
        if puerto.split(":")[-1].startswith("5432") and not puerto.startswith("127.0.0.1:")
    ]
    assert not abiertos, abiertos
