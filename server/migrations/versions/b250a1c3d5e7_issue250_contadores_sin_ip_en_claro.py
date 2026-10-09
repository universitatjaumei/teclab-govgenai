"""Borra los contadores de cuota que guardan la IP del anónimo en claro (#250).

Desde #250 el sujeto `ip` es una huella con clave y con el día dentro (`huella_de_ip`), no la
dirección. Las filas anteriores llevan la IP tal cual en `subject_id`, una por IP y día, y no se
pueden convertir: la huella se calcula sobre la IP, que es justo lo que no se quiere conservar.

Se borran todas. Lo único que se pierde es lo gastado hoy por cada anónimo del widget, que vuelve
a contar desde cero; los días anteriores ya no limitaban nada.

El `downgrade` no las recupera: borrar un dato personal no tiene vuelta, y es lo que se pretende.

Revision ID: b250a1c3d5e7
Revises: 7bc443cdc4c9
Create Date: 2026-10-09
"""
from alembic import op

revision = "b250a1c3d5e7"
down_revision = "7bc443cdc4c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM hub_usage_counters WHERE subject_type = 'ip'")


def downgrade() -> None:
    pass
