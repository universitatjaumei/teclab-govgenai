"""#218 — la lengua de la respuesta y el adjunto en tres niveles.

`espera_adjunto` (sí/no) pasa a `adjunto` (`no`, `opcional`, `obligatorio`): lo que esperaba
adjunto queda `obligatorio`, que es lo que era, y lo demás `no`. La lengua de la respuesta empieza
en `pregunta` para todos: es lo que hacía el asistente sin instrucción. Los CHECK van a mano porque
Alembic no los detecta.

Revision ID: b35eff104dae
Revises: 6866546b9c71
Create Date: 2026-10-04 07:46:50.229620

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b35eff104dae'
down_revision: Union[str, None] = '6866546b9c71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hub_agente_unidad_versiones', sa.Column('adjunto', sa.String(length=12), server_default='no', nullable=False))
    op.add_column('hub_agente_unidad_versiones', sa.Column('lengua_respuesta', sa.String(length=10), server_default='pregunta', nullable=False))
    op.execute(
        "UPDATE hub_agente_unidad_versiones "
        "SET adjunto = CASE WHEN espera_adjunto THEN 'obligatorio' ELSE 'no' END"
    )
    op.drop_column('hub_agente_unidad_versiones', 'espera_adjunto')
    op.create_check_constraint(
        "ck_agente_unidad_version_adjunto",
        "hub_agente_unidad_versiones",
        "adjunto IN ('no', 'opcional', 'obligatorio')",
    )
    op.create_check_constraint(
        "ck_agente_unidad_version_lengua_respuesta",
        "hub_agente_unidad_versiones",
        "lengua_respuesta IN ('pregunta', 'es', 'ca')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agente_unidad_version_lengua_respuesta", "hub_agente_unidad_versiones", type_="check")
    op.drop_constraint("ck_agente_unidad_version_adjunto", "hub_agente_unidad_versiones", type_="check")
    op.add_column('hub_agente_unidad_versiones', sa.Column('espera_adjunto', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    # `opcional` no existía: lo más fiel es «sí», porque el prompt lo admitía.
    op.execute("UPDATE hub_agente_unidad_versiones SET espera_adjunto = (adjunto <> 'no')")
    op.drop_column('hub_agente_unidad_versiones', 'lengua_respuesta')
    op.drop_column('hub_agente_unidad_versiones', 'adjunto')
