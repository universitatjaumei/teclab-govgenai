#!/usr/bin/env python3
"""Comprueba que cada imagen fija de los compose se descarga sin credenciales y arranca como creemos.

Lo ejecuta el job `imagen` de `ci.yml`, con los compose como argumentos. Una sola llamada por
imagen —`docker buildx imagetools inspect`, sin sesión iniciada y sin bajar las capas— responde a
las dos preguntas:

**1. ¿Se descarga sin credenciales? (#312)** MinIO dejó de servirse así dos veces, y las dos se vio
en la máquina de quien instalaba, porque en la de quien lo escribía la imagen estaba en caché. Sólo
cuenta como «no se descarga» lo que el registro **niega** (no autorizado, no existe). Un límite de
peticiones o un corte de red se reintenta y, si sigue, se dice como lo que es. Ninguna de las dos
cosas corta la comprobación: se informa de todas las imágenes al final (#327).

**2. ¿El arranque que copia la guarda sigue siendo el de la imagen? (#318, #327)** Un `entrypoint`
en Compose sustituye el de la imagen y **borra también su `command`**, así que las guardas de
Langfuse, ClickHouse y SeaweedFS acaban ejecutando a mano el arranque de su imagen. Dependabot sube
la etiqueta sin mirarlo. `ARRANQUES` guarda el arranque de cada imagen **tal como era cuando se
escribió su guarda**, y cualquier diferencia —una opción nueva, un `WorkingDir` movido— pone rojo:
quien la vea relee la guarda y actualiza la tabla. Un servicio que sustituya el `entrypoint` de una
imagen que no esté en la tabla también pone rojo.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from typing import NamedTuple


class Arranque(NamedTuple):
    entrypoint: list[str] | None
    cmd: list[str] | None
    workdir: str


#: El arranque de cada imagen cuyo `entrypoint` sustituye una guarda de los compose, leído con
#: `docker buildx imagetools inspect <imagen> --format '{{json .Image}}'` (linux/amd64).
ARRANQUES: dict[str, Arranque] = {
    # La guarda copia la rama sin `NEXT_PUBLIC_LANGFUSE_CLOUD_REGION` del `Cmd`.
    "langfuse/langfuse": Arranque(
        ["dumb-init", "--", "./web/entrypoint.sh"],
        [
            "/bin/sh",
            "-c",
            'if [ -n "$NEXT_PUBLIC_LANGFUSE_CLOUD_REGION" ]; then     node --import '
            "dd-trace/initialize.mjs ./web/server.js --keepAliveTimeout 110000;     else     "
            "node ./web/server.js --keepAliveTimeout 110000;     fi",
        ],
        "/app",
    ),
    "clickhouse/clickhouse-server": Arranque(["/entrypoint.sh"], None, "/"),
    # La guarda pasa su propio `mini …`: el `Cmd` se vigila porque dice cómo espera arrancar.
    "chrislusf/seaweedfs": Arranque(["/entrypoint.sh"], ["mini", "-dir=/data"], "/data"),
}

NIEGA = re.compile(r"unauthorized|denied|manifest unknown|no such manifest|not found", re.I)
INTENTOS = 3
ESPERA = 15


class Niega(Exception):
    """El registro dice que la imagen no se descarga sin credenciales, o que no existe."""


class NoResponde(Exception):
    """El registro no contesta: límite de peticiones o red. No es de credenciales."""


class ImagenIlegible(Exception):
    """El registro contesta, pero no con una configuración que se pueda comparar."""


def repositorio(imagen: str) -> str:
    """`langfuse/langfuse:3.225.11` → `langfuse/langfuse`."""
    nombre, _, etiqueta = imagen.rpartition(":")
    return nombre if nombre and "/" not in etiqueta else imagen


def imagenes_fijas(servicios: dict) -> list[str]:
    """Las imágenes por variable son nuestras y piden credenciales a propósito."""
    return sorted({s["image"] for s in servicios.values() if "image" in s and not s["image"].startswith("$")})


def sin_vigilar(servicios: dict) -> list[str]:
    return [
        f"{nombre} ({repositorio(s['image'])})"
        for nombre, s in servicios.items()
        if "entrypoint" in s and repositorio(s.get("image", "")) not in ARRANQUES
    ]


def configuracion(salida: str) -> Arranque:
    """Lee la salida de `--format '{{json .Image}}'`, que es un índice por plataforma o, si la
    etiqueta sólo publica una, la imagen directamente."""
    datos = json.loads(salida)
    if "config" not in datos:
        if "linux/amd64" not in datos:
            raise ImagenIlegible(f"no publica linux/amd64, sólo {sorted(datos)}")
        datos = datos["linux/amd64"]
    config = datos.get("config") or {}
    return Arranque(config.get("Entrypoint"), config.get("Cmd"), config.get("WorkingDir") or "/")


def diferencias(esperado: Arranque, real: Arranque) -> list[str]:
    return [
        f"{campo}: la guarda copia {getattr(esperado, atributo)!r} y la imagen trae {getattr(real, atributo)!r}"
        for campo, atributo in (("Entrypoint", "entrypoint"), ("Cmd", "cmd"), ("WorkingDir", "workdir"))
        if getattr(esperado, atributo) != getattr(real, atributo)
    ]


def inspecciona(imagen: str, ejecuta=subprocess.run) -> Arranque:
    orden = ["docker", "buildx", "imagetools", "inspect", imagen, "--format", "{{json .Image}}"]
    for intento in range(1, INTENTOS + 1):
        resultado = ejecuta(orden, capture_output=True, text=True, encoding="utf-8")
        if resultado.returncode == 0:
            return configuracion(resultado.stdout)
        error = resultado.stderr.strip()
        if NIEGA.search(error):
            raise Niega(error)
        if intento == INTENTOS:
            raise NoResponde(error)
        print(f"reintento {imagen}: {error}")
        time.sleep(ESPERA * intento)
    raise AssertionError("inalcanzable")


def comprueba(servicios: dict, ejecuta=subprocess.run) -> int:
    problemas = [f"sustituye el entrypoint de una imagen que no está en ARRANQUES: {s}" for s in sin_vigilar(servicios)]
    for imagen in imagenes_fijas(servicios):
        try:
            real = inspecciona(imagen, ejecuta)
        except Niega as error:
            problemas.append(f"{imagen} no se descarga sin credenciales: {error}")
            continue
        except NoResponde as error:
            problemas.append(f"el registro no responde para {imagen}, y no es de credenciales: {error}")
            continue
        except ImagenIlegible as error:
            problemas.append(f"{imagen}: {error}")
            continue
        esperado = ARRANQUES.get(repositorio(imagen))
        copia = [] if esperado is None else diferencias(esperado, real)
        problemas += [f"{imagen}, el arranque que copia la guarda ya no es el suyo. {d}" for d in copia]
        print(f"ok      {imagen}" if not copia else f"CAMBIA  {imagen}")
    for problema in problemas:
        print(f"::error::{problema}")
    return 1 if problemas else 0


def servicios_de(compose: str) -> dict:
    """Los servicios del compose, todos los perfiles incluidos y sin interpolar variables."""
    salida = subprocess.run(
        ["docker", "compose", "-f", compose, "--profile", "*", "config", "--no-interpolate", "--format", "json"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    return {f"{compose}:{nombre}": s for nombre, s in json.loads(salida)["services"].items()}


def main(argv: list[str] | None = None) -> int:
    for flujo in (sys.stdout, sys.stderr):  # la consola de Windows es cp1252
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("composes", nargs="+")
    args = parser.parse_args(argv)
    servicios: dict = {}
    for compose in args.composes:
        servicios |= servicios_de(compose)
    return comprueba(servicios)


if __name__ == "__main__":
    sys.exit(main())
