"""Internet Archive als tweede bron.

Wat hier vooral vastligt is het kiezen: één item bevat dezelfde inhoud vaak vijf
keer, in verschillende vormen. Zonder die keuze wordt elk deel vijf keer een
hoofdstuk.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bookpal.sources.archiveorg import ArchiveOrgSource
from bookpal.sources.base import SourceError

ITEM = "manga_Shinya_Shokudo"

_FILES = [
    {"name": "Shinya Shokudou - v01 c01-14.cbz", "size": "48000000", "format": "Comic Book ZIP"},
    {"name": "Shinya Shokudou - v01 c01-14.epub", "size": "37000000", "format": "EPUB"},
    {"name": "Shinya Shokudou - v01 c01-14.pdf", "size": "5000000", "format": "Text PDF"},
    {"name": "Shinya Shokudou - v01 c01-14_jp2.zip", "size": "38000000", "format": "JP2"},
    {"name": "Shinya Shokudou - v01 c01-14_lcp.epub", "size": "38000000", "format": "LCP"},
    {"name": "Shinya Shokudou - v02 c15-29.cbz", "size": "56000000", "format": "Comic Book ZIP"},
    {"name": "leesmij.txt", "size": "100", "format": "Text"},
]


def _bron(handler=None) -> ArchiveOrgSource:
    def standaard(request: httpx.Request) -> httpx.Response:
        pad = request.url.path
        if pad == "/advancedsearch.php":
            return httpx.Response(
                200,
                json={
                    "response": {
                        "numFound": 1,
                        "docs": [
                            {
                                "identifier": ITEM,
                                "title": "MANGA: Shinya Shokudo",
                                "creator": ["Abe Yarou"],
                                "year": "2007",
                                "language": ["jpn"],
                            }
                        ],
                    }
                },
            )
        if pad == f"/metadata/{ITEM}":
            return httpx.Response(
                200,
                json={
                    "metadata": {"title": "MANGA: Shinya Shokudo", "language": ["jpn"]},
                    "files": _FILES,
                },
            )
        if pad.startswith("/download/"):
            return httpx.Response(200, content=b"cbz-inhoud")
        return httpx.Response(404, json={})

    return ArchiveOrgSource(
        client=httpx.Client(
            base_url="https://archive.org",
            transport=httpx.MockTransport(handler or standaard),
            follow_redirects=True,
        ),
        rate=1000.0,
    )


class TestSearching:
    def test_a_hit_has_what_you_need_to_judge_it(self):
        [treffer] = _bron().search("shinya shokudo")
        assert treffer.ref == ITEM
        assert treffer.title == "MANGA: Shinya Shokudo"
        assert treffer.year == 2007
        assert treffer.url == f"https://archive.org/details/{ITEM}"
        assert treffer.cover_url is not None
        assert treffer.authors == ["Abe Yarou"]
        assert treffer.languages == ["ja"]

    def test_only_texts_are_searched(self):
        """Dezelfde zoekterm levert anders ook de tv-serie op."""
        gezien: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            gezien.append(str(request.url))
            return httpx.Response(200, json={"response": {"docs": []}})

        _bron(handler).search("shinya shokudo")
        assert "mediatype%3Atexts" in gezien[0] or "mediatype:texts" in gezien[0]

    def test_the_language_is_translated_to_what_the_archive_uses(self):
        gezien: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            gezien.append(str(request.url))
            return httpx.Response(200, json={"response": {"docs": []}})

        _bron(handler).search("iets", language="ja")
        assert "jpn" in gezien[0]


class TestChapters:
    def test_one_chapter_per_volume_not_per_format(self):
        """Dezelfde inhoud staat er als cbz, epub, pdf, jp2 en lcp in."""
        delen = _bron().chapters(ITEM)
        assert len(delen) == 2

    def test_the_cbz_wins_from_the_epub(self):
        """Een cbz is pagina's als beeld — precies waar de lezer op gebouwd is."""
        delen = _bron().chapters(ITEM)
        assert all(deel.ref.endswith(".cbz") for deel in delen)

    def test_the_archive_own_scan_formats_are_skipped(self):
        refs = [deel.ref for deel in _bron().chapters(ITEM)]
        assert not any("_jp2" in ref or "_lcp" in ref for ref in refs)

    def test_the_volume_number_comes_from_the_filename(self):
        delen = _bron().chapters(ITEM)
        assert [deel.volume for deel in delen] == ["01", "02"]

    def test_the_filename_is_the_title(self):
        """De parser houdt van "v01 c01-14" alleen "14" over; dat zegt minder."""
        [eerste, _tweede] = _bron().chapters(ITEM)
        assert eerste.title == "Shinya Shokudou - v01 c01-14"

    def test_a_chapter_ref_points_at_one_file(self):
        """Een ref moet in zijn eentje op te halen zijn."""
        [eerste, _tweede] = _bron().chapters(ITEM)
        assert eerste.ref.startswith(f"{ITEM}/")


class TestDownloading:
    def test_a_volume_lands_on_disk(self, tmp_path: Path):
        doel = tmp_path / "v01.cbz"
        _bron().download(f"{ITEM}/Shinya Shokudou - v01 c01-14.cbz", doel)
        assert doel.read_bytes() == b"cbz-inhoud"

    def test_nothing_half_is_left_behind(self, tmp_path: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        doel = tmp_path / "v01.cbz"
        with pytest.raises(SourceError):
            _bron(handler).download(f"{ITEM}/iets.cbz", doel)
        assert list(tmp_path.iterdir()) == []

    def test_a_ref_without_a_file_is_refused(self, tmp_path: Path):
        with pytest.raises(SourceError, match="bestand"):
            _bron().download(ITEM, tmp_path / "x.cbz")


class TestWhatItCannotDo:
    def test_there_are_no_loose_page_urls(self):
        """Je haalt hier hele bestanden op; dat hoort de bron ook te zeggen."""
        with pytest.raises(SourceError, match="hele bestanden"):
            _bron().page_urls(f"{ITEM}/iets.cbz")


class TestLendingItems:
    """Het Internet Archive scant boeken voor bibliotheken en leent ze uit.

    Die staan gewoon in de zoekresultaten, maar de bestanden zijn versleuteld.
    Zonder onderscheid abonneer je je op iets wat nooit binnenkomt.
    """

    def _uitleen(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/advancedsearch.php":
                return httpx.Response(
                    200,
                    json={
                        "response": {
                            "docs": [
                                {
                                    "identifier": "oishinbo220000kari",
                                    "title": "Oishinbo. 22",
                                    "language": ["jpn"],
                                    "collection": ["internetarchivebooks", "inlibrary"],
                                }
                            ]
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "metadata": {
                        "title": "Oishinbo. 22",
                        "collection": ["internetarchivebooks", "inlibrary"],
                        "access-restricted-item": "true",
                    },
                    "files": [
                        {"name": "oishinbo220000kari_encrypted.pdf", "format": "PDF"},
                        {"name": "oishinbo220000kari_lcp.epub", "format": "LCP"},
                    ],
                },
            )

        return _bron(handler)

    def test_a_lending_item_says_so_in_the_search(self):
        [treffer] = self._uitleen().search("oishinbo")
        assert treffer.status == "alleen te leen"

    def test_fetching_it_is_refused_with_the_reason(self):
        with pytest.raises(SourceError, match="alleen te leen"):
            self._uitleen().chapters("oishinbo220000kari")

    def test_an_ordinary_item_is_not_marked(self):
        [treffer] = _bron().search("shinya shokudo")
        assert treffer.status is None
