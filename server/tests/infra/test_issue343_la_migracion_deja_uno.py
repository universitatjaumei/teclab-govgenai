"""#343 — la migración deja un solo modelo por defecto por grupo y después lo exige.

Producción llegó al 30-10 con tres modelos de chat por defecto en el nivel 1 de plataforma. Allí ya
se arregló a mano, pero cualquier otra instalación puede tener el mismo estado, y el índice único
no se crearía sobre él: la migración de datos tiene que ir antes y dejar uno. Se queda **el que
usan más chatbots**, que es lo más parecido a «el que alguien eligió».
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2

_SERVER_ROOT = Path(__file__).parent.parent.parent

#: La última revisión antes de #343.
_ANTES = "c3e7a1f94b20"


def _alembic(base: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_SERVER_ROOT,
        env={**os.environ, "DATABASE_URL_SYNC": base},
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


def _conexion(base: str):
    conn = psycopg2.connect(base.replace("postgresql+psycopg2", "postgresql"))
    conn.autocommit = True
    return conn


def _sembrar_tres_por_defecto(base: str) -> dict[str, str]:
    """Tres de chat por defecto en el nivel 1 de plataforma; un chatbot usa el segundo."""
    ids = {nombre: str(uuid.uuid4()) for nombre in ("viejo", "usado", "local")}
    org = str(uuid.uuid4())
    conn = _conexion(base)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO hub_providers (id, name, provider_type) VALUES ('google', 'Google', 'google_genai') ON CONFLICT DO NOTHING"
        )
        for nombre, id_ in ids.items():
            cur.execute(
                "INSERT INTO hub_llm_configs (id, provider, model_name, temperature, top_p, "
                "max_tokens, tier, label, is_default, purpose) "
                "VALUES (%s, 'google', %s, 0.1, 1.0, 1000, 1, '', true, 'chat')",
                (id_, nombre),
            )
        # Y uno de embeddings por defecto en el mismo nivel: es otro grupo y no se toca.
        cur.execute(
            "INSERT INTO hub_llm_configs (id, provider, model_name, temperature, top_p, "
            "max_tokens, tier, label, is_default, purpose) "
            "VALUES (%s, 'google', 'emb', 0.1, 1.0, 1000, 1, '', true, 'embedding')",
            (str(uuid.uuid4()),),
        )
        cur.execute(
            "INSERT INTO hub_organizaciones (id, name, partner_id, is_active) VALUES (%s, 'Org', 'p', true)",
            (org,),
        )
        cur.execute(
            "INSERT INTO hub_chatbots (id, organizacion_id, llm_config_id, name, system_prompt) "
            "VALUES (%s, %s, %s, 'Bot', 'x')",
            (str(uuid.uuid4()), org, ids["usado"]),
        )
    conn.close()
    return ids


def _por_defecto(base: str) -> list[tuple[str, str]]:
    conn = _conexion(base)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT purpose, model_name FROM hub_llm_configs WHERE is_default ORDER BY purpose"
        )
        filas = cur.fetchall()
    conn.close()
    return filas


def test_deja_el_mas_usado_y_despues_no_admite_otro(fresh_database: str) -> None:
    r = _alembic(fresh_database, "upgrade", _ANTES)
    assert r.returncode == 0, r.stderr
    _sembrar_tres_por_defecto(fresh_database)

    r = _alembic(fresh_database, "upgrade", "head")
    assert r.returncode == 0, r.stderr

    assert _por_defecto(fresh_database) == [("chat", "usado"), ("embedding", "emb")]

    conn = _conexion(fresh_database)
    with conn.cursor() as cur:
        try:
            cur.execute("UPDATE hub_llm_configs SET is_default = true WHERE model_name = 'viejo'")
        except psycopg2.errors.UniqueViolation:
            pass
        else:  # pragma: no cover - es el fallo que se vigila
            raise AssertionError("la base admitió dos modelos por defecto en el mismo grupo")
    conn.close()


def test_baja_y_vuelve_a_subir(fresh_database: str) -> None:
    r = _alembic(fresh_database, "upgrade", "head")
    assert r.returncode == 0, r.stderr
    r = _alembic(fresh_database, "downgrade", _ANTES)
    assert r.returncode == 0, r.stderr
    r = _alembic(fresh_database, "upgrade", "head")
    assert r.returncode == 0, r.stderr
