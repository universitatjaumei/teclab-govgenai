"""Regresión 11.2 — `alembic upgrade head` debe completar sobre una BD vacía.

Reproduce exactamente lo que hace el servicio `migrate` de docker-compose.prod.yml
en una instalación nueva. Antes de este fix, la cadena fallaba en
d4e5f6a7b8c9_hub_ingestion_language (ALTER TABLE sobre `hub_ingestion_sources`,
una tabla que ninguna migración crea — ver planificacion/PROJECT_STATE.md 2026-07-15).

Requiere un servidor Postgres accesible (usa las mismas credenciales que
DATABASE_URL_SYNC) con permiso CREATEDB; si no está disponible, se salta.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg2

_SERVER_ROOT = Path(__file__).parent.parent.parent

# La fixture `fresh_database` vive en el conftest raíz (`tests/conftest.py`), junto a
# `db_url` y por el mismo motivo: la usa también `tests/modules/agents_hub/integration`
# (RAG.3), e importarla de módulo a módulo hace que el parámetro del test redefina el
# nombre importado.


def test_alembic_upgrade_head_succeeds_on_empty_database(fresh_database: str) -> None:
    env = {**os.environ, "DATABASE_URL_SYNC": fresh_database}

    # `python -m alembic` y no `alembic`: el ejecutable de consola solo está en
    # el PATH con el venv activado, y en Windows sin activar el test moría con
    # FileNotFoundError en lugar de comprobar las migraciones.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_SERVER_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, (
        "alembic upgrade head falló sobre una BD vacía (regresión 11.2):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _upgrade_head(fresh_database: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_SERVER_ROOT,
        env={**os.environ, "DATABASE_URL_SYNC": fresh_database},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _columns(fresh_database: str, table: str) -> set[str]:
    conn = psycopg2.connect(fresh_database.replace("postgresql+psycopg2", "postgresql"))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select column_name from information_schema.columns "
                "where table_name = %s",
                (table,),
            )
            return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def test_should_have_ingestion_job_columns_on_fresh_install(fresh_database: str) -> None:
    """ING.0.2 — el ORM declara HubIngestionJob.canonical_url y .original_filename
    (operational_models.py) y POST /hub/ingestion/upload las escribe
    (hub_ingestion_router.py), pero hasta ING.0.2 NINGUNA migración las creaba: en un
    despliegue limpio la subida de documentos fallaba con UndefinedColumn. Misma familia
    que el fallo de hub_ingestion_sources que arregló 11.2.
    """
    _upgrade_head(fresh_database)
    columnas = _columns(fresh_database, "hub_ingestion_jobs")

    assert "canonical_url" in columnas
    assert "original_filename" in columnas


def test_should_not_keep_dead_metadata_column_on_interactions(fresh_database: str) -> None:
    """SQLAlchemy reserva `metadata` en las clases declarativas, así que la columna que
    creaba a1b2c3d4e5f6 era inalcanzable desde el ORM (que usa interaction_metadata).
    Se retira en ING.0.2 por Caso B."""
    _upgrade_head(fresh_database)
    columnas = _columns(fresh_database, "hub_interactions")

    assert "metadata" not in columnas
    assert "interaction_metadata" in columnas


def test_should_have_document_metadata_columns_and_fk(fresh_database: str) -> None:
    """Las columnas de ING.0.2 y la FK de document_id que VIS.1 necesita para el JOIN."""
    _upgrade_head(fresh_database)
    columnas = _columns(fresh_database, "hub_documents")

    for esperada in (
        "content_class", "ambit_principal", "ambits_secundaris", "submateries",
        "submateries_internes", "nivell_acces", "us_assistents",
        "versio_idiomatica_de", "estat_vigencia", "vigencia_validada_el",
        "revisat_per", "revisat_el", "data_revisio_prevista", "id_publicacio",
        "last_seen_at", "doc_metadata",
    ):
        assert esperada in columnas, f"falta hub_documents.{esperada}"

    conn = psycopg2.connect(
        fresh_database.replace("postgresql+psycopg2", "postgresql")
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select confdeltype from pg_constraint "
                "where conrelid = 'hub_document_chunks'::regclass and contype = 'f' "
                "and conname like '%document_id%'"
            )
            fks = cur.fetchall()
            assert fks, "hub_document_chunks.document_id sigue sin FK"
            assert fks[0][0] == "c", "la FK de document_id debe ser ON DELETE CASCADE"

            cur.execute(
                "select indexdef from pg_indexes where tablename = 'hub_documents'"
            )
            defs = [r[0] for r in cur.fetchall()]
            assert any("gin" in d.lower() and "submateries" in d for d in defs), (
                "falta el indice GIN sobre submateries en instalacion limpia"
            )
    finally:
        conn.close()


def test_should_close_new_chatbots_by_default_on_fresh_install(fresh_database: str) -> None:
    """SEC.2.1 — la migración del modo de acceso es fail-closed, comprobado ejecutándola.

    Aquí sí se ejecuta `alembic upgrade head` de verdad, así que esto mide lo que le pasa a
    una instalación: un chatbot insertado sin declarar el modo queda en `authenticated`, y
    la tabla rechaza cualquier modo fuera del vocabulario. Un `server_default` en
    `'public_anon'` publicaría el corpus de cada organización sin que nadie lo decidiera.
    """
    import uuid as _uuid

    _upgrade_head(fresh_database)
    assert "access_mode" in _columns(fresh_database, "hub_chatbots")

    conn = psycopg2.connect(fresh_database.replace("postgresql+psycopg2", "postgresql"))
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "select column_default, is_nullable from information_schema.columns "
                "where table_name = 'hub_chatbots' and column_name = 'access_mode'"
            )
            defecto, admite_null = cur.fetchone()
            assert "authenticated" in defecto
            assert admite_null == "NO"

            organizacion, llm, chatbot = _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4()
            cur.execute(
                "insert into hub_organizaciones (id, name, partner_id) values (%s,%s,%s)",
                (str(organizacion), "Org", "p-1"),
            )
            cur.execute(
                "insert into hub_llm_configs (id, provider, model_name) values (%s,%s,%s)",
                (str(llm), "google", "gemini-2.5-flash"),
            )
            cur.execute(
                "insert into hub_chatbots (id, organizacion_id, llm_config_id, name, "
                "system_prompt) values (%s,%s,%s,%s,%s)",
                (str(chatbot), str(organizacion), str(llm), "Bot", "Eres útil."),
            )
            cur.execute(
                "select access_mode from hub_chatbots where id = %s", (str(chatbot),)
            )
            assert cur.fetchone()[0] == "authenticated"

            try:
                cur.execute(
                    "update hub_chatbots set access_mode = 'barra_libre' where id = %s",
                    (str(chatbot),),
                )
                raise AssertionError("la tabla aceptó un modo de acceso desconocido")
            except psycopg2.errors.CheckViolation:
                pass
    finally:
        conn.close()


def test_should_leave_sso_users_without_organizacion_on_fresh_install(
    fresh_database: str,
) -> None:
    """SEC.2.1 — la columna existe, admite NULL y nadie hereda una organización.

    La tabla se llama `hub_users` desde IDE.2; era `hub_sso_users` cuando se escribió
    este test, y el nombre viejo solo sobrevive en las migraciones que lo usaron.
    """
    _upgrade_head(fresh_database)

    assert "organizacion_id" in _columns(fresh_database, "hub_users")

    conn = psycopg2.connect(fresh_database.replace("postgresql+psycopg2", "postgresql"))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select is_nullable, column_default from information_schema.columns "
                "where table_name = 'hub_users' and column_name = 'organizacion_id'"
            )
            admite_null, defecto = cur.fetchone()
            assert admite_null == "YES"
            assert defecto is None, (
                "un default aquí daría organización de oficio a los usuarios SSO"
            )
    finally:
        conn.close()
