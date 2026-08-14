"""OPDS als bron: de plek waar je zelf een catalogus toevoegt.

OPDS is de standaard waarmee bibliotheken hun catalogus publiceren — Kavita,
Komga, Calibre-web, Standard Ebooks, en BookPal zelf. Wat hier vastligt is dat
één adres genoeg is, en dat een adres dat geen OPDS geeft dat meteen zegt.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bookpal.sources.base import SourceError
from bookpal.sources.opds import OpdsSource

WORTEL = "https://catalogus.test/opds"

_ZOEKBESCHRIJVING = """<?xml version="1.0"?>
<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
  <Url type="application/atom+xml" template="https://catalogus.test/zoek?q={searchTerms}"/>
</OpenSearchDescription>"""

_FEED = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dcterms="http://purl.org/dc/terms/">
  <title>Mijn catalogus</title>
  <link rel="search" type="application/opensearchdescription+xml" href="/zoek.xml"/>
  <entry>
    <title>Shinya Shokudo</title>
    <id>urn:reeks:1</id>
    <author><name>Abe Yarou</name></author>
    <summary>Een kroeg die 's nachts open is.</summary>
    <dcterms:issued>2007-01-01</dcterms:issued>
    <link rel="http://opds-spec.org/image" href="/omslag/1.jpg" type="image/jpeg"/>
    <link rel="subsection" type="application/atom+xml" href="/reeks/1"/>
  </entry>
  <entry>
    <title>Iets anders</title>
    <id>urn:reeks:2</id>
    <link rel="subsection" type="application/atom+xml" href="/reeks/2"/>
  </entry>
</feed>"""

_REEKS = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Shinya Shokudo</title>
  <entry>
    <title>Deel 1</title>
    <updated>2026-01-01T00:00:00Z</updated>
    <link rel="http://opds-spec.org/acquisition" href="/bestand/1.cbz" type="application/x-cbz"/>
    <link rel="http://opds-spec.org/acquisition" href="/bestand/1.pdf" type="application/pdf"/>
  </entry>
  <entry>
    <title>Deel 2</title>
    <link rel="http://opds-spec.org/acquisition" href="/bestand/2.cbz" type="application/x-cbz"/>
  </entry>
</feed>"""


def _bron(handler=None, **opties) -> OpdsSource:
    def standaard(request: httpx.Request) -> httpx.Response:
        pad = request.url.path
        if pad == "/opds":
            return httpx.Response(200, content=_FEED.encode())
        if pad == "/zoek.xml":
            return httpx.Response(200, content=_ZOEKBESCHRIJVING.encode())
        if pad == "/zoek":
            return httpx.Response(200, content=_FEED.encode())
        if pad.startswith("/reeks/"):
            return httpx.Response(200, content=_REEKS.encode())
        if pad.startswith("/bestand/"):
            return httpx.Response(200, content=b"cbz-inhoud")
        return httpx.Response(404)

    return OpdsSource(
        WORTEL,
        client=httpx.Client(transport=httpx.MockTransport(handler or standaard)),
        rate=1000.0,
        **opties,
    )


class TestSearching:
    def test_a_catalog_entry_becomes_a_hit(self):
        treffers = _bron().search("shinya")
        assert treffers[0].title == "Shinya Shokudo"
        assert treffers[0].authors == ["Abe Yarou"]
        assert treffers[0].year == 2007
        assert treffers[0].cover_url == "https://catalogus.test/omslag/1.jpg"

    def test_the_ref_is_a_full_address(self):
        """Dan is elk vervolg zelfstandig op te halen."""
        [eerste, _tweede] = _bron().search("shinya")
        assert eerste.ref == "https://catalogus.test/reeks/1"

    def test_the_catalog_own_search_is_used(self):
        gezien: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            gezien.append(str(request.url))
            if request.url.path == "/opds":
                return httpx.Response(200, content=_FEED.encode())
            if request.url.path == "/zoek.xml":
                return httpx.Response(200, content=_ZOEKBESCHRIJVING.encode())
            return httpx.Response(200, content=_FEED.encode())

        _bron(handler).search("shinya shokudo")
        assert any("q=shinya%20shokudo" in url for url in gezien)

    def test_without_a_search_link_the_root_is_filtered(self):
        """Iets teruggeven is beter dan een foutmelding."""
        kaal = _FEED.replace(
            '<link rel="search" type="application/opensearchdescription+xml" href="/zoek.xml"/>',
            "",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=kaal.encode())

        treffers = _bron(handler).search("anders")
        assert [t.title for t in treffers] == ["Iets anders"]


class TestChapters:
    def test_the_files_under_an_entry_become_chapters(self):
        delen = _bron().chapters("https://catalogus.test/reeks/1")
        assert [deel.title for deel in delen] == ["Deel 1", "Deel 2"]

    def test_a_format_we_can_read_wins(self):
        """Hetzelfde deel staat er vaak in meerdere vormen bij."""
        [eerste, _tweede] = _bron().chapters("https://catalogus.test/reeks/1")
        assert eerste.ref.endswith(".cbz")


class TestDownloading:
    def test_a_file_lands_on_disk(self, tmp_path: Path):
        doel = tmp_path / "deel.cbz"
        _bron().download("https://catalogus.test/bestand/1.cbz", doel)
        assert doel.read_bytes() == b"cbz-inhoud"

    def test_nothing_half_is_left_behind(self, tmp_path: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        with pytest.raises(SourceError):
            _bron(handler).download("https://catalogus.test/bestand/1.cbz", tmp_path / "x.cbz")
        assert list(tmp_path.iterdir()) == []


class TestWhenItGoesWrong:
    def test_an_address_that_is_not_opds_says_so(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>hallo</html>")

        with pytest.raises(SourceError, match="geen OPDS"):
            _bron(handler).search("iets")

    def test_a_catalog_behind_a_login_says_so(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        with pytest.raises(SourceError, match="gebruikersnaam"):
            _bron(handler).search("iets")

    def test_without_an_address_it_refuses_to_start(self):
        with pytest.raises(SourceError, match="catalogus-adres"):
            OpdsSource("")

    def test_an_entity_in_the_feed_cannot_read_our_files(self, tmp_path: Path):
        """Een feed van buiten mag geen bestanden van deze machine opvragen."""
        geheim = tmp_path / "geheim.txt"
        geheim.write_text("wachtwoord", encoding="utf-8")
        kwaad = f"""<?xml version="1.0"?>
        <!DOCTYPE feed [<!ENTITY xxe SYSTEM "file://{geheim}">]>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>&xxe;</title><id>1</id></entry>
        </feed>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=kwaad.encode())

        try:
            treffers = _bron(handler).search("iets")
        except SourceError:
            return  # geweigerd is ook goed
        assert all("wachtwoord" not in (t.title or "") for t in treffers)
