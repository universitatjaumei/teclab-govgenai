"""#297 — en el compose autoinstalable, Langfuse se levanta con lo que necesita, o no se levanta.

Langfuse 3 necesita ClickHouse, Redis y un almacenamiento de objetos, y el compose que propone
`docs/INSTALACION.md` sólo le daba Postgres: no arrancaba, y nada lo decía porque la aplicación
no depende de él. Ahora va en el perfil `observabilidad` con sus tres dependencias. Se levantó
en limpio el 2026-10-27 en un proyecto aislado: aplica sus migraciones de ClickHouse y arranca.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
PERFIL = "observabilidad"


@pytest.fixture(scope="module")
def servicios() -> dict:
    return yaml.safe_load((RAIZ / "docker-compose.prod.yml").read_text(encoding="utf-8"))["services"]


def test_should_bring_langfuse_with_what_it_needs(servicios):
    langfuse = servicios["langfuse"]
    assert set(langfuse["depends_on"]) >= {"postgres", "clickhouse", "redis", "minio-init"}
    entorno = langfuse["environment"]
    for variable in ("CLICKHOUSE_URL", "CLICKHOUSE_MIGRATION_URL", "REDIS_HOST",
                     "LANGFUSE_S3_EVENT_UPLOAD_BUCKET", "LANGFUSE_S3_MEDIA_UPLOAD_BUCKET"):
        assert variable in entorno, f"Langfuse 3 no arranca sin {variable}"


@pytest.mark.parametrize("nombre", ["langfuse", "clickhouse", "redis", "minio-init"])
def test_should_be_optional_and_together(servicios, nombre):
    """En el perfil, los cuatro: quien no quiere observabilidad no carga dos gigas de ClickHouse,
    y quien la quiere no la levanta a medias."""
    assert servicios[nombre].get("profiles") == [PERFIL]


def test_should_not_put_the_application_behind_the_profile(servicios):
    """La aplicación no depende de Langfuse: si dependiera, el perfil dejaría de ser opcional."""
    assert "langfuse" not in servicios["app"].get("depends_on", {})
