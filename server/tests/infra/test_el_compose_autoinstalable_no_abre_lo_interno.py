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
EXIGIDOS_AL_ARRANCAR = {"CLICKHOUSE_PASSWORD": "clickhouse"}


def test_ningun_secreto_arranca_vacio() -> None:
    texto = PROD.read_text(encoding="utf-8")
    sueltos = sorted({
        # `$${X}` no cuenta: es el shell del contenedor quien lo resuelve, con su propio entorno.
        nombre for nombre in re.findall(r"(?<!\$)\$\{(\w+)\}", texto)
        if SECRETO.search(nombre) and nombre != "GOOGLE_API_KEY" and nombre not in EXIGIDOS_AL_ARRANCAR
    })
    assert not sueltos, f"secretos sin `:?` en el compose autoinstalable: {sueltos}"


@pytest.mark.parametrize(("variable", "servicio"), sorted(EXIGIDOS_AL_ARRANCAR.items()))
def test_los_secretos_de_un_perfil_los_exige_su_servicio(prod, variable, servicio) -> None:
    guarda = " ".join(prod["services"][servicio].get("entrypoint") or [])
    assert f'test -n "$${{{variable}}}"' in guarda, f"{servicio} arrancaría con {variable} vacío"
    assert "exit 1" in guarda


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
