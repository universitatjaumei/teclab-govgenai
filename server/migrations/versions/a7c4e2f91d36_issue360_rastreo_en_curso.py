"""#360 — el sitio dice si tiene un rastreo en marcha y desde cuándo.

**Nullable** las dos: nulo es «no hay ninguno», que es lo que vale para todos los sitios al aplicar
la migración. Sin clave ajena en la sección: es una nota sobre la pasada en curso y tiene que
sobrevivir a que la sección se borre a mitad.

Revision ID: a7c4e2f91d36
Revises: f2a6d9e83b51
Create Date: 2026-11-01
"""
from alembic import op

revision = "a7c4e2f91d36"
down_revision = "f2a6d9e83b51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hub_web_sites ADD COLUMN IF NOT EXISTS rastreo_en_curso_desde "
        "TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE hub_web_sites ADD COLUMN IF NOT EXISTS rastreo_en_curso_seccion_id UUID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE hub_web_sites DROP COLUMN IF EXISTS rastreo_en_curso_seccion_id")
    op.execute("ALTER TABLE hub_web_sites DROP COLUMN IF EXISTS rastreo_en_curso_desde")
