"""AUT.6 (issue #116) — `hub_manifiestos_externos`: la evidencia de lo que corrió fuera.

Tabla propia y no `hub_run_manifests`, y es estructural: aquélla exige `workspace_id` y
`template_version_id` con clave ajena, y una ejecución de fuera no tiene ninguno de los dos.
Hacerlos nulos para que quepan las dos cosas dejaría una tabla en la que la mitad de las filas
incumplen lo que la otra mitad garantiza — y lo que `hub_run_manifests` garantiza es justamente
que cada manifiesto apunta a la plantilla exacta que lo produjo.

Las columnas sueltas duplican lo que ya va en `payload_json` **a propósito**: son por las que se
filtra y se ordena al leer.

Revision ID: e8c3f5a2b904
Revises: d4b8c0e71f93
Create Date: 2026-09-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8c3f5a2b904"
down_revision: str | Sequence[str] | None = "d4b8c0e71f93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hub_manifiestos_externos",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("organizacion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ocurrido_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("depositado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aplicacion", sa.String(length=100), nullable=False),
        sa.Column("referencia_externa", sa.String(length=255), nullable=True),
        sa.Column("finalidad", sa.String(length=500), nullable=False),
        sa.Column("modelo_usado", sa.String(length=100), nullable=True),
        sa.Column("hash_de_la_salida", sa.String(length=64), nullable=True),
        sa.Column("funcion_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_hub_manifiestos_externos_organizacion_id",
        "hub_manifiestos_externos",
        ["organizacion_id"],
    )
    op.create_index(
        "ix_hub_manifiestos_externos_ocurrido_en",
        "hub_manifiestos_externos",
        ["ocurrido_en"],
    )
    op.create_index(
        "ix_hub_manifiestos_externos_aplicacion",
        "hub_manifiestos_externos",
        ["aplicacion"],
    )
    op.create_index(
        "ix_hub_manifiestos_externos_funcion_sha256",
        "hub_manifiestos_externos",
        ["funcion_sha256"],
    )


def downgrade() -> None:
    op.drop_table("hub_manifiestos_externos")
