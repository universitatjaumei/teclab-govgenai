"""Retira nueve tablas heredadas de AutomatIA que no usa ningún código (#249).

Las encontró el inventario de retención (#162): se creaban en cada base y sólo las nombraban la
siembra de desarrollo y un guion de arreglo de esquema de la época de SQLite. Una, `clientaccount`,
tenía columnas de correo y NIF. En producción estaban vacías las nueve (contado el 2026-10-09),
así que el borrado no suprime ningún dato.

**El orden importa por las claves foráneas**: primero las hojas, `clientaccount` la última. El
`downgrade` las recrea vacías, en el orden inverso.

Revision ID: 7bc443cdc4c9
Revises: e3a9c5d17f42
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7bc443cdc4c9"
down_revision = "e3a9c5d17f42"
branch_labels = None
depends_on = None

#: De las hojas a la raíz: las que apuntan a `license` antes que ella, y todas antes que
#: `clientaccount`.
TABLAS = (
    "licenseactivation",
    "licenseauditlog",
    "billingrecord",
    "scriptescalation",
    "server_security_policy",
    "clienttelemetrylog",
    "trustedscript",
    "license",
    "clientaccount",
)


def upgrade() -> None:
    # `drop_table` se lleva sus índices.
    for tabla in TABLAS:
        op.drop_table(tabla)


def downgrade() -> None:
    op.create_table('clientaccount',
    sa.Column('client_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('partner_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('email', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('nif', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('license_key', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['partner_id'], ['adminaccount.partner_id'], name=op.f('clientaccount_partner_id_fkey')),
    sa.PrimaryKeyConstraint('client_id', name=op.f('clientaccount_pkey'))
    )
    op.create_table('trustedscript',
    sa.Column('script_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('code', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('code_hash', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('status', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('script_id', name=op.f('trustedscript_pkey'))
    )
    op.create_table('license',
    sa.Column('license_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('client_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('quota_tokens', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('consumed_tokens', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('valid_until', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('status', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('max_seats', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clientaccount.client_id'], name=op.f('license_client_id_fkey')),
    sa.PrimaryKeyConstraint('license_id', name=op.f('license_pkey'))
    )
    op.create_table('licenseactivation',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('license_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('machine_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('device_name', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('activated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('last_seen', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['license_id'], ['license.license_id'], name=op.f('licenseactivation_license_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('licenseactivation_pkey'))
    )
    op.create_index(op.f('ix_licenseactivation_machine_id'), 'licenseactivation', ['machine_id'], unique=False)
    op.create_index(op.f('ix_licenseactivation_license_id'), 'licenseactivation', ['license_id'], unique=False)
    op.create_table('licenseauditlog',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('license_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('action', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('details', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('performed_by', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('timestamp', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['license_id'], ['license.license_id'], name=op.f('licenseauditlog_license_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('licenseauditlog_pkey'))
    )
    op.create_index(op.f('ix_licenseauditlog_license_id'), 'licenseauditlog', ['license_id'], unique=False)
    op.create_table('billingrecord',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('timestamp', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('partner_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('client_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('operation', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('tokens_used', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('model_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('cost_usd', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clientaccount.client_id'], name=op.f('billingrecord_client_id_fkey')),
    sa.ForeignKeyConstraint(['partner_id'], ['adminaccount.partner_id'], name=op.f('billingrecord_partner_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('billingrecord_pkey'))
    )
    op.create_table('scriptescalation',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('partner_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('client_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('script_name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('original_code', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('escalation_type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('status', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('client_notes', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clientaccount.client_id'], name=op.f('scriptescalation_client_id_fkey')),
    sa.ForeignKeyConstraint(['partner_id'], ['adminaccount.partner_id'], name=op.f('scriptescalation_partner_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('scriptescalation_pkey'))
    )
    op.create_index(op.f('ix_scriptescalation_partner_id'), 'scriptescalation', ['partner_id'], unique=False)
    op.create_index(op.f('ix_scriptescalation_client_id'), 'scriptescalation', ['client_id'], unique=False)
    op.create_table('server_security_policy',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('scope', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('partner_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('client_id', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('allowed_domains', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('allowed_libraries', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('forbidden_libraries', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('screenshot_policy', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('trusted_screenshot_domains', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('max_execution_time', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('max_memory_mb', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clientaccount.client_id'], name=op.f('server_security_policy_client_id_fkey')),
    sa.ForeignKeyConstraint(['partner_id'], ['adminaccount.partner_id'], name=op.f('server_security_policy_partner_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('server_security_policy_pkey'))
    )
    op.create_index(op.f('ix_server_security_policy_partner_id'), 'server_security_policy', ['partner_id'], unique=False)
    op.create_index(op.f('ix_server_security_policy_client_id'), 'server_security_policy', ['client_id'], unique=False)
    op.create_table('clienttelemetrylog',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('machine_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('manifest_id', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('script_hash', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('execution_time_ms', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('total_tokens', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('cost_estimated', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('status', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('error_type', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('error_message', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('timestamp_client', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('synced_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clientaccount.client_id'], name=op.f('clienttelemetrylog_client_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('clienttelemetrylog_pkey'))
    )
    op.create_index(op.f('ix_clienttelemetrylog_manifest_id'), 'clienttelemetrylog', ['manifest_id'], unique=False)
    op.create_index(op.f('ix_clienttelemetrylog_machine_id'), 'clienttelemetrylog', ['machine_id'], unique=False)
    op.create_index(op.f('ix_clienttelemetrylog_client_id'), 'clienttelemetrylog', ['client_id'], unique=False)
