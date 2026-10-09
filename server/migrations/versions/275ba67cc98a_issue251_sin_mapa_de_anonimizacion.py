"""Quita el mapa ficticio→real de las propuestas de script (#251).

`hub_script_proposals.test_data_anonymization_map` guardaba, al anonimizar los datos de prueba,
qué valor ficticio correspondía a qué valor real. No lo leía nadie —el reintento del
administrador trabaja sobre el sintético— y es la llave que deshace la anonimización. Al quitar
la columna se van los mapas ya guardados; en producción no había ninguna propuesta (contado el
2026-10-09).

El `downgrade` devuelve la columna vacía: los mapas no vuelven, y es lo que se pretende.

Revision ID: 275ba67cc98a
Revises: b250a1c3d5e7
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "275ba67cc98a"
down_revision = "b250a1c3d5e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("hub_script_proposals", "test_data_anonymization_map")


def downgrade() -> None:
    op.add_column(
        "hub_script_proposals",
        sa.Column("test_data_anonymization_map", postgresql.JSONB(), nullable=True),
    )
