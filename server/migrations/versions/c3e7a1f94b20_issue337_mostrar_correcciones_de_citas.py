"""#337 — el interruptor que enseña al usuario las correcciones del contrato de citas.

El contrato de citas corre después de generar y corrige la respuesta: baja al documento un ancla
que nadie leyó, quita el enlace a lo que no se entregó. Pero el chat emite los tokens según salen
del modelo, así que esas correcciones no llegaban a nadie. Mostrarlas exige reemplazar el texto al
final de la respuesta, y eso se ve: por eso es un interruptor por chatbot y no el comportamiento
por omisión.

**Nullable, sin `server_default`**: nulo hereda el defecto de plataforma, que es apagado. Ningún
chatbot existente cambia por aplicar la migración. Sin capa de organización: es un ajuste que se
decide midiendo cada asistente.

Revision ID: c3e7a1f94b20
Revises: 1dd4d0eac847
Create Date: 2026-10-30
"""
from alembic import op

revision = "c3e7a1f94b20"
down_revision = "1dd4d0eac847"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hub_chatbots ADD COLUMN IF NOT EXISTS show_citation_corrections BOOLEAN"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE hub_chatbots DROP COLUMN IF EXISTS show_citation_corrections")
