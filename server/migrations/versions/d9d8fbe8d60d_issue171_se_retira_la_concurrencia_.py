"""Issue #171 — se retiran las dos columnas de concurrencia optimista que nadie leía.

Eran el lado de base de datos de la cadena 1C.1 (autoguardado), que estaba entera y sin
cablear y se retira en este mismo commit: `hub_workspaces.version` la incrementaba
`PATCH /state` y `hub_workspace_blocks.version` era el `expected_block_version` de su
cuerpo. Sin ese endpoint no las escribe ni las lee nadie, y no salen en ningún DTO.

Se borran en vez de dejarlas: una columna llamada `version` en una tabla afirma que hay
control de concurrencia, y no lo hay. El contenido de un bloque se escribe por
`PATCH /blocks/{id}/edit`, que es un camino distinto y no las usa. Son dos contadores a 1;
no se pierde ningún dato que alguien pueda echar de menos.

Revision ID: d9d8fbe8d60d
Revises: a1c2v3l4m5n6
Create Date: 2026-09-27 18:15:15.152870

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9d8fbe8d60d'
down_revision: Union[str, None] = 'a1c2v3l4m5n6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('hub_workspace_blocks', 'version')
    op.drop_column('hub_workspaces', 'version')


def downgrade() -> None:
    """Las devuelve a 1, que es lo que valían: nadie las incrementó nunca."""
    op.add_column('hub_workspaces', sa.Column('version', sa.INTEGER(), server_default=sa.text('1'), autoincrement=False, nullable=False))
    op.add_column('hub_workspace_blocks', sa.Column('version', sa.INTEGER(), server_default=sa.text('1'), autoincrement=False, nullable=False))
