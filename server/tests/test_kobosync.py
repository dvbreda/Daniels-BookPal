"""De Nickel-integratie (laag B).

Dit is de enige laag die op reverse-engineering leunt, en de enige die in de
database van je lezer schrijft. De tests draaien tegen een nagebouwde
``KoboReader.sqlite`` met dezelfde tabellen als het echte apparaat, en leggen
vooral vast wat er *niet* mag gebeuren: niets van jou verdwijnt, en zonder
kopie wordt er niet geschreven.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from bookpal.db import current_user
from bookpal.kobosync import device as device_module
from bookpal.kobosync import files, nickel
from bookpal.models import Book, BookKind, File, LibraryRoot, Progress, Series

# Zoals Nickel hem aanmaakt, teruggebracht tot de kolommen die wij aanraken.
_SCHEMA = """
CREATE TABLE content (
    ContentID TEXT PRIMARY KEY,
    ContentType INTEGER,
    MimeType TEXT,
    BookID TEXT,
    Title TEXT,
    Attribution TEXT,
    ___PercentRead INTEGER,
    ReadStatus INTEGER,
    DateLastRead TEXT
);
CREATE TABLE Shelf (
    CreationDate TEXT, Id TEXT, InternalName TEXT, LastModified TEXT,
    Name TEXT, Type TEXT, _IsDeleted TEXT, _IsVisible TEXT, _IsSynced TEXT
);
CREATE TABLE ShelfContent (
    ShelfName TEXT, ContentId TEXT, DateModified TEXT, _IsDeleted TEXT, _IsSynced TEXT
);
"""


def _kobo(tmp_path: Path, boeken: list[tuple[str, int, int]] | None = None) -> Path:
    """Een nagebootst apparaat: een map met .kobo/KoboReader.sqlite erin."""
    mount = tmp_path / "kobo"
    (mount / ".kobo").mkdir(parents=True)
    db = mount / ".kobo" / "KoboReader.sqlite"
    connection = sqlite3.connect(db)
    connection.executescript(_SCHEMA)
    for pad, percent, status in boeken or []:
        connection.execute(
            "INSERT INTO content (ContentID, ContentType, Title, ___PercentRead, ReadStatus)"
            " VALUES (?, 6, ?, ?, ?)",
            (nickel.ONBOARD + pad, Path(pad).stem, percent, status),
        )
    connection.commit()
    connection.close()
    return mount


class TestRecognisingTheDevice:
    def test_a_folder_with_kobo_data_is_a_device(self, tmp_path: Path):
        mount = _kobo(tmp_path)
        apparaat = device_module.open_device(mount)
        assert apparaat.database.is_file()

    def test_a_random_usb_stick_is_refused(self, tmp_path: Path):
        """Zonder deze controle zetten we bestanden op de eerste de beste schijf."""
        stick = tmp_path / "stick"
        stick.mkdir()
        with pytest.raises(device_module.DeviceError, match="KoboReader"):
            device_module.open_device(stick)

    def test_a_path_that_is_not_mounted_says_so(self, tmp_path: Path):
        with pytest.raises(device_module.DeviceError, match="niet gekoppeld"):
            device_module.open_device(tmp_path / "weg")


class TestTheDatabase:
    def test_something_that_is_not_a_kobo_database_is_refused(self, tmp_path: Path):
        vreemd = tmp_path / "iets.sqlite"
        sqlite3.connect(vreemd).execute("CREATE TABLE dingen (id INTEGER)")
        with pytest.raises(nickel.NickelError, match="geen KoboReader"):
            nickel.connect(vreemd)

    def test_a_backup_is_made_next_to_the_original(self, tmp_path: Path):
        mount = _kobo(tmp_path)
        kopie = nickel.backup(mount / ".kobo" / "KoboReader.sqlite")
        assert kopie.is_file()
        assert kopie.parent == (mount / ".kobo")

    def test_two_backups_do_not_overwrite_each_other(self, tmp_path: Path, monkeypatch):
        """Juist als het misgaat wil je de oudste nog hebben."""
        mount = _kobo(tmp_path)
        db = mount / ".kobo" / "KoboReader.sqlite"
        tijden = iter(["20260101-120000", "20260101-120500"])

        class NepDatetime:
            @staticmethod
            def now(tz=None):
                return _NepTijd(next(tijden))

        monkeypatch.setattr(nickel, "datetime", NepDatetime)
        eerste = nickel.backup(db)
        tweede = nickel.backup(db)
        assert eerste != tweede
        assert eerste.is_file() and tweede.is_file()

    def test_only_sideloaded_books_are_read(self, tmp_path: Path):
        """Wat uit de Kobo-winkel komt heeft met ons niets te maken."""
        mount = _kobo(tmp_path, [("BookPal/Reeks/h1.cbz", 40, 1)])
        db = mount / ".kobo" / "KoboReader.sqlite"
        connection = sqlite3.connect(db)
        connection.execute(
            "INSERT INTO content (ContentID, ContentType, Title)"
            " VALUES ('abc-uit-de-winkel', 6, 'Gekocht')"
        )
        connection.commit()
        connection.close()

        with nickel.connect(db) as verbinding:
            gevonden = nickel.books(verbinding)
        assert [book.path for book in gevonden] == ["BookPal/Reeks/h1.cbz"]


class _NepTijd:
    def __init__(self, stempel: str) -> None:
        self._stempel = stempel

    def strftime(self, _formaat: str) -> str:
        return self._stempel


class TestShelves:
    def _verbinding(self, tmp_path: Path, boeken):
        mount = _kobo(tmp_path, boeken)
        return nickel.connect(mount / ".kobo" / "KoboReader.sqlite")

    def test_a_shelf_is_created_with_its_books(self, tmp_path: Path):
        verbinding = self._verbinding(tmp_path, [("BookPal/Reeks/h1.cbz", 0, 0)])
        rapport = nickel.write_shelves(
            verbinding, {"Manga": [nickel.content_id_for("BookPal/Reeks/h1.cbz")]}
        )
        assert rapport.created == ["Manga"]
        assert rapport.added == 1

        rijen = verbinding.execute("SELECT ShelfName, ContentId FROM ShelfContent").fetchall()
        assert len(rijen) == 1

    def test_running_twice_does_not_duplicate(self, tmp_path: Path):
        verbinding = self._verbinding(tmp_path, [("BookPal/Reeks/h1.cbz", 0, 0)])
        planken = {"Manga": [nickel.content_id_for("BookPal/Reeks/h1.cbz")]}
        nickel.write_shelves(verbinding, planken)
        tweede = nickel.write_shelves(verbinding, planken)

        assert tweede.created == []
        assert tweede.added == 0
        aantal = verbinding.execute("SELECT COUNT(*) FROM ShelfContent").fetchone()[0]
        assert aantal == 1

    def test_your_own_shelf_is_added_to_and_not_replaced(self, tmp_path: Path):
        """Dezelfde naam gebruiken mag jouw indeling niet weggooien."""
        verbinding = self._verbinding(
            tmp_path, [("BookPal/Reeks/h1.cbz", 0, 0), ("eigen/boek.epub", 0, 0)]
        )
        verbinding.execute(
            "INSERT INTO Shelf (Name, Type, _IsDeleted, _IsVisible)"
            " VALUES ('Manga', 'UserTag', 'false', 'true')"
        )
        verbinding.execute(
            "INSERT INTO ShelfContent (ShelfName, ContentId, _IsDeleted)"
            " VALUES ('Manga', ?, 'false')",
            (nickel.ONBOARD + "eigen/boek.epub",),
        )
        verbinding.commit()

        rapport = nickel.write_shelves(
            verbinding, {"Manga": [nickel.content_id_for("BookPal/Reeks/h1.cbz")]}
        )
        assert rapport.created == [], "de plank bestond al"

        inhoud = {
            rij[0] for rij in verbinding.execute("SELECT ContentId FROM ShelfContent").fetchall()
        }
        assert nickel.ONBOARD + "eigen/boek.epub" in inhoud
        assert len(inhoud) == 2

    def test_a_book_nickel_does_not_know_yet_is_reported_not_dropped(self, tmp_path: Path):
        """Nickel bouwt zijn lijst pas op ná het loskoppelen."""
        verbinding = self._verbinding(tmp_path, [])
        rapport = nickel.write_shelves(
            verbinding, {"Manga": [nickel.content_id_for("BookPal/Reeks/h1.cbz")]}
        )
        assert rapport.added == 0
        assert len(rapport.not_imported) == 1


def _reeks(session: Session, tmp_path: Path, aantal: int, naam: str = "Reeks") -> Series:
    root = LibraryRoot(name=naam, path=str(tmp_path / f"lib-{naam}"))
    session.add(root)
    session.flush()
    (tmp_path / f"lib-{naam}").mkdir(parents=True, exist_ok=True)
    series = Series(title=naam, sort_title=naam.lower())
    session.add(series)
    session.flush()
    for index in range(aantal):
        pad = tmp_path / f"lib-{naam}" / f"{index + 1:02d}.cbz"
        pad.write_bytes(b"cbz" * 100)
        bestand = File(
            library_root_id=root.id,
            path=str(pad),
            size=pad.stat().st_size,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(bestand)
        session.flush()
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title=f"Hoofdstuk {index + 1}",
                number=str(index + 1),
                sort_number=float(index + 1),
                page_count=20,
                file_id=bestand.id,
            )
        )
    session.flush()
    return series


class TestWhatGoesToTheDevice:
    def test_only_a_window_of_what_you_are_about_to_read(self, session: Session, tmp_path: Path):
        """Een serie van 700 hoofdstukken past niet op een Kobo."""
        series = _reeks(session, tmp_path, 10)
        session.commit()

        gepland = files.plan(session, current_user(session), [series.id], ahead=3)
        assert [item.title for item in gepland] == [
            "Hoofdstuk 1",
            "Hoofdstuk 2",
            "Hoofdstuk 3",
        ]

    def test_the_window_moves_along_with_what_you_finished(self, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 10)
        boeken = sorted(series.books, key=lambda b: b.sort_number)
        for boek in boeken[:4]:
            session.add(
                Progress(
                    user_id=current_user(session).id,
                    book_id=boek.id,
                    percent=100.0,
                    finished=True,
                )
            )
        session.commit()

        gepland = files.plan(session, current_user(session), [series.id], ahead=2)
        assert [item.title for item in gepland] == ["Hoofdstuk 5", "Hoofdstuk 6"]

    def test_the_name_keeps_reading_order(self, session: Session, tmp_path: Path):
        """Nickel sorteert op titel; zonder voorvoegsel staat 10 tussen 1 en 2."""
        series = _reeks(session, tmp_path, 12)
        session.commit()

        gepland = files.plan(session, current_user(session), [series.id], ahead=12)
        namen = [Path(item.relative).name for item in gepland]
        assert namen == sorted(namen)


class TestCopyingToTheDevice:
    def test_files_land_on_the_device(self, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 3)
        session.commit()
        mount = _kobo(tmp_path)

        gepland = files.plan(session, current_user(session), [series.id], ahead=2)
        rapport = files.export(mount, gepland)

        assert rapport.copied == 2
        assert len(list((mount / "BookPal" / "Reeks").glob("*.cbz"))) == 2

    def test_a_second_run_copies_nothing_new(self, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 3)
        session.commit()
        mount = _kobo(tmp_path)
        gepland = files.plan(session, current_user(session), [series.id], ahead=2)

        files.export(mount, gepland)
        tweede = files.export(mount, gepland)
        assert tweede.copied == 0
        assert tweede.skipped == 2

    def test_what_falls_out_of_the_window_is_cleaned_up(self, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 5)
        session.commit()
        mount = _kobo(tmp_path)

        files.export(mount, files.plan(session, current_user(session), [series.id], ahead=3))
        boeken = sorted(series.books, key=lambda b: b.sort_number)
        for boek in boeken[:2]:
            session.add(
                Progress(
                    user_id=current_user(session).id,
                    book_id=boek.id,
                    percent=100.0,
                    finished=True,
                )
            )
        session.commit()

        rapport = files.export(
            mount, files.plan(session, current_user(session), [series.id], ahead=3)
        )
        assert rapport.removed == 2
        namen = sorted(p.name for p in (mount / "BookPal" / "Reeks").glob("*.cbz"))
        assert len(namen) == 3

    def test_your_own_books_on_the_device_are_never_touched(self, session: Session, tmp_path: Path):
        """Opruimen blijft binnen onze eigen map."""
        series = _reeks(session, tmp_path, 2)
        session.commit()
        mount = _kobo(tmp_path)
        eigen = mount / "mijn boeken"
        eigen.mkdir()
        (eigen / "iets van mij.epub").write_bytes(b"van mij")

        files.export(mount, files.plan(session, current_user(session), [series.id], ahead=1))
        assert (eigen / "iets van mij.epub").read_bytes() == b"van mij"

    def test_an_interrupted_copy_leaves_no_half_book(self, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 1)
        session.commit()
        mount = _kobo(tmp_path)
        gepland = files.plan(session, current_user(session), [series.id], ahead=1)

        files.export(mount, gepland)
        halve = list((mount / "BookPal" / "Reeks").glob(".*deel"))
        assert halve == []


class TestProgressComingBack:
    def test_reading_on_the_kobo_counts_here(self, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 2)
        session.commit()
        gepland = files.plan(session, current_user(session), [series.id], ahead=1)
        files.remember(session, gepland)

        bijgewerkt = files.progress_back(
            session, current_user(session), {gepland[0].relative: (60, 1)}
        )
        assert bijgewerkt == 1

        row = session.query(Progress).one()
        assert row.percent == 60.0
        assert row.device == "kobo"

    def test_a_finished_book_lands_as_finished(self, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 2)
        session.commit()
        gepland = files.plan(session, current_user(session), [series.id], ahead=1)
        files.remember(session, gepland)

        files.progress_back(session, current_user(session), {gepland[0].relative: (100, 2)})
        assert session.query(Progress).one().finished is True

    def test_an_older_stand_never_pulls_you_back(self, session: Session, tmp_path: Path):
        """Een Kobo die een week in de la lag mag je niet terugzetten."""
        series = _reeks(session, tmp_path, 2)
        boek = sorted(series.books, key=lambda b: b.sort_number)[0]
        session.add(
            Progress(
                user_id=current_user(session).id, book_id=boek.id, percent=80.0, finished=False
            )
        )
        session.commit()
        gepland = files.plan(session, current_user(session), [series.id], ahead=1)
        files.remember(session, gepland)

        bijgewerkt = files.progress_back(
            session, current_user(session), {gepland[0].relative: (20, 1)}
        )
        assert bijgewerkt == 0
        assert session.query(Progress).one().percent == 80.0

    def test_a_book_we_never_put_there_is_ignored(self, session: Session, tmp_path: Path):
        _reeks(session, tmp_path, 1)
        session.commit()
        bijgewerkt = files.progress_back(
            session, current_user(session), {"iets/anders.epub": (50, 1)}
        )
        assert bijgewerkt == 0


class TestTheApi:
    def test_without_a_device_the_status_says_so(self, client):
        body = client.get("/api/kobo/status").json()
        assert body["connected"] is False
        assert body["mount"] is None
        assert body["dry_run"] is True, "een proefronde is de veilige standaard"

    def test_settings_stick(self, client, tmp_path: Path):
        mount = _kobo(tmp_path)
        body = client.put(
            "/api/kobo/settings",
            json={"mount": str(mount), "ahead": 5, "series_ids": [1, 2]},
        ).json()
        assert body["connected"] is True
        assert body["ahead"] == 5
        assert client.get("/api/kobo/status").json()["series_ids"] == [1, 2]

    def test_a_dry_run_touches_nothing(self, client, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 3)
        session.commit()
        mount = _kobo(tmp_path)
        client.put(
            "/api/kobo/settings",
            json={"mount": str(mount), "series_ids": [series.id], "ahead": 2},
        )

        body = client.post("/api/kobo/sync").json()
        assert body["dry_run"] is True
        assert body["planned"] == 2
        assert body["copied"] == 0
        assert not (mount / "BookPal").exists()

    def test_a_real_run_copies_and_makes_shelves(self, client, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 2)
        session.commit()
        mount = _kobo(tmp_path)
        client.put(
            "/api/kobo/settings",
            json={
                "mount": str(mount),
                "series_ids": [series.id],
                "ahead": 2,
                "dry_run": False,
            },
        )

        eerste = client.post("/api/kobo/sync").json()
        assert eerste["copied"] == 2
        assert eerste["backup"] is not None, "nooit schrijven zonder kopie"
        # Nickel kent de bestanden nog niet; dat hoort een melding te zijn.
        assert eerste["not_imported"] == 2
        assert eerste["shelves_created"] == ["Reeks"], "de plank alvast, de inhoud volgt"
        assert any("Koppel hem los" in melding for melding in eerste["notes"])

    def test_after_nickel_imported_them_the_shelf_fills(
        self, client, session: Session, tmp_path: Path
    ):
        series = _reeks(session, tmp_path, 2)
        session.commit()
        mount = _kobo(tmp_path)
        client.put(
            "/api/kobo/settings",
            json={
                "mount": str(mount),
                "series_ids": [series.id],
                "ahead": 2,
                "dry_run": False,
            },
        )
        client.post("/api/kobo/sync")

        # Doe alsof het apparaat losgekoppeld is geweest en heeft ingelezen.
        paden = [str(pad.relative_to(mount)) for pad in (mount / "BookPal").rglob("*.cbz")]
        verbinding = sqlite3.connect(mount / ".kobo" / "KoboReader.sqlite")
        for pad in paden:
            verbinding.execute(
                "INSERT INTO content (ContentID, ContentType, Title, ___PercentRead, ReadStatus)"
                " VALUES (?, 6, ?, 0, 0)",
                (nickel.ONBOARD + pad, Path(pad).stem),
            )
        verbinding.commit()
        verbinding.close()

        tweede = client.post("/api/kobo/sync").json()
        assert tweede["shelf_entries"] == 2
        # De plank zelf bestond al vanaf de eerste ronde; die wordt nu gevuld.
        assert tweede["shelves_created"] == []
        assert tweede["not_imported"] == 0

    def test_a_missing_device_is_a_clear_409(self, client, tmp_path: Path):
        client.put("/api/kobo/settings", json={"mount": str(tmp_path / "weg"), "dry_run": False})
        response = client.post("/api/kobo/sync")
        assert response.status_code == 409
        assert "niet gekoppeld" in response.json()["detail"]

    def test_the_plan_can_be_seen_without_syncing(self, client, session: Session, tmp_path: Path):
        series = _reeks(session, tmp_path, 5)
        session.commit()
        client.put("/api/kobo/settings", json={"series_ids": [series.id], "ahead": 2})

        body = client.get("/api/kobo/plan").json()
        assert [item["title"] for item in body] == ["Hoofdstuk 1", "Hoofdstuk 2"]
