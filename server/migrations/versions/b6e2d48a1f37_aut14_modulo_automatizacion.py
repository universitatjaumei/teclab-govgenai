"""El módulo `automatizacion`: el catálogo de funciones sale de `informes` (2026-10-05).

Decisión del usuario, opción A: «Informes» se queda con plantillas, workspaces, borradores y los
scripts que quien redacta propone para su plantilla; el catálogo de funciones —con las de origen
externo, su revisión y la ejecución por API— pasa a «Automatización». Ver
`core/auth/modulos.py`.

**Se concede a quien ya tenía `informes`**, con el mismo `INSERT ... SELECT` idempotente de REG.6:
nadie pierde lo que hoy usa por partir un módulo en dos. Al hacerlo no había ninguna concesión de
`informes` en producción, así que en la práctica sólo entra la fila del catálogo; la copia queda
para cualquier instalación que sí las tenga.

Revision ID: b6e2d48a1f37
Revises: d5cf0e7a5973
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "b6e2d48a1f37"
down_revision = "d5cf0e7a5973"
branch_labels = None
depends_on = None

_MODULO = "automatizacion"
_ETIQUETA = "Automatización"
_FIRMA = "migracion:aut14"


def upgrade() -> None:
    conexion = op.get_bind()

    # El catálogo primero: `modulos_del_usuario` cruza las concesiones con los módulos
    # `vigente`, así que sin la fila del catálogo la concesión no daría acceso a nada.
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
            "  WHERE g.module_code = 'informes'"
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
