from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.library.scanner import ScanAborted, scan_all, scan_root
from bookpal.metadata.filename import normalise_number, parse_filename, sort_title
from bookpal.models import Book, BookKind, File, OriginRegion, OriginSource, Series
from tests.conftest import make_root
from tests.fixtures import comicinfo_xml, make_cb7, make_cbz, make_epub, make_pdf


class TestFilenameParsing:
    @pytest.mark.parametrize(
        ("stem", "series", "number"),
        [
            ("De Testreeks 01", "De Testreeks", "01"),
            ("Storm #12", "Storm", "12"),
            ("Blake en Mortimer - 012 - Het Zwaard", "Blake en Mortimer", "012"),
            ("One Piece c1045", "One Piece", "1045"),
            ("Naruto ch. 700", "Naruto", "700"),
            ("Suske en Wiske 305 (2010)", "Suske en Wiske", "305"),
            ("Berserk v41", "Berserk", "41"),
            ("Thorgal T05", "Thorgal", "05"),
        ],
    )
    def test_series_and_number(self, stem: str, series: str, number: str):
        parsed = parse_filename(stem)
        assert parsed.series == series
        assert parsed.number == number

    def test_scanlator_tags_are_stripped(self):
        parsed = parse_filename("Vinland Saga c001 [Groep] (2019)")
        assert parsed.series == "Vinland Saga"
        assert parsed.number == "001"

    def test_title_without_number(self):
        parsed = parse_filename("Een Losstaand Verhaal")
        assert parsed.series == "Een Losstaand Verhaal"
        assert parsed.number is None

    def test_decimal_chapter(self):
        parsed = parse_filename("Bleach c012.5")
        assert parsed.number == "012.5"
        assert normalise_number("012.5") == 12.5

    def test_missing_number_sorts_last(self):
        assert normalise_number(None) == float("inf")

    def test_sort_title_ignores_articles(self):
        assert sort_title("De Testreeks") == "Testreeks"
        assert sort_title("The Sandman") == "Sandman"
        assert sort_title("Blake en Mortimer") == "Blake en Mortimer"


