"""#343 — deja un solo modelo por defecto en cada grupo, antes de que el índice lo exija.

Datos y esquema en migraciones separadas: esta desmarca, la siguiente crea el índice. Un grupo es
nivel, propósito y organización, con la plataforma (organización nula) como un grupo más.

**Cuál se queda**: el que usan más chatbots, y a igualdad, el de menor `id`. No hay fecha de
creación en la tabla, y «el que más se usa» es lo más parecido a «el que alguien eligió». En
producción no cambia nada: el 30-10 ya se dejó uno a mano desde el panel.

Repetible: una segunda pasada no encuentra grupos con más de uno.

Revision ID: d4f8a2c61e07
Revises: c3e7a1f94b20
Create Date: 2026-10-30
"""
from alembic import op

revision = "d4f8a2c61e07"
down_revision = "c3e7a1f94b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH uso AS (
            SELECT c.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY c.tier, c.purpose, c.organizacion_id
                       ORDER BY (SELECT count(*) FROM hub_chatbots b WHERE b.llm_config_id = c.id) DESC,
                                c.id
                   ) AS orden
            FROM hub_llm_configs c
            WHERE c.is_default
        )
        UPDATE hub_llm_configs SET is_default = false
        WHERE id IN (SELECT id FROM uso WHERE orden > 1)
        """
    )


def downgrade() -> None:
    # Qué filas estaban marcadas no se guarda: volver a tener varias por defecto es justo el
    # defecto que esto corrige.
    pass
