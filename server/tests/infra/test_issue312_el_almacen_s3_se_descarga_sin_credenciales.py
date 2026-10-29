"""#312 — el almacén S3 de los compose es SeaweedFS, que se descarga sin credenciales.

Las dos imágenes de MinIO dejaron de servirse sin credenciales: quay.io responde 401 a las dos, y
`minio/minio` en Docker Hub no tiene etiquetas (medido el 2026-10-27 y otra vez el 2026-10-29).
El compose autoinstalable no arrancaba en una máquina sin caché, y el de desarrollo tampoco.
Decisión del 2026-10-29: **SeaweedFS** (Apache 2.0), en un solo proceso (`weed mini`), que crea
sus buckets al arrancar y toma las credenciales de `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`.

Probado en contenedor ese día: con la clave buena lista y escribe, con otra responde
`InvalidAccessKeyId`, y sin firmar, 403. **Lo que SeaweedFS trae abierto** se cierra aquí:

- el panel de administración, WebDAV y el catálogo Iceberg, que no se usan, van apagados;
- el filer y el volumen exigen una firma JWT (`security.toml`): sin ella, 401 al leer y al escribir;
- la telemetría, que viene encendida por omisión hacia `telemetry.seaweedfs.com`, se apaga.

**Lo que queda abierto, a sabiendas**: la API del maestro no lleva autenticación. Su `[guard]`
corta también el tráfico interno del propio proceso (`not authorized: @`, probado con `mini` y con
`server`). Sólo la alcanzan los servicios de la red `default`; el sandbox, que ejecuta código
ajeno, está en `sandbox-net` y no la ve.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
PROD = RAIZ / "docker-compose.prod.yml"
DEV = RAIZ / "docker-compose.yml"
COMPOSES = pytest.mark.parametrize("fichero", [PROD, DEV], ids=["prod", "dev"])
BUCKETS = ("langfuse-events", "langfuse-media")


def _servicios(fichero: Path) -> dict:
    return yaml.safe_load(fichero.read_text(encoding="utf-8"))["services"]


def _arranque(servicio: dict) -> str:
    partes = []
    for clave in ("entrypoint", "command"):
        valor = servicio.get(clave) or []
        partes.append(valor if isinstance(valor, str) else " ".join(valor))
    return " ".join(partes)


@COMPOSES
def test_el_almacen_es_seaweedfs_con_version_fija(fichero):
    imagen = _servicios(fichero)["s3"]["image"]
    assert imagen.startswith("chrislusf/seaweedfs:"), imagen
    assert imagen.split(":")[1][0].isdigit(), f"{imagen}: sin versión numérica"


@COMPOSES
def test_ningun_compose_menciona_minio(fichero):
    """Ni el servicio, ni su `init`, ni sus variables: una `MINIO_ROOT_USER` que configura otra
    cosa es un rótulo que miente. Los comentarios sí pueden contar por qué se fue."""
    configuracion = "\n".join(
        linea for linea in fichero.read_text(encoding="utf-8").lower().splitlines()
        if not linea.strip().startswith("#")
    )
    assert "minio" not in configuracion.replace("dominio", "")


@COMPOSES
def test_lo_que_no_se_usa_va_apagado(fichero):
    arranque = _arranque(_servicios(fichero)["s3"])
    for bandera in ("-admin.ui=false", "-webdav=false", "-s3.port.iceberg=0", "-master.telemetry=false"):
        assert bandera in arranque, f"falta {bandera}: SeaweedFS lo trae encendido por omisión"


@COMPOSES
def test_el_filer_y_el_volumen_exigen_firma(fichero):
    arranque = _arranque(_servicios(fichero)["s3"])
    for seccion in ("[jwt.signing]", "[jwt.signing.read]", "[jwt.filer_signing]", "[jwt.filer_signing.read]"):
        assert seccion in arranque, f"sin {seccion}, el filer o el volumen responden sin firma"
    assert "/etc/seaweedfs/security.toml" in arranque


@COMPOSES
def test_crea_los_buckets_de_langfuse_al_arrancar(fichero):
    arranque = _arranque(_servicios(fichero)["s3"])
    assert f"-bucket={','.join(BUCKETS)}" in arranque


@COMPOSES
def test_langfuse_escribe_en_el_almacen_con_sus_credenciales(fichero):
    servicios = _servicios(fichero)
    entorno = servicios["langfuse"]["environment"]
    for uso in ("EVENT", "MEDIA"):
        assert entorno[f"LANGFUSE_S3_{uso}_UPLOAD_ENDPOINT"] == "http://s3:9000"
        assert "S3_ACCESS_KEY" in entorno[f"LANGFUSE_S3_{uso}_UPLOAD_ACCESS_KEY_ID"]
        assert "S3_SECRET_KEY" in entorno[f"LANGFUSE_S3_{uso}_UPLOAD_SECRET_ACCESS_KEY"]
    assert servicios["langfuse"]["depends_on"]["s3"] == {"condition": "service_healthy"}


def test_el_generador_de_env_da_las_credenciales_del_almacen():
    texto = (RAIZ / "scripts" / "generate_env.sh").read_text(encoding="utf-8")
    assert 'S3_SECRET_KEY="$(openssl rand -hex' in texto
    assert "S3_ACCESS_KEY=" in texto
    assert "MINIO" not in texto
