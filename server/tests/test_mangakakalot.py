"""De eerste bron zonder API, dus met eigen risico's.

Alles hier draait op vaste HTML in plaats van op het echte net: een test die
de site opvraagt faalt zodra jij in de trein zit, en zegt bovendien niets over
wat er gebeurt als de opmaak verandert. Dát laatste is juist het geval waar
deze bron van moet kunnen breken zonder stilletjes een leeg hoofdstuk op te
leveren, dus daar staan de meeste tests op.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import httpx
import pytest

from bookpal.sources.base import SourceError
from bookpal.sources.mangakakalot import MangaKakalotSource, _slug_uit

REEKS_HTML = """
<html><head>
<meta property="og:description" content="Hirayasumi Manga: Een man erft een huis."/>
<meta property="og:image" content="https://thumb.example/mn/hirayasumi.jpg"/>
</head><body>
<h1>Hirayasumi ; Хираясуми</h1>
<a href="https://mangakakalot.fun/chapter/hirayasumi/chapter-0">Hoofdstuk 0</a>
<a href="https://mangakakalot.fun/chapter/hirayasumi/chapter-2">Hoofdstuk 2</a>
<a href="https://mangakakalot.fun/chapter/hirayasumi/chapter-10">Hoofdstuk 10</a>
<a href="https://mangakakalot.fun/chapter/hirayasumi/chapter-9.5">Hoofdstuk 9.5</a>
<a href="/chapter/een-hele-andere-reeks/chapter-297">Uit de zijbalk</a>
<a href="/assets/vendors~chapter~home.chunk.js">Geen hoofdstuk</a>
</body></html>
"""

HOOFDSTUK_HTML = """
<html><body>
<img src="/logo.png"/>
<img src="https://imgx.example/hirayasumi/0/1.jpg"/>
<img src="https://imgx.example/hirayasumi/0/2.jpg"/>
<img src="https://imgx.example/hirayasumi/0/2.jpg"/>
</body></html>
"""


def _bron(routes: dict[str, httpx.Response]) -> MangaKakalotSource:
    """Een bron die vaste antwoorden krijgt in plaats van het echte net."""

    def afhandelen(verzoek: httpx.Request) -> httpx.Response:
        pad = verzoek.url.path
        if pad in routes:
            return routes[pad]
        return httpx.Response(404, text="niet gevonden")

    client = httpx.Client(
        base_url="https://mangakakalot.fun", transport=httpx.MockTransport(afhandelen)
    )
    # Hoog in plaats van uit: de limiter weigert nul, en zo wacht een test
    # nooit op een seconde die er in het echt wél hoort te zijn.
    return MangaKakalotSource(client=client, rate=10_000.0)


class TestSlug:
    def test_a_bare_slug_stays_what_it_is(self):
        assert _slug_uit("hirayasumi") == "hirayasumi"

    def test_a_pasted_series_url_gives_the_slug(self):
        """Je komt hier met een link, dus plakken hoort te werken."""
        assert _slug_uit("https://mangakakalot.fun/manga/hirayasumi") == "hirayasumi"
        assert _slug_uit("https://mangakakalot.fun/manga/hirayasumi/") == "hirayasumi"

    def test_a_chapter_url_also_gives_the_series(self):
        assert _slug_uit("https://mangakakalot.fun/chapter/hirayasumi/chapter-3") == "hirayasumi"

    def test_nonsense_is_refused_before_it_becomes_a_url(self):
        for poging in ["../../etc/passwd", "met spaties", "", "HOOFDLETTERS?"]:
            with pytest.raises(SourceError):
                _slug_uit(poging)


class TestDetail:
    def test_the_first_title_variant_wins(self):
        """De h1 stapelt alle talen achter elkaar; in een bibliotheek wil je er één."""
        bron = _bron({"/manga/hirayasumi": httpx.Response(200, text=REEKS_HTML)})
        assert bron.detail("hirayasumi").title == "Hirayasumi"

    def test_the_title_is_stripped_from_the_description(self):
        bron = _bron({"/manga/hirayasumi": httpx.Response(200, text=REEKS_HTML)})
        assert bron.detail("hirayasumi").description == "Een man erft een huis."

    def test_no_language_is_invented(self):
        """De site zegt het niet, dus raden we het niet — de herkomst-keten
        bouwt hierop verder en een verzonnen taal werkt daar door."""
        bron = _bron({"/manga/hirayasumi": httpx.Response(200, text=REEKS_HTML)})
        assert bron.detail("hirayasumi").languages == []

    def test_a_missing_series_is_an_error_and_not_an_empty_result(self):
        bron = _bron({})
        with pytest.raises(SourceError):
            bron.detail("bestaat-niet")

    def test_a_page_without_a_title_says_the_layout_changed(self):
        """Het geval waar het bij een scraper om draait: de site is er wel,
        maar ziet er anders uit."""
        bron = _bron(
            {"/manga/hirayasumi": httpx.Response(200, text="<html><body>hoi</body></html>")}
        )
        with pytest.raises(SourceError, match="opmaak"):
            bron.detail("hirayasumi")


class TestChapters:
    def test_only_this_series_and_in_reading_order(self):
        """De pagina heeft een zijbalk met heel andere reeksen erin."""
        bron = _bron({"/manga/hirayasumi": httpx.Response(200, text=REEKS_HTML)})
        hoofdstukken = bron.chapters("hirayasumi")
        assert [h.number for h in hoofdstukken] == ["0", "2", "9.5", "10"]
        assert all(h.ref.startswith("hirayasumi/") for h in hoofdstukken)

    def test_a_page_without_chapters_is_an_error(self):
        """Een lege lijst zou als 'deze reeks heeft niets' gelezen worden, en
        dan verdwijnt er stilletjes werk uit je bibliotheek."""
        bron = _bron({"/manga/hirayasumi": httpx.Response(200, text="<html><body></body></html>")})
        with pytest.raises(SourceError, match="opmaak"):
            bron.chapters("hirayasumi")


class TestPaginas:
    def test_the_logo_is_not_a_page_and_doubles_are_dropped(self):
        bron = _bron({"/chapter/hirayasumi/chapter-0": httpx.Response(200, text=HOOFDSTUK_HTML)})
        assert bron.page_urls("hirayasumi/chapter-0") == [
            "https://imgx.example/hirayasumi/0/1.jpg",
            "https://imgx.example/hirayasumi/0/2.jpg",
        ]

    def test_a_chapter_without_images_is_an_error(self):
        bron = _bron({"/chapter/hirayasumi/chapter-0": httpx.Response(200, text="<html></html>")})
        with pytest.raises(SourceError, match="opmaak"):
            bron.page_urls("hirayasumi/chapter-0")

    def test_a_malformed_reference_is_refused(self):
        bron = _bron({})
        with pytest.raises(SourceError):
            bron.page_urls("alleen-een-slug")


class TestDownload:
    def test_a_chapter_becomes_a_cbz_in_reading_order(self, tmp_path: Path):
        routes = {
            "/chapter/hirayasumi/chapter-0": httpx.Response(200, text=HOOFDSTUK_HTML),
            "/hirayasumi/0/1.jpg": httpx.Response(200, content=b"eerste"),
            "/hirayasumi/0/2.jpg": httpx.Response(200, content=b"tweede"),
        }
        doel = tmp_path / "Hirayasumi 000.cbz"
        bron = _bron(routes)
        bron.download("hirayasumi/chapter-0", doel)

        with zipfile.ZipFile(doel) as archief:
            assert archief.namelist() == ["001.jpg", "002.jpg"]
            assert archief.read("001.jpg") == b"eerste"

    def test_a_failed_page_leaves_no_half_archive(self, tmp_path: Path):
        """Een half binnengehaald hoofdstuk mag de scanner nooit als geldig
        archief tegenkomen."""
        routes = {
            "/chapter/hirayasumi/chapter-0": httpx.Response(200, text=HOOFDSTUK_HTML),
            "/hirayasumi/0/1.jpg": httpx.Response(200, content=b"eerste"),
            # de tweede pagina ontbreekt: 404
        }
        doel = tmp_path / "Hirayasumi 000.cbz"
        with pytest.raises(SourceError):
            _bron(routes).download("hirayasumi/chapter-0", doel)
        assert not doel.exists()
        assert not doel.with_suffix(".cbz.partial").exists()


class TestZoeken:
    def test_search_resolves_a_pasted_link(self):
        """Zoeken kán niet bij deze bron; een link oplossen wel."""
        bron = _bron({"/manga/hirayasumi": httpx.Response(200, text=REEKS_HTML)})
        treffers = bron.search("https://mangakakalot.fun/manga/hirayasumi")
        assert [t.ref for t in treffers] == ["hirayasumi"]

    def test_an_unknown_series_gives_nothing_instead_of_an_error(self):
        """Hier is niets kapot: je zocht iets wat er niet is."""
        assert _bron({}).search("bestaat-niet") == []

    def test_a_real_search_term_gives_nothing_rather_than_a_wrong_hit(self):
        assert _bron({}).search("een verhaal over eten") == []
