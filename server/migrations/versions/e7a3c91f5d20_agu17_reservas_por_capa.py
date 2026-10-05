"""#228 — plazas reservadas por capa en la selección de documentos de un agente.

Las versiones que hay quedan sin reservas (`[]`): seleccionan como hasta ahora.

Revision ID: e7a3c91f5d20
Revises: d00bcc89c296
Create Date: 2026-10-05 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e7a3c91f5d20'
down_revision: Union[str, None] = 'd00bcc89c296'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hub_agente_unidad_versiones', sa.Column('reservas', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))


def downgrade() -> None:
    op.drop_column('hub_agente_unidad_versiones', 'reservas')
