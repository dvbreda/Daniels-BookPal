from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from bookpal.formats import Format, detect_format, open_book
from bookpal.formats.base import UnsupportedOperation, natural_key
from bookpal.models import BookKind
from tests.fixtures import comicinfo_xml, make_cb7, make_cbz, make_epub, make_pdf


def test_natural_sort_puts_page_2_before_page_10():
    names = ["page10.png", "page2.png", "page1.png"]
    assert sorted(names, key=natural_key) == ["page1.png", "page2.png", "page10.png"]


class TestCbz:
    def test_reads_pages_in_natural_order(self, tmp_path: Path):
        path = make_cbz(tmp_path / "a.cbz", pages=12, shuffled_names=True)
        with open_book(path) as book:
            assert book.page_count() == 12
            assert book.kind is BookKind.COMIC
            # Pagina 2 moet de tweede kleur hebben, niet die van page10.
            assert book.get_page(1).data == book.get_page(1).data
            first = book.get_page(0)
            assert first.media_type == "image/png"
            assert first.data.startswith(b"\x89PNG")

    def test_ignores_macos_forks_and_non_images(self, tmp_path: Path):
        path = make_cbz(tmp_path / "b.cbz", pages=3)
        with open_book(path) as book:
            # 3 pagina's, ondanks __MACOSX en thumbs.db in het archief.
            assert book.page_count() == 3

    def test_reads_comicinfo(self, tmp_path: Path):
        path = make_cbz(
            tmp_path / "c.cbz",
            pages=2,
            comicinfo=comicinfo_xml(series="Storm", number="7", publisher="Dupuis", language="nl"),
        )
        with open_book(path) as book:
            meta = book.metadata()
        assert meta.series == "Storm"
        assert meta.number == "7"
        assert meta.publisher == "Dupuis"
        assert meta.language == "nl"
        assert "Avontuur" in meta.tags
        assert meta.authors == ["Iemand Anders"]

    def test_manga_flag_sets_right_to_left(self, tmp_path: Path):
        path = make_cbz(
            tmp_path / "d.cbz", pages=1, comicinfo=comicinfo_xml(manga="YesAndRightToLeft")
        )
        with open_book(path) as book:
            meta = book.metadata()
        assert meta.right_to_left is True
        assert meta.raw["Manga"] == "YesAndRightToLeft"

    def test_out_of_range_page_raises(self, tmp_path: Path):
        path = make_cbz(tmp_path / "e.cbz", pages=2)
        with open_book(path) as book, pytest.raises(IndexError):
            book.get_page(5)


class TestLibarchive:
    """Dekt de cbr-code; 7z deelt de volledige leesweg met rar."""

    def test_reads_pages(self, tmp_path: Path):
        path = make_cb7(tmp_path / "a.cb7", pages=4)
        with open_book(path) as book:
            assert book.page_count() == 4
            page = book.get_page(2)
            assert page.data.startswith(b"\x89PNG")
            assert page.media_type == "image/png"

    def test_reads_comicinfo(self, tmp_path: Path):
        path = make_cb7(tmp_path / "b.cb7", pages=2, comicinfo=comicinfo_xml(series="Tesuto"))
        with open_book(path) as book:
            assert book.metadata().series == "Tesuto"

    def test_extraction_is_reused_across_pages(self, tmp_path: Path):
        path = make_cb7(tmp_path / "c.cb7", pages=3)
        book = open_book(path)
        try:
            book.get_page(0)
            tempdir = book._tempdir  # type: ignore[attr-defined]
            assert tempdir is not None and tempdir.exists()
            book.get_page(2)
            assert book._tempdir is tempdir  # type: ignore[attr-defined]
        finally:
            book.close()
        assert not tempdir.exists()


class TestEpub:
    def test_metadata_and_spine(self, tmp_path: Path):
        path = make_epub(tmp_path / "a.epub", title="Duin", author="F. Herbert", chapters=4)
        with open_book(path) as book:
            assert book.kind is BookKind.EPUB
            meta = book.metadata()
            assert meta.title == "Duin"
            assert meta.authors == ["F. Herbert"]
            assert meta.language == "nl"
            assert meta.publisher == "Testuitgeverij"
            assert book.page_count() == 4

    def test_cover_is_found(self, tmp_path: Path):
        path = make_epub(tmp_path / "b.epub", with_cover=True)
        with open_book(path) as book:
            cover = book.cover()
        assert cover is not None
        assert cover.data.startswith(b"\x89PNG")

    def test_no_cover_returns_none(self, tmp_path: Path):
        path = make_epub(tmp_path / "c.epub", with_cover=False)
        with open_book(path) as book:
            assert book.cover() is None

    def test_toc(self, tmp_path: Path):
        path = make_epub(tmp_path / "d.epub", chapters=3)
        with open_book(path) as book:
            toc = book.toc()
        assert [entry.title for entry in toc] == ["Hoofdstuk 1", "Hoofdstuk 2", "Hoofdstuk 3"]

    def test_page_as_image_is_refused(self, tmp_path: Path):
        path = make_epub(tmp_path / "e.epub")
        with open_book(path) as book, pytest.raises(UnsupportedOperation):
            book.get_page(0)


class TestPdf:
    def test_pages_and_metadata(self, tmp_path: Path):
        path = make_pdf(tmp_path / "a.pdf", pages=3, title="Handleiding")
        with open_book(path) as book:
            assert book.kind is BookKind.PDF
            assert book.page_count() == 3
            assert book.metadata().title == "Handleiding"

    def test_target_width_controls_render_size(self, tmp_path: Path):
        from io import BytesIO

        from PIL import Image

        path = make_pdf(tmp_path / "b.pdf", pages=1)
        with open_book(path) as book:
            small = Image.open(BytesIO(book.get_page(0, target_width=200).data))
            large = Image.open(BytesIO(book.get_page(0, target_width=800).data))
        # Direct op de doelbreedte renderen in plaats van groot renderen en
        # daarna verkleinen — dat scheelt op een N100 echt tijd.
        assert small.width == pytest.approx(200, abs=2)
        assert large.width == pytest.approx(800, abs=2)


class TestFormatDetection:
    def test_detects_by_content(self, tmp_path: Path):
        assert detect_format(make_cbz(tmp_path / "a.cbz")) is Format.CBZ
        assert detect_format(make_cb7(tmp_path / "b.cb7")) is Format.CB7
        assert detect_format(make_epub(tmp_path / "c.epub")) is Format.EPUB
        assert detect_format(make_pdf(tmp_path / "d.pdf")) is Format.PDF

    def test_misnamed_cbr_that_is_really_a_zip(self, tmp_path: Path):
        """Komt in echte collecties constant voor."""
        path = make_cbz(tmp_path / "eigenlijk-een-zip.cbr", pages=3)
        assert detect_format(path) is Format.CBZ
        with open_book(path) as book:
            assert book.page_count() == 3

    def test_epub_is_not_mistaken_for_a_comic(self, tmp_path: Path):
        # Een epub is ook een zip; alleen de mimetype onderscheidt ze.
        path = make_epub(tmp_path / "boek.epub")
        assert detect_format(path) is Format.EPUB

    def test_unknown_file(self, tmp_path: Path):
        path = tmp_path / "aantekeningen.txt"
        path.write_text("geen boek")
        assert detect_format(path) is None
        with pytest.raises(UnsupportedOperation):
            open_book(path)

    def test_empty_zip_without_images(self, tmp_path: Path):
        path = tmp_path / "leeg.cbz"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", b"niets te zien")
        with open_book(path) as book:
            assert book.page_count() == 0
            assert book.cover() is None
