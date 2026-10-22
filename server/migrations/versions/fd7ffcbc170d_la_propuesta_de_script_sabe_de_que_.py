"""La propuesta de script sabe de qué organización es.

Acota quién ve y revisa una propuesta. Las que ya existen quedan a nulo y, con eso, sólo las
revisa un superadministrador: no se rellenan hacia atrás porque `proposer_user_id` es un uuid
derivado del sujeto y no lleva a una persona con organización.

Revision ID: fd7ffcbc170d
Revises: 241fb97f3622
Create Date: 2026-10-22 10:37:42.041102

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fd7ffcbc170d"
down_revision: Union[str, None] = "241fb97f3622"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hub_script_proposals", sa.Column("organizacion_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_hub_script_proposals_organizacion_id"),
        "hub_script_proposals",
        ["organizacion_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_hub_script_proposals_organizacion_id"), table_name="hub_script_proposals")
    op.drop_column("hub_script_proposals", "organizacion_id")
