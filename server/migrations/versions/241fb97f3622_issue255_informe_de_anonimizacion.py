"""Informe de anonimización en las propuestas de script (#255).

Qué se sustituyó, qué se mantuvo y cuántos valores originales siguen en el resultado, **sin un solo
valor**: es lo que permite comprobar que la anonimización de los datos de prueba funcionó, ahora que
el mapa ficticio→real ya no se guarda (#251). Nula en las propuestas anteriores, que se anonimizaron
sin informe.

Revision ID: 241fb97f3622
Revises: 275ba67cc98a
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "241fb97f3622"
down_revision = "275ba67cc98a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hub_script_proposals",
        sa.Column("anonymization_report_json", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hub_script_proposals", "anonymization_report_json")
