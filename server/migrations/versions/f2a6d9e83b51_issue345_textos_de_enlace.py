"""#345 — los textos de los enlaces de cada página rastreada.

El texto guardado de una página ya no tiene etiquetas, así que no dice qué líneas eran enlaces, y es
lo que separa una página de navegación de una con poco contenido. **Nullable**: las páginas ya
rastreadas no lo tienen hasta el siguiente rastreo, y mientras tanto el detector las juzga como
antes.

Revision ID: f2a6d9e83b51
Revises: e9b3c7d15a42
Create Date: 2026-10-30
"""
from alembic import op

revision = "f2a6d9e83b51"
down_revision = "e9b3c7d15a42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE hub_crawled_pages ADD COLUMN IF NOT EXISTS textos_de_enlace JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE hub_crawled_pages DROP COLUMN IF EXISTS textos_de_enlace")
