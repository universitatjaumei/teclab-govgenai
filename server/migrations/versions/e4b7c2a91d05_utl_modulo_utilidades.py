"""UTL — el módulo `utilidades`, para las operaciones sueltas que hoy se hacen fuera.

Unir o partir un PDF (#190) y anonimizar un fichero para compartirlo (#191). **Un módulo propio**
y no dentro de `informes`: no son informes ni pasos de un flujo, son operaciones que necesita
cualquiera que trabaje con documentos, y meterlas en `informes` obligaría a conceder la
redacción de informes para poder dar una utilidad de PDF.

**Se concede a quien ya tenía `informes` o `plataforma`.** REG.6 concedía su módulo a quien tenía
`plataforma` porque el registro lo mira quien administra; estas utilidades las usa quien trabaja
con documentos, y ése es el colectivo de `informes` —«todo el que necesita hacer informes»—. Sin
esto el módulo nacería sin nadie que pudiera usarlo, que es lo que pasó en producción con las
concesiones vacías.

Mismo `INSERT ... SELECT` idempotente que REG.6, por nombre de restricción y copiando los cuatro
campos: conceder `utilidades` «en todas» a quien tiene `informes` en una sola sería ampliarle el
alcance.

Revision ID: e4b7c2a91d05
Revises: bd93bc9196a1
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "e4b7c2a91d05"
down_revision = "bd93bc9196a1"
branch_labels = None
depends_on = None

_MODULO = "utilidades"
_ETIQUETA = "Utilidades"
_FIRMA = "migracion:utl"


def upgrade() -> None:
    conexion = op.get_bind()

    # El catálogo primero: sin la fila, la concesión no daría acceso a nada.
    conexion.execute(
        sa.text(
            "INSERT INTO hub_platform_modules (code, label, vigente)"
            " VALUES (:code, :label, true)"
            " ON CONFLICT (code) DO NOTHING"
        ),
        {"code": _MODULO, "label": _ETIQUETA},
    )

    conexion.execute(
        sa.text(
            "INSERT INTO hub_module_grants"
            " (subject_type, subject_id, module_code, organizacion_id, granted_by)"
            " SELECT DISTINCT g.subject_type, g.subject_id, :modulo, g.organizacion_id, :firma"
            "   FROM hub_module_grants AS g"
            "  WHERE g.module_code IN ('informes', 'plataforma')"
            " ON CONFLICT ON CONSTRAINT uq_grant_subject_type_module DO NOTHING"
        ),
        {"modulo": _MODULO, "firma": _FIRMA},
    )


def downgrade() -> None:
    conexion = op.get_bind()
    # Sólo las concesiones que puso esta migración: una puesta a mano después es de su autor.
    conexion.execute(
        sa.text(
            "DELETE FROM hub_module_grants WHERE module_code = :modulo AND granted_by = :firma"
        ),
        {"modulo": _MODULO, "firma": _FIRMA},
    )
    conexion.execute(
        sa.text("DELETE FROM hub_platform_modules WHERE code = :modulo"),
        {"modulo": _MODULO},
    )
