"""#271 — retira `schedulerconfig` y `automation_library`, las tablas de dos cosas sin uso.

**`schedulerconfig`.** `services/scheduler_service.py` refrescaba la caché de modelos y los precios
con APScheduler y leía su horario de esta tabla, pero **nada lo arrancaba**: ni el *lifespan* ni
ningún router lo importaba. El planificador que sí corre es el de calidad de curación, que no la
usa. Tiene a lo sumo una fila, el horario por omisión.

**`automation_library`.** La biblioteca de automatizaciones —`/v1/library`: publicar, descargar y
firmar *blueprints*— servía al agente de ejecución local, que se descartó el 2026-09-23. No la
llamaba el panel, ni el MCP, ni ningún guion. Retirarla entera, con la tabla, es decisión del
usuario del 2026-10-23, sabiendo que si producción tuviera filas se perderían; el código queda en
el historial de git. Con ella se va su tipo enumerado de Postgres, `automationtype`, que
`sa.Enum` creó aparte y que `drop_table` no borra.

Revision ID: 1dd4d0eac847
Revises: fd7ffcbc170d
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "1dd4d0eac847"
down_revision: Union[str, None] = "fd7ffcbc170d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `IF EXISTS`, como en BD.1: la misma revisión tiene que poder correr sobre una base que ya
    # perdió una de las dos —una de desarrollo a medio migrar— sin reventar en la primera.
    op.execute('DROP TABLE IF EXISTS "schedulerconfig"')
    op.execute('DROP TABLE IF EXISTS "automation_library"')
    op.execute("DROP TYPE IF EXISTS automationtype")


def downgrade() -> None:
    """Las recrea con el esquema de `8879cf0a3197`, que es el que tenían; vacías."""
    op.create_table(
        "schedulerconfig",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("refresh_hour", sa.Integer(), nullable=False),
        sa.Column("refresh_minute", sa.Integer(), nullable=False),
        sa.Column("last_run", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "automation_library",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "PDF_EXTRACTOR", "RPA_WEB", "ETL_TRANSFORM", "CHART_GENERATOR",
                "CUSTOM_SCRIPT", "WORKFLOW", name="automationtype",
            ),
            nullable=False,
        ),
        sa.Column("code_content", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("partner_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("is_system_template", sa.Boolean(), nullable=False),
        sa.Column("signature", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("is_workflow", sa.Boolean(), nullable=False),
        sa.Column("access_groups", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    for columna in ("client_id", "id", "name", "partner_id"):
        op.create_index(
            op.f(f"ix_automation_library_{columna}"), "automation_library", [columna], unique=False
        )
