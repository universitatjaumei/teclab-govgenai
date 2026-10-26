"""PLG.2 estrategias por eje y el CHECK de retrieval_mode fuera

Revision ID: 611e53c82fcb
Revises: 8f5a3c2d1e07
Create Date: 2026-09-16 06:22:25.910681

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '611e53c82fcb'
down_revision: Union[str, None] = '8f5a3c2d1e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hub_chatbots', sa.Column('estrategias', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('hub_organizaciones', sa.Column('default_estrategias', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # **Esto lo autogenerado NO lo detecta**: Alembic no compara `CheckConstraint`, así que la
    # retirada va escrita a mano. Sin ella, el bloque entero sería inútil para terceros — el
    # modo se validaría contra el registro vivo en el router, pasaría, y Postgres lo rechazaría
    # al guardar. El CHECK era correcto mientras los modos eran una cadena de `if`; desde PLG.1
    # llegan instalando un paquete, y un CHECK no puede saber qué hay instalado.
    #
    # `IF EXISTS` porque la misma revisión tiene que valer donde la restricción está y donde no:
    # la base de desarrollo y la de producción no han seguido el mismo camino (BD.1).
    op.execute(
        "ALTER TABLE hub_chatbots DROP CONSTRAINT IF EXISTS ck_chatbot_retrieval_mode"
    )


def downgrade() -> None:
    # Al volver atrás hay que reponer el CHECK, pero **sólo si los datos lo admiten**: si algún
    # chatbot quedó con un modo aportado por un paquete, reponerlo a ciegas haría fallar la
    # migración con la base a medias. Se reponen los datos primero, al modo por defecto, y se
    # dice en el log.
    op.execute(
        "UPDATE hub_chatbots SET retrieval_mode = 'RAG' "
        "WHERE retrieval_mode NOT IN ('RAG', 'MD_LONG_CONTEXT', 'MD_AGENT_SELECTOR')"
    )
    op.create_check_constraint(
        "ck_chatbot_retrieval_mode",
        "hub_chatbots",
        "retrieval_mode IN ('RAG', 'MD_LONG_CONTEXT', 'MD_AGENT_SELECTOR')",
    )
    op.drop_column('hub_organizaciones', 'default_estrategias')
    op.drop_column('hub_chatbots', 'estrategias')
