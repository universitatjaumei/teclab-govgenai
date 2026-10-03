"""#215 — el adaptador del asistente: los selectores con los que la extensión inserta y lee.

Crea la tabla y siembra Gemini con los selectores comprobados el 2026-10-03 contra su página. Es
una **copia literal** de `extension/adaptadores/gemini.json` en esa fecha: una migración no lee
ficheros que pueden cambiar después. Lo que se corrija luego se corrige en la fila, desde la
plataforma, sin migraciones.

Revision ID: c83adf77b4ce
Revises: a8c5e1f3b479
Create Date: 2026-10-03 19:56:05.424978

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c83adf77b4ce'
down_revision: Union[str, None] = 'a8c5e1f3b479'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GEMINI = {
    "asistente": "gemini",
    "nombre": "Gemini",
    "origen": "https://gemini.google.com",
    "selectores": {
        "cuadro": "rich-textarea [role='textbox'][contenteditable='true']",
        "respuesta": "model-response",
        "texto": "message-content [aria-live]",
        "ocupado": "aria-busy",
        "fuentes": "sources-list a[href]",
    },
}


def upgrade() -> None:
    tabla = op.create_table('hub_asistente_adaptadores',
    sa.Column('asistente', sa.String(length=40), nullable=False),
    sa.Column('nombre', sa.String(length=80), nullable=False),
    sa.Column('origen', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('selectores', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actualizado_por', sa.String(length=255), nullable=True),
    sa.Column('fallos_de_la_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('ultimo_fallo_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_fallo_selector', sa.String(length=40), nullable=True),
    sa.PrimaryKeyConstraint('asistente')
    )
    op.bulk_insert(tabla, [GEMINI])


def downgrade() -> None:
    op.drop_table('hub_asistente_adaptadores')
