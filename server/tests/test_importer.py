"""Een gevolgde serie als gewone bestanden in je eigen mappen zetten.

Dit is de enige plek waar BookPal in je collectie schrijft, dus de nadruk ligt
op wat er níet mag gebeuren: niets overschrijven, niets weggooien.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from bookpal.models import Book, BookKind, File, LibraryRoot, Series
from bookpal.sources.base import SourceError
from bookpal.sources.importer import (
    check_writable,
    import_series,
    target_dir,
    target_name,
)
from tests.conftest import make_root


class FakeSource:
    """Doet alsof hij hoofdstukken ophaalt, zonder netwerk."""

    type = "nep"

    def __init__(self) -> None:
        self.gedownload: list[int] = []


def _series_with_files(
    session: Session, tmp_path: Path, count: int = 2
) -> tuple[Series, LibraryRoot]:
    downloads = make_root(session, tmp_path / "downloads", name="Downloads")
    Path(downloads.path).mkdir(parents=True, exist_ok=True)
    series = Series(title="Shinya Shokudo", sort_title="shinya", library_root_id=downloads.id)
    session.add(series)
    session.flush()

    for index in range(count):
        source_file = Path(downloads.path) / f"hoofdstuk-{index}.cbz"
        source_file.write_bytes(b"cbz-inhoud")
        stat = source_file.stat()
        file_row = File(
            library_root_id=downloads.id,
            path=str(source_file),
            size=stat.st_size,
            mtime=stat.st_mtime,
            extension=".cbz",
        )
        session.add(file_row)
        session.flush()
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title=f"Deel {index + 1}",
                number=str(index + 1),
                sort_number=float(index + 1),
                file_id=file_row.id,
                source_ref=f"ref-{index}",
            )
        )
    session.flush()
    return series, downloads


class TestNaming:
    def test_the_folder_is_named_after_the_series(self, session: Session, tmp_path: Path):
        root = make_root(session, tmp_path / "manga", name="Manga")
        series = Series(title="Shinya Shokudo", sort_title="s")
        assert target_dir(root, series).name == "Shinya Shokudo"

    def test_unsafe_characters_are_stripped_from_the_folder(self, session: Session, tmp_path: Path):
        root = make_root(session, tmp_path / "manga", name="Manga")
        series = Series(title='Hij/Zij: "raar"', sort_title="h")
        assert "/" not in target_dir(root, series).name

    def test_numbers_get_leading_zeroes_so_a_folder_sorts(self, session: Session):
        series = Series(title="Reeks", sort_title="r")
        book = Book(series_id=1, kind=BookKind.COMIC, title="Deel", number="7")
        assert "0007" in target_name(series, book)

    def test_a_non_numeric_chapter_is_left_alone(self, session: Session):
        series = Series(title="Reeks", sort_title="r")
        book = Book(series_id=1, kind=BookKind.COMIC, title="Extra", number="Extra")
        assert "Extra" in target_name(series, book)

    def test_the_volume_is_included_when_there_is_one(self, session: Session):
        series = Series(title="Reeks", sort_title="r")
        book = Book(series_id=1, kind=BookKind.COMIC, title="Deel", number="3", volume="2")
        assert "v2" in target_name(series, book)


class TestWritable:
    def test_a_missing_folder_is_a_clear_error(self, session: Session, tmp_path: Path):
        root = LibraryRoot(name="Weg", path=str(tmp_path / "bestaat-niet"))
        with pytest.raises(SourceError, match="bestaat niet"):
            check_writable(root)

    def test_a_read_only_folder_names_the_likely_cause(self, session: Session, tmp_path: Path):
        """Read-only aangekoppeld is de gangbare oorzaak; dat hoort in de
        melding te staan in plaats van een kale OSError."""
        folder = tmp_path / "alleenlezen"
        folder.mkdir()
        folder.chmod(0o500)
        root = LibraryRoot(name="RO", path=str(folder))
        try:
            with pytest.raises(SourceError, match=":ro"):
                check_writable(root)
        finally:
            folder.chmod(0o700)

    def test_it_leaves_no_probe_file_behind(self, session: Session, tmp_path: Path):
        folder = tmp_path / "schrijfbaar"
        folder.mkdir()
        check_writable(LibraryRoot(name="OK", path=str(folder)))
        assert list(folder.iterdir()) == []


class TestImport:
    def test_files_move_into_the_library(self, session: Session, tmp_path: Path):
        series, _ = _series_with_files(session, tmp_path, count=2)
        target = make_root(session, tmp_path / "manga", name="Manga")
        Path(target.path).mkdir(parents=True, exist_ok=True)

        report = import_series(session, FakeSource(), series, target, download_missing=False)

        assert report.moved == 2
        folder = Path(target.path) / "Shinya Shokudo"
        assert len(list(folder.glob("*.cbz"))) == 2

    def test_the_file_row_follows_along(self, session: Session, tmp_path: Path):
        """Zonder dit zou een scan een tweede exemplaar naast het oude maken."""
        series, _downloads = _series_with_files(session, tmp_path, count=1)
        target = make_root(session, tmp_path / "manga", name="Manga")
        Path(target.path).mkdir(parents=True, exist_ok=True)

        import_series(session, FakeSource(), series, target, download_missing=False)

        book = session.scalars(session.query(Book).filter_by(series_id=series.id).statement).first()
        assert book is not None
        file_row = session.get(File, book.file_id)
        assert file_row is not None
        assert file_row.library_root_id == target.id
        assert Path(file_row.path).parent.name == "Shinya Shokudo"
        assert Path(file_row.path).is_file()

    def test_the_original_is_gone_after_moving(self, session: Session, tmp_path: Path):
        series, downloads = _series_with_files(session, tmp_path, count=1)
        origineel = next(Path(downloads.path).glob("*.cbz"))
        target = make_root(session, tmp_path / "manga", name="Manga")
        Path(target.path).mkdir(parents=True, exist_ok=True)

        import_series(session, FakeSource(), series, target, download_missing=False)
        assert not origineel.exists()

    def test_an_existing_file_is_never_overwritten(self, session: Session, tmp_path: Path):
        """Staat er al iets, dan is dat waarschijnlijk van jou."""
        series, _ = _series_with_files(session, tmp_path, count=1)
        target = make_root(session, tmp_path / "manga", name="Manga")
        folder = Path(target.path) / "Shinya Shokudo"
        folder.mkdir(parents=True, exist_ok=True)

        book = session.scalars(session.query(Book).filter_by(series_id=series.id).statement).first()
        assert book is not None
        bestaand = folder / target_name(series, book)
        bestaand.write_bytes(b"van mij")

        report = import_series(session, FakeSource(), series, target, download_missing=False)
        assert report.moved == 0
        assert report.skipped == 1
        assert bestaand.read_bytes() == b"van mij"

    def test_the_series_moves_to_the_new_root(self, session: Session, tmp_path: Path):
        series, _ = _series_with_files(session, tmp_path, count=1)
        target = make_root(session, tmp_path / "manga", name="Manga")
        Path(target.path).mkdir(parents=True, exist_ok=True)

        import_series(session, FakeSource(), series, target, download_missing=False)
        assert series.library_root_id == target.id
        assert series.folder_path == "Shinya Shokudo"

    def test_a_temporary_download_becomes_permanent(self, session: Session, tmp_path: Path):
        """Na importeren mag de TTL het bestand niet alsnog weghalen."""
        from datetime import UTC, datetime

        series, _ = _series_with_files(session, tmp_path, count=1)
        book = session.scalars(session.query(Book).filter_by(series_id=series.id).statement).first()
        assert book is not None
        book.expires_at = datetime(2030, 1, 1, tzinfo=UTC)
        session.flush()

        target = make_root(session, tmp_path / "manga", name="Manga")
        Path(target.path).mkdir(parents=True, exist_ok=True)
        import_series(session, FakeSource(), series, target, download_missing=False)

        session.refresh(book)
        assert book.expires_at is None

    def test_a_missing_source_file_is_skipped_not_fatal(self, session: Session, tmp_path: Path):
        series, downloads = _series_with_files(session, tmp_path, count=2)
        next(Path(downloads.path).glob("*.cbz")).unlink()
        target = make_root(session, tmp_path / "manga", name="Manga")
        Path(target.path).mkdir(parents=True, exist_ok=True)

        report = import_series(session, FakeSource(), series, target, download_missing=False)
        assert report.moved == 1
        assert report.skipped == 1


class TestImportingMakesItYours:
    """Een vooruit opgehaald hoofdstuk is cache, geen eigen bestand.

    Het staat er zolang het handig is en mag daarna weg. Importeren is precies
    de handeling die er een eigen bestand van maakt — pas dán hoort het bij
    "Eigen bestanden".
    """

    def _opzet(self, session: Session, tmp_path: Path):
        from bookpal.models import Edition, Source, Subscription

        bron = Source(type="mangadex", name="MD")
        session.add(bron)
        session.flush()
        series = Series(title="Reeks", sort_title="reeks", source_id=bron.id)
        session.add(series)
        session.flush()
        abo = Subscription(source_id=bron.id, series_id=series.id)
        session.add(abo)
        session.flush()
        uitgave = Edition(series_id=series.id, name="Reeks via MD", rank=0, subscription_id=abo.id)
        session.add(uitgave)
        session.flush()

        from tests.conftest import make_root

        cache = tmp_path / "cache"
        cache.mkdir()
        cache_root = make_root(session, cache, name="Downloads")
        session.flush()
        pad = cache / "h1.cbz"
        pad.write_bytes(b"PK\x03\x04nep")
        bestand = File(
            library_root_id=cache_root.id,
            path=str(pad),
            size=pad.stat().st_size,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(bestand)
        session.flush()
        boek = Book(
            series_id=series.id,
            kind=BookKind.COMIC,
            title="Hoofdstuk 1",
            number="1",
            sort_number=1.0,
            file_id=bestand.id,
            source_id=bron.id,
            source_ref="abc",
            edition_id=uitgave.id,
        )
        session.add(boek)
        session.flush()
        return series, boek, uitgave

    def test_a_cached_chapter_stays_with_its_subscription(self, session: Session, tmp_path: Path):
        _series, boek, uitgave = self._opzet(session, tmp_path)
        assert boek.edition_id == uitgave.id, "vooruit opgehaald is nog niet van jou"

    def test_importing_moves_it_to_your_own_files(self, session: Session, tmp_path: Path):
        from bookpal.library import editions
        from bookpal.sources.importer import _move
        from tests.conftest import make_root

        series, boek, uitgave = self._opzet(session, tmp_path)
        doel_map = tmp_path / "bibliotheek"
        doel_map.mkdir()
        root = make_root(session, doel_map, name="Strips")
        session.flush()

        verplaatst = _move(session, boek, doel_map / "Hoofdstuk 1.cbz", root)
        session.flush()

        assert verplaatst is True
        assert boek.edition_id != uitgave.id
        eigen = editions.for_local_files(session, series)
        assert boek.edition_id == eigen.id