class TestScanning:
    def test_indexes_all_supported_formats(self, session: Session, library_root: Path):
        make_cbz(library_root / "strips" / "Reeks 01.cbz", pages=5)
        make_cb7(library_root / "manga" / "Tesuto 01.cb7", pages=3)
        make_epub(library_root / "boeken" / "Boek.epub")
        make_pdf(library_root / "boeken" / "Document.pdf")
        root = make_root(session, library_root)

        result = scan_root(session, root)

        assert result.added == 4
        assert result.errors == []
        kinds = {book.kind for book in session.scalars(select(Book))}
        assert kinds == {BookKind.COMIC, BookKind.EPUB, BookKind.PDF}

    def test_page_count_is_stored(self, session: Session, library_root: Path):
        make_cbz(library_root / "Reeks 01.cbz", pages=7)
        root = make_root(session, library_root)
        scan_root(session, root)
        book = session.scalar(select(Book))
        assert book is not None
        assert book.page_count == 7

    def test_second_scan_changes_nothing(self, session: Session, library_root: Path):
        """Idempotentie: dit is wat een rescan op een grote collectie snel houdt."""
        make_cbz(library_root / "Reeks 01.cbz", pages=3)
        make_cbz(library_root / "Reeks 02.cbz", pages=3)
        root = make_root(session, library_root)

        first = scan_root(session, root)
        second = scan_root(session, root)

        assert first.added == 2
        assert second.added == 0
        assert second.updated == 0
        assert second.removed == 0
        assert second.unchanged == 2
        assert second.changed is False

    def test_changed_file_is_reindexed(self, session: Session, library_root: Path):
        path = make_cbz(library_root / "Reeks 01.cbz", pages=3)
        root = make_root(session, library_root)
        scan_root(session, root)

        make_cbz(path, pages=6)
        result = scan_root(session, root)

        assert result.updated == 1
        book = session.scalar(select(Book))
        assert book is not None
        assert book.page_count == 6

    def test_force_rereads_everything(self, session: Session, library_root: Path):
        make_cbz(library_root / "Reeks 01.cbz", pages=3)
        root = make_root(session, library_root)
        scan_root(session, root)
        result = scan_root(session, root, force=True)
        assert result.updated == 1
        assert result.unchanged == 0

    def test_deleted_file_is_removed(self, session: Session, library_root: Path):
        path = make_cbz(library_root / "Reeks 01.cbz", pages=3)
        make_cbz(library_root / "Reeks 02.cbz", pages=3)
        root = make_root(session, library_root)
        scan_root(session, root)

        path.unlink()
        result = scan_root(session, root)

        assert result.removed == 1
        assert session.scalar(select(File).where(File.path == str(path))) is None
        assert len(session.scalars(select(Book)).all()) == 1

    def test_empty_series_is_pruned(self, session: Session, library_root: Path):
        path = make_cbz(library_root / "Reeks" / "Reeks 01.cbz", pages=2)
        root = make_root(session, library_root)
        scan_root(session, root)
        assert len(session.scalars(select(Series)).all()) == 1

        path.unlink()
        scan_root(session, root)
        assert session.scalars(select(Series)).all() == []

    def test_broken_file_does_not_stop_the_scan(self, session: Session, library_root: Path):
        make_cbz(library_root / "Goed 01.cbz", pages=2)
        (library_root / "Stuk 01.cbz").write_bytes(b"PK\x03\x04 dit is geen geldige zip")
        root = make_root(session, library_root)

        result = scan_root(session, root)

        assert result.added == 1
        assert len(result.errors) == 1
        assert "Stuk 01.cbz" in result.errors[0]

    def test_unmounted_nas_does_not_wipe_the_library(self, session: Session, library_root: Path):
        """Het scenario dat je collectie zou kunnen kosten: de share is even weg."""
        for index in range(6):
            make_cbz(library_root / f"Reeks {index + 1:02d}.cbz", pages=2)
        root = make_root(session, library_root)
        scan_root(session, root)
        assert len(session.scalars(select(File)).all()) == 6

        for path in library_root.glob("*.cbz"):
            path.unlink()

        with pytest.raises(ScanAborted, match="mount"):
            scan_root(session, root)
        # Niets verwijderd.
        assert len(session.scalars(select(File)).all()) == 6

    def test_missing_root_raises(self, session: Session, tmp_path: Path):
        root = make_root(session, tmp_path / "bestaat-niet")
        with pytest.raises(ScanAborted, match="niet bereikbaar"):
            scan_root(session, root)

    def test_scan_all_reports_per_root(self, session: Session, tmp_path: Path):
        good = tmp_path / "goed"
        good.mkdir()
        make_cbz(good / "Reeks 01.cbz", pages=2)
        make_root(session, good, name="Goed")
        make_root(session, tmp_path / "weg", name="Weg")

        results = scan_all(session)

        assert results["Goed"].added == 1
        assert results["Weg"].errors


