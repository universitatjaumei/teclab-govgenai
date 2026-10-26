import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool
from alembic import context
from sqlmodel import SQLModel

# Load server/.env so DATABASE_URL_SYNC is available when running alembic from server/
load_dotenv(Path(__file__).parent.parent / ".env")

# Import all models so Alembic can detect them
import server.app.database.models
import server.app.modules.agents_hub.database.config_models
import server.app.modules.agents_hub.database.operational_models
import server.app.modules.redaccion.database.models  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Combine both metadatas so Alembic tracks Hub tables alongside SQLModel tables
from server.app.modules.agents_hub.database.base import HubConfigBase, HubOperationalBase
target_metadata = [SQLModel.metadata, HubConfigBase.metadata, HubOperationalBase.metadata]

# Use the sync URL for Alembic (psycopg2, not asyncpg)
database_url = os.environ.get("DATABASE_URL_SYNC")
if not database_url:
    # Fallback: derive sync URL from async URL
    async_url = os.environ.get("DATABASE_URL", "")
    database_url = async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
