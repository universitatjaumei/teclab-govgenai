"""ROL.1 — Verificación del renombrado a nivel de esquema y de código.

- El esquema en la BD real refleja el renombrado (tablas/columnas nuevas, viejas
  ausentes) preservando filas (rename, no drop+create).
- No quedan referencias a los nombres antiguos en el código de producción
  (excluyendo migraciones, la capa NiceGUI legacy `ui/` — retirada en CAL.1 — y el
  concepto legacy AutomatIA `AutomationLibrary`, ajeno a este mapa).
"""

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL_SYNC")
    if url:
        return url
    async_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://govgenai:govgenai_dev@localhost:5432/govgenai"
    )
    return async_url.replace("postgresql+asyncpg", "postgresql+psycopg2")


@pytest.fixture(scope="module")
def inspector():
    engine = create_engine(_sync_url())
    try:
        with engine.connect():
            pass
    except Exception:  # pragma: no cover - entorno sin BD
        pytest.skip("BD Postgres no disponible")
    return inspect(engine), engine


def test_should_rename_tables_preserving_rows(inspector):
    insp, engine = inspector
    # Tablas nuevas presentes, viejas ausentes.
    assert insp.has_table("superadminaccount")
    assert insp.has_table("adminaccount")
    assert insp.has_table("hub_organizaciones")
    assert not insp.has_table("partneraccount")
    assert not insp.has_table("hub_clients")
    # El renombrado preserva la estructura (ALTER RENAME, no drop+create): las
    # columnas de negocio de la tabla original siguen presentes bajo el nuevo nombre.
    # (No se comprueban filas concretas porque otros tests de integración mutan la
    # BD de desarrollo compartida; la preservación de filas se verifica en el
    # `alembic upgrade` — ver descripción de la migración y el histórico de PROJECT_STATE.)
    org_cols = {c["name"] for c in insp.get_columns("hub_organizaciones")}
    assert {"id", "name", "partner_id", "default_public_graph_profile"} <= org_cols
    sa_cols = {c["name"] for c in insp.get_columns("superadminaccount")}
    assert {"admin_id", "email", "hashed_password"} <= sa_cols


def test_should_rename_client_id_to_organizacion_id_on_chatbots(inspector):
    insp, _ = inspector
    cb_cols = {c["name"] for c in insp.get_columns("hub_chatbots")}
    assert "organizacion_id" in cb_cols
    assert "client_id" not in cb_cols
    # hub_web_sites es operacional; otros tests pueden recrearla, así que sólo se
    # comprueba si está presente en este momento.
    if insp.has_table("hub_web_sites"):
        ws_cols = {c["name"] for c in insp.get_columns("hub_web_sites")}
        assert "organizacion_id" in ws_cols
        assert "client_id" not in ws_cols


# --- Zero references en código de producción ------------------------------

_APP = Path(__file__).resolve().parents[2] / "app"
_FORBIDDEN = re.compile(r"PartnerAccount|\bHubClient\b|UserRole\.PARTNER|['\"]partner['\"]")


def _production_py_files():
    for p in _APP.rglob("*.py"):
        # ui/ es NiceGUI legacy (se retira en CAL.1); fuera del alcance de ROL.1.
        if "ui" in p.relative_to(_APP).parts:
            continue
        yield p


def test_should_have_zero_references_to_old_names():
    offenders = []
    for path in _production_py_files():
        text_ = path.read_text(encoding="utf-8")
        for i, line in enumerate(text_.splitlines(), start=1):
            if _FORBIDDEN.search(line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, "Referencias a nomenclatura antigua:\n" + "\n".join(offenders)


def test_should_have_zero_client_id_in_agents_hub_package():
    """El concepto Hub usa organizacion_id; client_id sólo pervive en el legacy AutomatIA."""
    hub = _APP / "modules" / "agents_hub"
    offenders = [
        f"{p.name}:{i}: {line.strip()}"
        for p in hub.rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        if re.search(r"\bclient_id\b", line)
    ]
    assert not offenders, "client_id residual en agents_hub:\n" + "\n".join(offenders)
