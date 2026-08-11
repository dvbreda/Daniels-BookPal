"""Bewaakt dat de migraties en de modellen niet uit elkaar lopen.

Zonder deze test merk je schema-drift pas als de server op de NAS omvalt op een
kolom die alleen in de modellen bestaat.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from bookpal.db import get_engine
from bookpal.models import Base

SERVER_DIR = Path(__file__).resolve().parent.parent


def alembic_config() -> Config:
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    return config


def test_migrations_produce_the_model_schema(temp_settings: Path):
    command.upgrade(alembic_config(), "head")

    with get_engine().connect() as connection:
        context = MigrationContext.configure(connection)
        diff = compare_metadata(context, Base.metadata)

    assert diff == [], f"migraties lopen achter op de modellen: {diff}"


def test_downgrade_to_base_leaves_no_tables(temp_settings: Path):
    config = alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    with get_engine().connect() as connection:
        context = MigrationContext.configure(connection)
        # Alles behalve alembic's eigen boekhouding is weg, dus alle
        # modeltabellen komen als 'toe te voegen' terug.
        diff = compare_metadata(context, Base.metadata)

    added_tables = {entry[1].name for entry in diff if entry[0] == "add_table"}
    assert "book" in added_tables
    assert "series" in added_tables
