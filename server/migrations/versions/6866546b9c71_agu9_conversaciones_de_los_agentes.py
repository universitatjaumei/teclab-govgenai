"""#216 — las conversaciones con los agentes de unidad, en validación o sólo las incidencias.

Cada agente lleva su modo de registro (`validacion` de partida, también para los que ya hay:
primero se comprueba que funcionan), y cada consulta el modo con que se hizo, la pregunta, la
respuesta que leyó la extensión y la valoración. Las consultas anteriores quedan en `incidencias`,
que es lo que fueron: no guardaron nada. Los CHECK van a mano porque Alembic no los detecta.

Revision ID: 6866546b9c71
Revises: c83adf77b4ce
Create Date: 2026-10-03 21:14:26.623410

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6866546b9c71'
down_revision: Union[str, None] = 'c83adf77b4ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hub_agente_consultas', sa.Column('modo', sa.String(length=12), server_default='incidencias', nullable=False))
    op.add_column('hub_agente_consultas', sa.Column('pregunta', sa.Text(), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('respuesta', sa.Text(), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('respuesta_en', sa.DateTime(timezone=True), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('respuesta_no_capturada', sa.String(length=20), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('fuentes', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('puntuacion', sa.Integer(), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('motivo', sa.String(length=40), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('comentario', sa.Text(), nullable=True))
    op.add_column('hub_agente_consultas', sa.Column('valorada_en', sa.DateTime(timezone=True), nullable=True))
    op.add_column('hub_agentes_unidad', sa.Column('modo_registro', sa.String(length=12), server_default='validacion', nullable=False))
    op.create_check_constraint(
        "ck_agente_consulta_modo", "hub_agente_consultas", "modo IN ('validacion', 'incidencias')"
    )
    op.create_check_constraint(
        "ck_agente_consulta_puntuacion", "hub_agente_consultas", "puntuacion IS NULL OR puntuacion IN (-1, 1)"
    )
    op.create_check_constraint(
        "ck_agente_unidad_modo_registro", "hub_agentes_unidad", "modo_registro IN ('validacion', 'incidencias')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_agente_unidad_modo_registro", "hub_agentes_unidad", type_="check")
    op.drop_constraint("ck_agente_consulta_puntuacion", "hub_agente_consultas", type_="check")
    op.drop_constraint("ck_agente_consulta_modo", "hub_agente_consultas", type_="check")
    op.drop_column('hub_agentes_unidad', 'modo_registro')
    op.drop_column('hub_agente_consultas', 'valorada_en')
    op.drop_column('hub_agente_consultas', 'comentario')
    op.drop_column('hub_agente_consultas', 'motivo')
    op.drop_column('hub_agente_consultas', 'puntuacion')
    op.drop_column('hub_agente_consultas', 'fuentes')
    op.drop_column('hub_agente_consultas', 'respuesta_no_capturada')
    op.drop_column('hub_agente_consultas', 'respuesta_en')
    op.drop_column('hub_agente_consultas', 'respuesta')
    op.drop_column('hub_agente_consultas', 'pregunta')
    op.drop_column('hub_agente_consultas', 'modo')
