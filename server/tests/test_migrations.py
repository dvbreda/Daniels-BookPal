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


def _seed(connection, tabel: str, teller: int) -> None:
    """Zet één rij in ``tabel``, wat de kolommen op dat moment ook zijn.

    Generiek en niet met een vaste kolomlijst: deze test moet juist blijven
    werken als er later kolommen bijkomen — dat is het hele punt. ``teller``
    houdt de waarden uniek, want tabellen met een unieke kolom zouden anders
    bij de volgende migratiestap op zichzelf botsen.
    """
    from sqlalchemy import text

    kolommen = list(connection.execute(text(f"PRAGMA table_info('{tabel}')")))
    namen: list[str] = []
    waarden: dict[str, object] = {}
    for _cid, naam, soort, notnull, standaard, pk in kolommen:
        soort = (soort or "").upper()
        # Een integer-primary-key vult SQLite zelf; een tekstsleutel niet.
        if pk and "INT" in soort:
            continue
        if standaard is not None or not (notnull or pk):
            continue
        if "BOOL" in soort:
            waarde: object = 0
        elif "INT" in soort:
            waarde = teller
        elif "FLOAT" in soort or "REAL" in soort or "NUMERIC" in soort:
            waarde = 1.0
        elif "JSON" in soort:
            waarde = "{}"
        elif "DATE" in soort or "TIME" in soort:
            waarde = "2026-01-01 00:00:00"
        else:
            waarde = f"x{teller}"
        namen.append(naam)
        waarden[naam] = waarde

    if not namen:
        connection.execute(text(f"INSERT INTO {tabel} DEFAULT VALUES"))
        return
    kolomlijst = ", ".join(namen)
    plaatshouders = ", ".join(f":{naam}" for naam in namen)
    connection.execute(
        text(f"INSERT INTO {tabel} ({kolomlijst}) VALUES ({plaatshouders})"), waarden
    )


def test_migrations_survive_a_database_with_rows(temp_settings: Path):
    """Elke migratie stap voor stap, met gevulde tabellen.

    Op lege tabellen slaagt bijna alles. Een NOT NULL-kolom zonder
    server_default gaat pas stuk zodra er rijen zijn — en dat is precies de
    situatie op de NAS, niet in de test. Daarom hier na elke stap iets erin
    zetten en pas dan verder.
    """
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    config = alembic_config()
    script = ScriptDirectory.from_config(config)
    revisies = [revision.revision for revision in script.walk_revisions()][::-1]

    engine = get_engine()
    teller = 0
    for revision in revisies:
        command.upgrade(config, revision)
        with engine.begin() as connection:
            tabellen = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
                if not row[0].startswith(("sqlite_", "alembic_"))
            }
            # Even zonder verwijzingscontrole: het gaat hier om de kolommen,
            # niet om kloppende relaties. Anders zou deze test ook nog de
            # invoegvolgorde van elke tabel moeten kennen.
            connection.execute(text("PRAGMA foreign_keys = OFF"))
            try:
                for tabel in sorted(tabellen):
                    teller += 1
                    _seed(connection, tabel, teller)
            finally:
                connection.execute(text("PRAGMA foreign_keys = ON"))
