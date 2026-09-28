"""AUT.5 (issue #124) — el evento de actividad dice qué programa se ejecutó.

`funcion_sha256` en `hub_actividad_ia`: el SHA-256 del fichero que corrió, que es
`hub_funcion_versiones.code_sha256` cuando ese fichero está registrado como función de origen
externo (AUT.3). Cierra el circuito: el catálogo dice qué cuadernos existen y el registro dice
cuándo corrieron.

**Indexado**, porque ese cruce es la consulta que justifica el campo.

No se reutilizó `payload_hash`: ése significa «el SHA-256 del contenido procesado», y darle un
segundo significado dejaría sin poder leerse el único campo que sirve para cotejar un tratamiento
concreto.

Revision ID: d4b8c0e71f93
Revises: c7e2a91d45b8
Create Date: 2026-09-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4b8c0e71f93"
down_revision: str | Sequence[str] | None = "c7e2a91d45b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hub_actividad_ia",
        sa.Column("funcion_sha256", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_hub_actividad_ia_funcion_sha256",
        "hub_actividad_ia",
        ["funcion_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_hub_actividad_ia_funcion_sha256", table_name="hub_actividad_ia")
    op.drop_column("hub_actividad_ia", "funcion_sha256")
