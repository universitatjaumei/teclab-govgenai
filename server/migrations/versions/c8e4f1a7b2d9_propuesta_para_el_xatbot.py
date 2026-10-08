"""Proponer una página para un asistente mientras se cura la web (2026-10-08).

Piloto de un asistente alimentado desde la web de la Escuela de Doctorado: quien cura propone qué
páginas deberían alimentarlo y quien lo crea decide en Publicación. La marca es de la página, no
de un asistente —todavía no existe cuando se propone—, y dice quién la puso y cuándo.

Dos columnas nulas en `hub_crawled_pages`: nula es «no propuesta». El rastreo actualiza la página
por su URL sin tocarlas, así que una propuesta sobrevive a volver a rastrear.

Revision ID: c8e4f1a7b2d9
Revises: b6e2d48a1f37
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa

revision = "c8e4f1a7b2d9"
down_revision = "b6e2d48a1f37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hub_crawled_pages",
        sa.Column("propuesta_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "hub_crawled_pages",
        sa.Column("propuesta_por", sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hub_crawled_pages", "propuesta_por")
    op.drop_column("hub_crawled_pages", "propuesta_at")
