"""#175 — el módulo `consulta_agentes`, de oficio: consultar los agentes es de cualquiera.

Decisión del usuario (2026-10-02): mientras no exista la extensión (#176), una persona consulta
un agente desde una pantalla propia y copia el prompt. Hace falta un módulo para que esa
pantalla esté en el menú, y **de oficio** para que lo tenga todo el mundo sin concesión, igual
que `utilidades`. La ruta lo exige, así que retirarlo apaga la consulta para todos.

Revision ID: d5f9b2c7e148
Revises: c4e8a1f6d935
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "d5f9b2c7e148"
down_revision = "c4e8a1f6d935"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO hub_platform_modules (code, label, vigente, de_oficio)"
            " VALUES ('consulta_agentes', 'Consulta de agentes', true, true)"
            " ON CONFLICT (code) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM hub_platform_modules WHERE code = 'consulta_agentes'")
    )
