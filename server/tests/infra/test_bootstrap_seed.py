"""Tests 11.3 — sembrado de primera instalación (server/app/scripts/bootstrap.py).

El criterio de aceptación del prompt es la **idempotencia**: ejecutarlo dos veces
no debe duplicar datos. Eso solo se comprueba contra una base de datos real, así
que estos tests crean una BD desechable, aplican las migraciones y siembran.

Requiere Postgres accesible (mismas credenciales que DATABASE_URL_SYNC); si no lo
está, se saltan.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import pytest

_SERVER_ROOT = Path(__file__).parent.parent.parent

SUPERADMIN_EMAIL = "superadmin@ejemplo.test"
SUPERADMIN_PASSWORD = "clave-de-prueba-larga"


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL_SYNC")
    if url:
        return url
    async_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://govgenai:govgenai_dev@localhost:5432/govgenai"
    )
    return async_url.replace("postgresql+asyncpg", "postgresql+psycopg2")


@pytest.fixture
def seeded_database():
    """BD desechable con las migraciones aplicadas. Devuelve (sync_url, async_url)."""
    sync_url = _sync_url()
    parts = urlsplit(sync_url.replace("postgresql+psycopg2", "postgresql"))
    admin_dsn = urlunsplit(parts._replace(path="/postgres"))

    try:
        admin_conn = psycopg2.connect(admin_dsn)
    except Exception:  # pragma: no cover - entorno sin BD
        pytest.skip("BD Postgres no disponible")

    admin_conn.autocommit = True
    db_name = f"test_bootstrap_{uuid.uuid4().hex[:12]}"
    with admin_conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')

    fresh_sync = urlunsplit(urlsplit(sync_url)._replace(path=f"/{db_name}"))
    plain = fresh_sync.replace("postgresql+psycopg2", "postgresql")

    conn = psycopg2.connect(plain)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.close()

    migrate = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_SERVER_ROOT,
        env={**os.environ, "DATABASE_URL_SYNC": fresh_sync},
        capture_output=True, text=True, timeout=180,
        check=False,
    )
    assert migrate.returncode == 0, f"migraciones fallaron:\n{migrate.stderr}"

    fresh_async = plain.replace("postgresql://", "postgresql+asyncpg://")
    yield plain, fresh_async

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (db_name,),
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    admin_conn.close()


def _run_bootstrap(async_url: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, "-m", "server.app.scripts.bootstrap",
            "--superadmin-email", SUPERADMIN_EMAIL,
            *extra,
        ],
        cwd=_SERVER_ROOT.parent,
        # #270: la contraseña ya no va como argumento, y sin `stdin` cerrado el guion
        # se quedaría esperándola en la terminal.
        env={**os.environ, "DATABASE_URL": async_url, "SUPERADMIN_PASSWORD": SUPERADMIN_PASSWORD},
        stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=180,
        check=False,
    )


def _scalar(dsn: str, sql: str):
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Paso 3 — SuperAdmin
# ---------------------------------------------------------------------------

def test_should_create_superadmin_with_hashed_password(seeded_database) -> None:
    dsn, async_url = seeded_database
    result = _run_bootstrap(async_url)
    assert result.returncode == 0, result.stderr

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT email, hashed_password, is_active FROM superadminaccount WHERE email = %s",
            (SUPERADMIN_EMAIL,),
        )
        fila = cur.fetchone()

    assert fila is not None, "debe crear la cuenta de SuperAdmin"
    email, hashed, is_active = fila
    assert email == SUPERADMIN_EMAIL
    assert is_active is True
    assert hashed != SUPERADMIN_PASSWORD, "la contraseña no puede guardarse en claro"
    assert hashed.startswith("$2"), "debe ser un hash bcrypt"


def test_should_never_print_the_password(seeded_database) -> None:
    _, async_url = seeded_database
    result = _run_bootstrap(async_url)
    assert SUPERADMIN_PASSWORD not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# Paso 4 — chatbot de ejemplo con prompts en es/ca/en
# ---------------------------------------------------------------------------

def test_should_create_example_chatbot_with_its_dependencies(seeded_database) -> None:
    dsn, async_url = seeded_database
    assert _run_bootstrap(async_url).returncode == 0

    assert _scalar(dsn, "SELECT count(*) FROM hub_organizaciones") == 1
    assert _scalar(dsn, "SELECT count(*) FROM hub_llm_configs") >= 1
    assert _scalar(dsn, "SELECT count(*) FROM hub_chatbots") == 1


def test_should_create_welcome_prompts_in_three_languages(seeded_database) -> None:
    dsn, async_url = seeded_database
    assert _run_bootstrap(async_url).returncode == 0

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT language FROM hub_prompt_templates ORDER BY language")
        idiomas = [r[0] for r in cur.fetchall()]

    assert idiomas == ["ca", "en", "es"], f"esperados los tres idiomas, hay {idiomas}"


def test_prompts_must_not_be_empty_or_identical(seeded_database) -> None:
    """Tres filas con el mismo texto cumplirían el recuento sin cumplir el
    requisito: el prompt pide bienvenida *en los tres idiomas*."""
    dsn, async_url = seeded_database
    assert _run_bootstrap(async_url).returncode == 0

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT language, template_text FROM hub_prompt_templates")
        textos = dict(cur.fetchall())

    assert all(t.strip() for t in textos.values()), "ningún prompt puede estar vacío"
    assert len(set(textos.values())) == 3, "los tres idiomas deben tener texto distinto"


# ---------------------------------------------------------------------------
# Criterio de aceptación — idempotencia
# ---------------------------------------------------------------------------

def _inventario(dsn: str) -> dict[str, int]:
    return {
        tabla: _scalar(dsn, f"SELECT count(*) FROM {tabla}")
        for tabla in (
            "superadminaccount",
            "hub_organizaciones",
            "hub_llm_configs",
            "hub_chatbots",
            "hub_prompt_templates",
        )
    }


def test_should_be_idempotent_on_second_run(seeded_database) -> None:
    dsn, async_url = seeded_database

    assert _run_bootstrap(async_url).returncode == 0
    primera = _inventario(dsn)

    segunda_ejecucion = _run_bootstrap(async_url)
    assert segunda_ejecucion.returncode == 0, segunda_ejecucion.stderr
    segunda = _inventario(dsn)

    assert primera == segunda, (
        f"la segunda ejecución duplicó datos: {primera} -> {segunda}"
    )


def test_should_not_overwrite_an_existing_superadmin_password(seeded_database) -> None:
    """Reejecutar setup.sh tras un cambio de contraseña no debe revertirla."""
    dsn, async_url = seeded_database
    assert _run_bootstrap(async_url).returncode == 0

    hash_inicial = _scalar(
        dsn, f"SELECT hashed_password FROM superadminaccount WHERE email = '{SUPERADMIN_EMAIL}'"
    )
    assert _run_bootstrap(async_url).returncode == 0
    hash_final = _scalar(
        dsn, f"SELECT hashed_password FROM superadminaccount WHERE email = '{SUPERADMIN_EMAIL}'"
    )

    assert hash_inicial == hash_final, "no debe rehashear ni pisar la cuenta existente"


def test_should_report_what_it_created_and_what_it_skipped(seeded_database) -> None:
    _, async_url = seeded_database

    primera = _run_bootstrap(async_url)
    assert "creado" in primera.stdout.lower() or "creada" in primera.stdout.lower()

    segunda = _run_bootstrap(async_url)
    assert "ya exist" in segunda.stdout.lower(), \
        "la segunda pasada debe decir que no hizo nada, no fingir que creó"


# ---------------------------------------------------------------------------
# #343 — la semilla no se impone a un modelo por defecto que ya existe
# ---------------------------------------------------------------------------

def test_should_not_mark_its_model_as_default_when_there_is_one(seeded_database) -> None:
    """Así se juntaron tres modelos por defecto en producción: cada siembra marcaba el suyo. Con
    el índice único de #343, además, marcarlo haría fallar la instalación."""
    dsn, async_url = seeded_database
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO hub_providers (id, name, provider_type) "
            "VALUES ('google', 'Google', 'google_genai') ON CONFLICT DO NOTHING"
        )
        cur.execute(
            "INSERT INTO hub_llm_configs (id, provider, model_name, temperature, top_p, "
            "max_tokens, tier, label, is_default, purpose) "
            "VALUES (%s, 'google', 'gemini-2.5-flash', 0.1, 1.0, 1000, 1, '', true, 'chat')",
            (str(uuid.uuid4()),),
        )

    result = _run_bootstrap(async_url)

    assert result.returncode == 0, result.stderr
    assert _scalar(
        dsn,
        "SELECT string_agg(model_name, ',') FROM hub_llm_configs "
        "WHERE is_default AND purpose = 'chat' AND tier = 1",
    ) == "gemini-2.5-flash"
