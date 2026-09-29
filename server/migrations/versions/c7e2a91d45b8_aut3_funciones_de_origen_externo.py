"""AUT.3 (issue #114) — el tercer origen del catálogo: la función externa.

Un cuaderno o un script que **se ejecuta fuera** y aquí sólo se registra. Dos cambios:

- `origen` admite `externa`. Es estructura y no vocabulario —cada valor tiene consumidor en el
  código—, por eso vive en un `CheckConstraint` y ampliarlo es una migración.
- `entorno_ejecucion` en la versión: **dónde corre**. Es el dato que distingue este origen,
  porque la plataforma no lo ejecuta; sin él el registro no dice de qué responde nadie.

Nulo en los otros dos orígenes, que es lo que ya son las filas existentes: en `autoservicio`
corre el sandbox y en `paquete` el proceso, y las dos respuestas están en el código.

Revision ID: c7e2a91d45b8
Revises: b3f6d1c8a742
Create Date: 2026-09-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2a91d45b8"
down_revision: str | Sequence[str] | None = "b3f6d1c8a742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_funcion_origen", "hub_funciones", type_="check")
    op.create_check_constraint(
        "ck_funcion_origen",
        "hub_funciones",
        "origen IN ('autoservicio', 'paquete', 'externa')",
    )
    op.add_column(
        "hub_funcion_versiones",
        sa.Column("entorno_ejecucion", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hub_funcion_versiones", "entorno_ejecucion")
    # Volver atrás con funciones externas registradas dejaría filas que el `CHECK` rechaza, así
    # que se retiran primero. Es destructivo y por eso está escrito: bajar de aquí pierde el
    # registro de lo que corre fuera, que es justo lo que esta migración vino a guardar.
    op.execute("DELETE FROM hub_funciones WHERE origen = 'externa'")
    op.drop_constraint("ck_funcion_origen", "hub_funciones", type_="check")
    op.create_check_constraint(
        "ck_funcion_origen", "hub_funciones", "origen IN ('autoservicio', 'paquete')"
    )
