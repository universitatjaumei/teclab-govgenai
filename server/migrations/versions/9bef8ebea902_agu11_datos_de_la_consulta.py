"""#219 — los datos de la consulta: lo que declara el agente y lo que se indicó en cada consulta.

Los agentes que hay quedan sin datos (`[]`) y sin indicaciones: consultan como hasta ahora.

Revision ID: 9bef8ebea902
Revises: b35eff104dae
Create Date: 2026-10-04 08:48:01.087989

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9bef8ebea902'
down_revision: Union[str, None] = 'b35eff104dae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hub_agente_consultas', sa.Column('datos', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('hub_agente_unidad_versiones', sa.Column('datos_consulta', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('hub_agente_unidad_versiones', sa.Column('indicaciones', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('hub_agente_unidad_versiones', 'indicaciones')
    op.drop_column('hub_agente_unidad_versiones', 'datos_consulta')
    op.drop_column('hub_agente_consultas', 'datos')