class TestSeriesGrouping:
    def test_groups_by_comicinfo_series(self, session: Session, library_root: Path):
        make_cbz(
            library_root / "a.cbz", pages=2, comicinfo=comicinfo_xml(series="Storm", number="1")
        )
        make_cbz(
            library_root / "b.cbz", pages=2, comicinfo=comicinfo_xml(series="Storm", number="2")
        )
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalars(select(Series)).all()
        assert len(series) == 1
        assert series[0].title == "Storm"
        assert [book.number for book in series[0].books] == ["1", "2"]

    def test_groups_by_filename_when_no_metadata(self, session: Session, library_root: Path):
        make_cbz(library_root / "De Testreeks 01.cbz", pages=2)
        make_cbz(library_root / "De Testreeks 02.cbz", pages=2)
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalars(select(Series)).all()
        assert len(series) == 1
        assert series[0].title == "De Testreeks"
        assert series[0].sort_title == "Testreeks"

    def test_books_are_ordered_by_number(self, session: Session, library_root: Path):
        for number in ("10", "2", "1"):
            make_cbz(library_root / f"Reeks {number}.cbz", pages=1)
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalar(select(Series))
        assert series is not None
        assert [book.number for book in series.books] == ["1", "2", "10"]

    def test_sorts_by_volume_first_when_chapters_restart_per_volume(
        self, session: Session, library_root: Path
    ):
        """Chapter 1 bestaat in elk deel — zonder sort_volume komen die naast
        elkaar te staan in scanvolgorde in plaats van leesvolgorde. Precies
        wat er met de echte Crayon Shin-Chan-collectie misging."""
        folder = library_root / "Reeks"
        # Bewust niet in leesvolgorde aanmaken: de bug zat in aanname dat
        # scanvolgorde toevallig zou kloppen.
        for vol, ch in [("10", "1"), ("1", "2"), ("2", "1"), ("1", "1")]:
            make_cbz(
                folder / f"vol{vol}-ch{ch}.cbz",
                pages=1,
                comicinfo=comicinfo_xml(series="Reeks", number=ch, volume=vol),
            )
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalar(select(Series))
        assert series is not None
        volgorde = [(book.volume, book.number) for book in series.books]
        assert volgorde == [("1", "1"), ("1", "2"), ("2", "1"), ("10", "1")]

    def test_books_without_a_volume_still_sort_by_number(
        self, session: Session, library_root: Path
    ):
        """De meeste strips hebben geen 'deel' apart van het nummer; die
        mogen niet allemaal naar het einde van de reeks verdwijnen."""
        for number in ("3", "1", "2"):
            make_cbz(
                library_root / f"los-{number}.cbz",
                pages=1,
                comicinfo=comicinfo_xml(series="Los", number=number),
            )
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalar(select(Series))
        assert series is not None
        assert [book.number for book in series.books] == ["1", "2", "3"]

    def test_a_folder_holds_one_series_even_with_messy_filenames(
        self, session: Session, library_root: Path
    ):
        """De echte vorm waar dit op stukliep: de serietitel staat achteraan,
        achter de hoofdstuktitel. Ontleden van de naam maakt er dan van elk
        hoofdstuk een eigen reeks; de map weet het beter."""
        folder = library_root / "Crayon Shin-Chan"
        for stem in (
            "Vol.15 Ch.005.002 - Part 002 - Complicated Cases! - Crayon Shin-chan",
            "Vol.15 Ch.005.003 - Part 003 - Complicated Cases! - Crayon Shin-chan",
            "Vol.16 Ch.006.001 - Part 001 - A Love Letter - Crayon Shin-chan",
        ):
            make_cbz(folder / f"{stem}.cbz", pages=1)
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalars(select(Series)).all()
        assert len(series) == 1
        assert series[0].title == "Crayon Shin-Chan"
        assert len(series[0].books) == 3

    def test_comicinfo_still_wins_over_the_folder(self, session: Session, library_root: Path):
        make_cbz(
            library_root / "Verkeerde Mapnaam" / "deel 1.cbz",
            pages=1,
            comicinfo=comicinfo_xml(series="De Echte Reeks", number="1"),
        )
        root = make_root(session, library_root)
        scan_root(session, root)
        series = session.scalar(select(Series))
        assert series is not None
        assert series.title == "De Echte Reeks"

    def test_folder_becomes_series_as_last_resort(self, session: Session, library_root: Path):
        make_cbz(library_root / "Een Map" / "losse naam zonder nummer.cbz", pages=1)
        root = make_root(session, library_root)
        scan_root(session, root)
        series = session.scalar(select(Series))
        assert series is not None
        assert series.folder_path == "Een Map"


