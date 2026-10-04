"""#217 — la revisión de la calidad de un agente: veredicto y nota sobre cada conversación.

Los mismos tres veredictos que la revisión de los chatbots (`good`, `bad`, `mixed`). El CHECK va a
mano porque Alembic no lo detecta. Lo que ya hay queda sin revisar.

Revision ID: d00bcc89c296
Revises: 9bef8ebea902
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd00bcc89c296'
down_revision: Union[str, None] = '9bef8ebea902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hub_agente_consultas', sa.Column('veredicto', sa.String(length=10), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('nota_revision', sa.Text(), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('revisada_por', sa.String(length=255), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('revisada_en', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_agente_consulta_veredicto",
        "hub_agente_consultas",
        "veredicto IS NULL OR veredicto IN ('good', 'bad', 'mixed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agente_consulta_veredicto", "hub_agente_consultas", type_="check")
    op.drop_column('hub_agente_consultas', 'revisada_en')
    op.drop_column('hub_agente_consultas', 'revisada_por')
    op.drop_column('hub_agente_consultas', 'nota_revision')
    op.drop_column('hub_agente_consultas', 'veredicto')
