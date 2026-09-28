"""Issue #86 — dónde se guarda lo que se escribe en los bloques `USER_INPUT`.

Columna propia y no una clave más de `inputs_json`, que es la de los ficheros: `uploaded_slots`
devuelve las claves de aquélla como ficheros ya subidos, y el runner valida cada entrada como
`InputArtifact`. Un texto ahí saldría en la pantalla como un fichero subido y en el registro
como una entrada corrupta.

`NOT NULL` con defecto `{}`, que es lo que deja a los informes que ya existen sin nada escrito
en vez de con un nulo que cada lector tendría que interpretar.

Revision ID: b3f6d1c8a742
Revises: e1a4c7b93f20
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3f6d1c8a742"
down_revision: str | Sequence[str] | None = "e1a4c7b93f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hub_workspaces",
        sa.Column(
            "manual_inputs_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("hub_workspaces", "manual_inputs_json")