class TestAuthorsDuringScan:
    def test_writer_from_comicinfo_lands_on_the_series(
        self, session: Session, library_root: Path
    ):
        make_cbz(library_root / "a.cbz", pages=1, comicinfo=comicinfo_xml(series="Storm"))
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalar(select(Series))
        assert series is not None
        assert series.authors == ["Iemand Anders"]

    def test_authors_are_merged_not_overwritten(self, session: Session, library_root: Path):
        """Een serie heeft vaak een tekenaar naast een schrijver, en die staan
        zelden in hetzelfde deel — dus samenvoegen, niet vervangen."""
        make_cbz(library_root / "a.cbz", pages=1, comicinfo=comicinfo_xml(series="Storm"))
        make_cbz(
            library_root / "b.cbz",
            pages=1,
            comicinfo=comicinfo_xml(series="Storm", number="2").replace(
                b"<Writer>Iemand Anders</Writer>", b"<Writer>Nog Iemand</Writer>"
            ),
        )
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalar(select(Series))
        assert series is not None
        assert sorted(series.authors) == ["Iemand Anders", "Nog Iemand"]

    def test_rescanning_does_not_duplicate_authors(self, session: Session, library_root: Path):
        make_cbz(library_root / "a.cbz", pages=1, comicinfo=comicinfo_xml(series="Storm"))
        root = make_root(session, library_root)
        scan_root(session, root)
        scan_root(session, root, force=True)

        series = session.scalar(select(Series))
        assert series is not None
        assert series.authors == ["Iemand Anders"]


class TestOriginDuringScan:
    def test_publisher_from_comicinfo_sets_europe(self, session: Session, library_root: Path):
        make_cbz(
            library_root / "a.cbz",
            pages=1,
            comicinfo=comicinfo_xml(series="Storm", publisher="Dupuis"),
        )
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalar(select(Series))
        assert series is not None
        assert series.origin_region is OriginRegion.EUROPE
        assert series.origin_source is OriginSource.EMBEDDED

    def test_manga_flag_sets_japan_and_rtl(self, session: Session, library_root: Path):
        make_cbz(
            library_root / "b.cbz",
            pages=1,
            comicinfo=comicinfo_xml(series="Tesuto", manga="YesAndRightToLeft"),
        )
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalar(select(Series))
        book = session.scalar(select(Book))
        assert series is not None and book is not None
        assert series.origin_region is OriginRegion.JAPAN
        assert book.right_to_left is True

    def test_root_default_applies_when_file_says_nothing(
        self, session: Session, library_root: Path
    ):
        make_cbz(library_root / "c.cbz", pages=1)
        root = make_root(session, library_root, default_region=OriginRegion.JAPAN)
        scan_root(session, root)

        series = session.scalar(select(Series))
        assert series is not None
        assert series.origin_region is OriginRegion.JAPAN
        assert series.origin_source is OriginSource.ROOT_DEFAULT

    def test_manual_choice_survives_rescan(self, session: Session, library_root: Path):
        make_cbz(
            library_root / "d.cbz",
            pages=1,
            comicinfo=comicinfo_xml(series="Twijfelgeval", publisher="Shueisha"),
        )
        root = make_root(session, library_root)
        scan_root(session, root)

        series = session.scalar(select(Series))
        assert series is not None
        assert series.origin_region is OriginRegion.JAPAN

        # Jij weet beter: dit is een Europese uitgave.
        series.origin_region = OriginRegion.EUROPE
        series.origin_country = "be"
        series.origin_source = OriginSource.MANUAL
        session.flush()

        scan_root(session, root, force=True)
        session.refresh(series)
        assert series.origin_region is OriginRegion.EUROPE
        assert series.origin_source is OriginSource.MANUAL

    def test_tabs_can_separate_europe_from_japan(self, session: Session, tmp_path: Path):
        """De eigenlijke eis: strips uit Europa en manga uit Japan uit elkaar."""
        strips = tmp_path / "strips"
        manga = tmp_path / "manga"
        make_cbz(
            strips / "Storm 01.cbz",
            pages=1,
            comicinfo=comicinfo_xml(series="Storm", publisher="Dupuis"),
        )
        make_cbz(
            manga / "Tesuto 01.cbz",
            pages=1,
            comicinfo=comicinfo_xml(series="Tesuto", manga="YesAndRightToLeft"),
        )
        make_root(session, strips, name="Strips")
        make_root(session, manga, name="Manga", default_region=OriginRegion.JAPAN)
        scan_all(session)

        by_region = {
            series.origin_region: series.title for series in session.scalars(select(Series))
        }
        assert by_region[OriginRegion.EUROPE] == "Storm"
        assert by_region[OriginRegion.JAPAN] == "Tesuto"
