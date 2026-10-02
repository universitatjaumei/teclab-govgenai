"""UTL — `utilidades` es de oficio: la tiene cualquier persona de la plataforma.

Decisión del usuario (2026-10-02). La migración anterior (`e4b7c2a91d05`) la concedía a quien ya
tenía `informes` o `plataforma`; eso dejaba fuera a quien sólo tuviera otro módulo, o ninguno, y a
todas las cuentas que se den de alta después sin que nadie se acuerde.

**Una marca del catálogo, `de_oficio`, y no una concesión por persona**: así vale para quien entre
mañana —también por Google o por SAML— y es dato, que se cambia sin desplegar.

Y las concesiones que puso aquella migración **se retiran**, porque con la marca no conceden nada
y una fila que no cambia nada es ruido en la pantalla de concesiones. Sólo las suyas, por su firma
(`migracion:utl`): una concesión puesta a mano es de su autor.

Revision ID: f2a8d6c3b190
Revises: e4b7c2a91d05
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "f2a8d6c3b190"
down_revision = "e4b7c2a91d05"
branch_labels = None
depends_on = None

_MODULO = "utilidades"
_FIRMA_ANTERIOR = "migracion:utl"


def upgrade() -> None:
    op.add_column(
        "hub_platform_modules",
        sa.Column("de_oficio", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    conexion = op.get_bind()
    conexion.execute(
        sa.text("UPDATE hub_platform_modules SET de_oficio = true WHERE code = :modulo"),
        {"modulo": _MODULO},
    )
    conexion.execute(
        sa.text(
            "DELETE FROM hub_module_grants WHERE module_code = :modulo AND granted_by = :firma"
        ),
        {"modulo": _MODULO, "firma": _FIRMA_ANTERIOR},
    )


def downgrade() -> None:
    conexion = op.get_bind()
    # Se devuelven las concesiones que la anterior había puesto, con su misma regla, para que
    # bajar a `e4b7c2a91d05` deje las cosas como esa migración las dejó.
    conexion.execute(
        sa.text(
            "INSERT INTO hub_module_grants"
            " (subject_type, subject_id, module_code, organizacion_id, granted_by)"
            " SELECT DISTINCT g.subject_type, g.subject_id, :modulo, g.organizacion_id, :firma"
            "   FROM hub_module_grants AS g"
            "  WHERE g.module_code IN ('informes', 'plataforma')"
            " ON CONFLICT ON CONSTRAINT uq_grant_subject_type_module DO NOTHING"
        ),
        {"modulo": _MODULO, "firma": _FIRMA_ANTERIOR},
    )
    op.drop_column("hub_platform_modules", "de_oficio")
