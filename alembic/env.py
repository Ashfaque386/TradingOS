import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.core.config import get_settings
from src.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# REL-014 E14.1 (GLH-05): migrations need DDL rights (CREATE ROLE, ALTER TABLE, ...) that the
# app's own runtime role (`tradingos_app`, non-superuser as of u2v3w4x5y6z7) deliberately does
# not have. MIGRATION_DATABASE_URL lets Alembic keep using the schema-owning `tradingos` role
# without that role ever being part of the running application's own DATABASE_URL. Falls back to
# database_url so any environment that hasn't set this (or predates the role split) still works.
config.set_main_option(
    "sqlalchemy.url", os.environ.get("MIGRATION_DATABASE_URL") or get_settings().database_url
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
