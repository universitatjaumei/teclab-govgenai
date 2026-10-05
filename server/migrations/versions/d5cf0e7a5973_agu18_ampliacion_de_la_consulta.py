"""#225 — «Buscar más documentos»: cada ampliación es una consulta ligada a la primera.

Las consultas que hay quedan sin madre (NULL): cada una es su propia conversación.

Revision ID: d5cf0e7a5973
Revises: e7a3c91f5d20
Create Date: 2026-10-05 18:12:57.687782

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5cf0e7a5973'
down_revision: Union[str, None] = 'e7a3c91f5d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK = 'hub_agente_consultas_consulta_madre_id_fkey'


def upgrade() -> None:
    op.add_column('hub_agente_consultas', sa.Column('consulta_madre_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_hub_agente_consultas_consulta_madre_id'), 'hub_agente_consultas', ['consulta_madre_id'], unique=False)
    op.create_foreign_key(FK, 'hub_agente_consultas', 'hub_agente_consultas', ['consulta_madre_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint(FK, 'hub_agente_consultas', type_='foreignkey')
    op.drop_index(op.f('ix_hub_agente_consultas_consulta_madre_id'), table_name='hub_agente_consultas')
    op.drop_column('hub_agente_consultas', 'consulta_madre_id')
