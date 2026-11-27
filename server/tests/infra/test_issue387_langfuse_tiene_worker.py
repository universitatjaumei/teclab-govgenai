"""#387 — Langfuse 3 son dos contenedores, y los compose sólo levantaban uno.

La web (`langfuse/langfuse`) recibe las trazas, las deja en S3 y encola un trabajo en Redis; el
*worker* (`langfuse/langfuse-worker`) es quien las lleva a ClickHouse. Sin él, Langfuse arranca,
migra y responde a `/api/public/health` —lo que comprobaba #297— y no muestra ni una traza.

Medido el 2026-11-27 con un compose aislado: sin *worker*, 0 trazas a los 90 s y el trabajo
esperando en `otel-ingestion-queue`; al arrancarlo, la encolada aparece y las nuevas llegan en
menos de un minuto.

Los guardarraíles de abajo vigilan también que web y *worker* no diverjan: una versión distinta
o una variable que sólo tenga uno de los dos es exactamente cómo se rompe esto en silencio.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
COMPOSES = ("docker-compose.yml", "docker-compose.prod.yml")

# Lo que el worker necesita para sacar el trabajo de la cola y escribirlo en ClickHouse.
INGESTA = (
    "DATABASE_URL",
    "CLICKHOUSE_URL",
    "CLICKHOUSE_USER",
    "CLICKHOUSE_PASSWORD",
    "REDIS_HOST",
    "REDIS_PORT",
    "LANGFUSE_S3_EVENT_UPLOAD_BUCKET",
    "LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT",
    "SALT",
    "ENCRYPTION_KEY",
)


def _servicios(compose: str) -> dict:
    return yaml.safe_load((RAIZ / compose).read_text(encoding="utf-8"))["services"]


def _imagen_y_etiqueta(servicio: dict) -> tuple[str, str]:
    imagen, _, etiqueta = servicio["image"].partition(":")
    return imagen, etiqueta


@pytest.mark.parametrize("compose", COMPOSES)
def test_should_run_the_worker_next_to_the_web(compose):
    servicios = _servicios(compose)
    assert "langfuse-worker" in servicios, (
        f"{compose}: sin `langfuse-worker`, Langfuse acepta las trazas y no procesa ninguna"
    )
    assert _imagen_y_etiqueta(servicios["langfuse-worker"])[0] == "langfuse/langfuse-worker"


@pytest.mark.parametrize("compose", COMPOSES)
def test_should_pin_web_and_worker_to_the_same_version(compose):
    """Dependabot sube cada imagen por su cuenta: una mayor llega como dos PRs, y aplicar una sola
    deja la web y el worker hablando versiones distintas de la misma cola."""
    servicios = _servicios(compose)
    web = _imagen_y_etiqueta(servicios["langfuse"])[1]
    worker = _imagen_y_etiqueta(servicios["langfuse-worker"])[1]
    assert web, f"{compose}: la web de Langfuse no fija versión"
    assert web == worker, f"{compose}: web {web} y worker {worker}"


@pytest.mark.parametrize("compose", COMPOSES)
def test_should_give_the_worker_what_ingestion_needs(compose):
    entorno = _servicios(compose)["langfuse-worker"]["environment"]
    faltan = [v for v in INGESTA if v not in entorno]
    assert not faltan, f"{compose}: al worker le faltan {faltan}"


@pytest.mark.parametrize("compose", COMPOSES)
def test_should_share_every_variable_with_the_web(compose):
    """Lo que tienen los dos, igual: un `SALT` o una `ENCRYPTION_KEY` distinta descifra mal."""
    servicios = _servicios(compose)
    web = servicios["langfuse"]["environment"]
    worker = servicios["langfuse-worker"]["environment"]
    distintas = sorted(k for k in worker if web.get(k) != worker[k])
    assert not distintas, f"{compose}: el worker y la web difieren en {distintas}"


@pytest.mark.parametrize("compose", COMPOSES)
def test_should_wait_for_what_the_worker_reads(compose):
    dependencias = set(_servicios(compose)["langfuse-worker"]["depends_on"])
    assert dependencias >= {"postgres", "clickhouse", "redis", "s3"}


def test_should_be_in_the_observability_profile():
    """En el autoinstalable, con el resto de la observabilidad (#297): o entera, o nada."""
    assert _servicios("docker-compose.prod.yml")["langfuse-worker"].get("profiles") == [
        "observabilidad"
    ]


def test_should_have_a_memory_ceiling_in_the_self_installable_compose():
    """Como sus vecinos del perfil. 445 MiB medidos en reposo tras procesar trazas."""
    techo = _servicios("docker-compose.prod.yml")["langfuse-worker"]["deploy"]["resources"]
    assert techo["limits"]["memory"]
