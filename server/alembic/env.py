"""Alembic-omgeving.

De database-URL komt uit dezelfde settings als de applicatie, zodat een
migratie nooit per ongeluk op een andere database landt dan de server gebruikt.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from bookpal.config import settings
from bookpal.models import Base

config = context.config
# Zonder dit faalt een migratie op een verse installatie, omdat de map waarin
# de database moet komen nog niet bestaat.
settings.ensure_dirs()
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite kan geen kolommen wijzigen; batch-modus bouwt de tabel
            # opnieuw op. Zonder dit loopt elke latere migratie vast.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
