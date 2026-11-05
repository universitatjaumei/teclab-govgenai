"""#370 — la región de Vertex es del proveedor.

**Nullable**: nulo es «la de `GOOGLE_CLOUD_LOCATION`», que es lo que vale para todos los
proveedores existentes al aplicar la migración. La fila `vertex-global` no la crea esta
migración sino la semilla del arranque, como el resto de proveedores.

Revision ID: b3e8f1a27c90
Revises: a7c4e2f91d36
Create Date: 2026-11-05
"""
from alembic import op

revision = "b3e8f1a27c90"
down_revision = "a7c4e2f91d36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE hub_providers ADD COLUMN IF NOT EXISTS location VARCHAR(50)")


def downgrade() -> None:
    op.execute("ALTER TABLE hub_providers DROP COLUMN IF EXISTS location")
