"""Issue #94 — la contraseña que restablece otra persona vale una sola vez.

Tres columnas en `hub_users`:

- `debe_cambiar_contrasena`: mientras sea cierto, el token que se emita no sirve para nada más
  que cambiarla. Es lo que acota a **un solo uso** el conocimiento de quien la restableció.
- `password_reset_at` / `password_reset_by`: la traza. Sin ella, un restablecimiento es
  indistinguible de un cambio propio y la pregunta «¿quién más ha conocido esta contraseña?»
  no tiene respuesta.

El `server_default` de la primera es lo que deja **en «nada pendiente» a las filas que ya
existen**: sin él, `NOT NULL` no se puede añadir sobre una tabla con datos, y con `NULL` como
tercer estado nadie sabría qué hacer con quien ya estaba dentro.

Revision ID: e1a4c7b93f20
Revises: d9d8fbe8d60d
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1a4c7b93f20"
down_revision: str | Sequence[str] | None = "d9d8fbe8d60d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hub_users",
        sa.Column(
            "debe_cambiar_contrasena",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "hub_users",
        sa.Column("password_reset_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "hub_users",
        sa.Column("password_reset_by", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hub_users", "password_reset_by")
    op.drop_column("hub_users", "password_reset_at")
    op.drop_column("hub_users", "debe_cambiar_contrasena")
