"""#343 — la base no admite dos modelos por defecto en el mismo nivel, propósito y organización.

`NULLS NOT DISTINCT` (Postgres 15+) porque la fila de plataforma lleva la organización a nulo, y
para un índice único corriente dos nulos son distintos: el caso de producción pasaría.

Revision ID: e9b3c7d15a42
Revises: d4f8a2c61e07
Create Date: 2026-10-30
"""
from alembic import op

revision = "e9b3c7d15a42"
down_revision = "d4f8a2c61e07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_config_un_por_defecto "
        "ON hub_llm_configs (tier, purpose, organizacion_id) NULLS NOT DISTINCT "
        "WHERE is_default"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_llm_config_un_por_defecto")
