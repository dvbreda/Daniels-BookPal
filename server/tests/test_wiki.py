"""Wikipedia als epub: wat er van een artikel overblijft en wat er misgaat."""

from __future__ import annotations

import zipfile
from io import BytesIO

import httpx
import pytest

from bookpal.wiki import service
from bookpal.wiki.service import WikiError, WikiHit, _clean, search

ARTICLE = """<html><head><title>Oishinbo</title></head><body>
<section><p>Oishinbo is een kookmanga.</p>
<figure><img src="x.jpg"/><figcaption>Een plaatje</figcaption></figure>
<table class="infobox"><tr><td>Rommel</td></tr></table>
<div class="hatnote">Zie ook iets anders</div>
<sup class="reference">[1]</sup>
<h2>Verhaal</h2><p>Yamaoka proeft.</p>
<h2>Referenties</h2><ol class="references"><li>Bron 1</li></ol>
</section></body></html>"""


class TestClean:
    def test_the_title_comes_from_the_document(self):
        title, _ = _clean(ARTICLE, "Oishinbo")
        assert title == "Oishinbo"

    def test_the_body_text_survives(self):
        _, html = _clean(ARTICLE, "Oishinbo")
        assert "kookmanga" in html
        assert "Yamaoka proeft" in html

    def test_navigation_and_boxes_are_stripped(self):
        """Wikipedia's HTML zit vol dingen die in een epub alleen in de weg
        staan."""
        _, html = _clean(ARTICLE, "Oishinbo")
        assert "infobox" not in html
        assert "hatnote" not in html
        assert "<img" not in html
        assert "figcaption" not in html

    def test_the_reference_list_is_dropped(self):
        _, html = _clean(ARTICLE, "Oishinbo")
        assert "Bron 1" not in html

    def test_the_result_is_parseable_xml(self):
        """De epub-lezer verwacht XHTML; niet-gesloten tags maken hem stuk."""
        from lxml import etree

        _, html = _clean(ARTICLE, "Oishinbo")
        etree.fromstring(html.encode())  # gooit als het geen geldige XML is

    def test_a_missing_title_falls_back_to_the_key(self):
        title, _ = _clean("<html><body><p>Hoi</p></body></html>", "Een_Sleutel")
        assert title == "Een Sleutel"


class TestEpub:
    def test_it_builds_a_valid_epub(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(service, "fetch_html", lambda key, lang="nl": ("Titel", "<p>Hoi</p>"))
        title, data = service.article_epub("Titel", lang="nl")

        assert title == "Titel"
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            # mimetype moet als eerste en ongecomprimeerd in het archief staan.
            assert names[0] == "mimetype"
            assert archive.read("mimetype") == b"application/epub+zip"
            assert "OEBPS/content.opf" in names
            chapter = archive.read("OEBPS/artikel.xhtml").decode()
            assert "Hoi" in chapter
            # De herkomst hoort erbij: dit is Wikipedia's tekst, niet de onze.
            assert "CC BY-SA" in chapter
            assert "wikipedia.org" in chapter


class TestSearch:
    def _stub(self, monkeypatch: pytest.MonkeyPatch, per_lang: dict[str, list[str]]) -> None:
        def fake(query: str, lang: str, limit: int) -> list[WikiHit]:
            return [
                WikiHit(title=title, key=title.replace(" ", "_"), description=None, lang=lang)
                for title in per_lang.get(lang, [])
            ]

        monkeypatch.setattr(service, "_search_one", fake)

    def test_english_is_added_when_the_local_hits_are_off_topic(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Het echte geval: "Oishinbo" gaf op nl "Lijst van NES-spellen",
        puur omdat de titel ergens in die lijst voorkomt."""
        self._stub(monkeypatch, {"nl": ["Lijst van NES-spellen"], "en": ["Oishinbo"]})
        hits = search("Oishinbo", lang="nl")
        assert hits[0].title == "Oishinbo"
        assert hits[0].lang == "en"

    def test_a_good_local_hit_stays_on_top(self, monkeypatch: pytest.MonkeyPatch):
        self._stub(monkeypatch, {"nl": ["Kuifje", "Kuifje in Afrika"], "en": ["Tintin"]})
        hits = search("Kuifje", lang="nl")
        assert hits[0].title == "Kuifje"
        assert hits[0].lang == "nl"

    def test_an_invalid_language_is_refused(self):
        """De taalcode gaat rechtstreeks in een hostnaam."""
        with pytest.raises(WikiError):
            search("x", lang="../evil")

    def test_an_unreachable_wikipedia_is_a_clear_error(self, monkeypatch: pytest.MonkeyPatch):
        def boom(*args: object, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("weg")

        monkeypatch.setattr(httpx.Client, "get", boom)
        with pytest.raises(WikiError, match="niet bereikbaar"):
            search("x", lang="nl")


class TestApi:
    def test_search_needs_a_query(self, client):
        assert client.get("/api/wiki/search").status_code == 422

    def test_an_invalid_language_is_a_502(self, client, monkeypatch: pytest.MonkeyPatch):
        response = client.get("/api/wiki/search", params={"q": "x", "lang": "../etc"})
        assert response.status_code in (422, 502)
