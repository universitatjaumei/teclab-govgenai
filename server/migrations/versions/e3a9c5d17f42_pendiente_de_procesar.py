"""La página recuerda que el rastreo la vio nueva o cambiada hasta que el job la procesa (#247).

El rastreo pasa a confirmar cada página al guardarla, para que proponer una página mientras se
rastrea su sitio no espere doce minutos a un bloqueo. Con eso, lo que el job hacía después —reingerir
lo cambiado, ingerir lo nuevo— no puede seguir dependiendo de la memoria del rastreo: tras un
reinicio a mitad, la página ya estaría guardada con su contenido nuevo y nadie la vería cambiar.

Una columna nula en `hub_crawled_pages`: `nueva`, `cambiada` o nula. Las filas que ya existen
quedan a nula, que es lo que eran: nada pendiente.

Revision ID: e3a9c5d17f42
Revises: c8e4f1a7b2d9
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa

revision = "e3a9c5d17f42"
down_revision = "c8e4f1a7b2d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hub_crawled_pages",
        sa.Column("pendiente", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hub_crawled_pages", "pendiente")
