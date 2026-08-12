"""OPDS als bron: zelf een catalogus toevoegen.

MangaDex en Internet Archive zitten in de code omdat ze een eigen API hebben.
Deze niet: dit is de bron waar je zélf een adres in zet. OPDS is de standaard
waarmee bibliotheken hun catalogus publiceren, en hij wordt gesproken door onder
meer Kavita, Komga, Calibre-web, Standard Ebooks, Project Gutenberg en — niet
onbelangrijk — BookPal zelf. Eén adres invullen en je hebt er een bron bij,
zonder dat er een regel code bij hoeft.

Het formaat is Atom-XML met twee soorten feeds:

* een **navigatiefeed** verwijst naar andere feeds — planken, reeksen, mappen;
* een **acquisitiefeed** bevat boeken, elk met een of meer downloadlinks.

Wij vertalen dat naar wat ``Source`` verwacht: een treffer is een boek of een
reeks, en de "hoofdstukken" zijn de bestanden die eronder hangen. Een boek dat
maar één bestand heeft levert dus één hoofdstuk op, en dat is precies goed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx
from lxml import etree

from bookpal.formats import SUPPORTED_EXTENSIONS
from bookpal.ratelimit import RateLimiter
from bookpal.sources.base import ChapterInfo, CoverInfo, SearchResult, Source, SourceError

logger = logging.getLogger(__name__)

USER_AGENT = "DanielsBookPal/0.1 (persoonlijke bibliotheek; +https://github.com/dvbreda)"

_ATOM = "http://www.w3.org/2005/Atom"
_OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1/"
_DC = "http://purl.org/dc/terms/"

# Waaraan je een downloadlink herkent. OPDS zet het doel in de rel; alles wat
# met dit voorvoegsel begint is een bestand dat je mag ophalen.
_ACQUISITION = "http://opds-spec.org/acquisition"
_IMAGE_RELS = ("http://opds-spec.org/image", "http://opds-spec.org/cover")
_THUMBNAIL_RELS = (
    "http://opds-spec.org/image/thumbnail",
    "http://opds-spec.org/thumbnail",
)

# Een feed die naar andere feeds wijst in plaats van naar bestanden.
_NAVIGATION = "application/atom+xml"


def _text(element: Any, naam: str, ns: str = _ATOM) -> str | None:
    gevonden = element.find(f"{{{ns}}}{naam}")
    if gevonden is None or gevonden.text is None:
        return None
    return str(gevonden.text).strip() or None


def _links(entry: Any) -> list[dict[str, str]]:
    return [
        {
            "rel": str(link.get("rel") or ""),
            "href": str(link.get("href") or ""),
            "type": str(link.get("type") or ""),
            "title": str(link.get("title") or ""),
        }
        for link in entry.findall(f"{{{_ATOM}}}link")
        if link.get("href")
    ]


def _authors(entry: Any) -> list[str]:
    namen = []
    for auteur in entry.findall(f"{{{_ATOM}}}author"):
        naam = _text(auteur, "name")
        if naam:
            namen.append(naam)
    return namen


class OpdsSource(Source):
    """Een OPDS-catalogus. Het adres komt uit ``Source.config``."""

    type = "opds"

    def __init__(
        self,
        url: str = "",
        *,
        username: str = "",
        password: str = "",
        client: httpx.Client | None = None,
        rate: float = 5.0,
    ) -> None:
        self._url = url.strip()
        if client is not None:
            self._client = client
        else:
            if not self._url:
                raise SourceError("deze bron heeft nog geen catalogus-adres")
            auth = (username, password) if username else None
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
                follow_redirects=True,
                auth=auth,
            )
        self._limiter = RateLimiter(rate)

    # -- ophalen en lezen ---------------------------------------------------

    def _feed(self, url: str) -> Any:
        self._limiter.acquire()
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise SourceError(f"catalogus niet bereikbaar: {exc}") from exc
        if response.status_code == 401:
            raise SourceError("de catalogus vraagt om een gebruikersnaam en wachtwoord")
        if response.status_code >= 400:
            raise SourceError(f"de catalogus gaf {response.status_code}")
        try:
            # resolve_entities uit: een feed van buiten mag geen bestanden van
            # deze machine kunnen opvragen via een entiteit in de xml.
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            wortel = etree.fromstring(response.content, parser=parser)
        except etree.XMLSyntaxError as exc:
            raise SourceError(f"dit adres geeft geen OPDS terug: {exc}") from exc

        # Geldige xml is nog geen OPDS. Een gewone webpagina komt hier vaak
        # doorheen, en dan zou je een lege lijst krijgen zonder te weten waarom.
        if wortel.tag not in (
            f"{{{_ATOM}}}feed",
            f"{{{_ATOM}}}entry",
            f"{{{_OPENSEARCH}}}OpenSearchDescription",
        ):
            raise SourceError("dit adres geeft geen OPDS terug (geen Atom-feed)")
        return wortel

    def _entries(self, feed: Any) -> list[Any]:
        gevonden: list[Any] = feed.findall(f"{{{_ATOM}}}entry")
        return gevonden

    def _to_result(self, entry: Any, basis: str) -> SearchResult:
        links = _links(entry)
        eigen = next(
            (
                link
                for link in links
                if link["rel"] in ("self", "alternate", "subsection")
                or link["type"].startswith(_NAVIGATION)
            ),
            None,
        )
        omslag = next(
            (link for link in links if link["rel"] in _IMAGE_RELS),
            next((link for link in links if link["rel"] in _THUMBNAIL_RELS), None),
        )
        # De ref is een volledig adres: dan is elk vervolg zelfstandig op te
        # halen, ook als de catalogus zijn paden anders opbouwt dan wij denken.
        ref = urljoin(basis, eigen["href"]) if eigen else (_text(entry, "id") or "")
        jaar = _text(entry, "issued", _DC) or _text(entry, "published")
        return SearchResult(
            ref=ref,
            title=_text(entry, "title") or "(zonder titel)",
            description=_text(entry, "summary") or _text(entry, "content"),
            year=int(jaar[:4]) if jaar and jaar[:4].isdigit() else None,
            url=ref or None,
            cover_url=urljoin(basis, omslag["href"]) if omslag else None,
            authors=_authors(entry),
            original_language=_text(entry, "language", _DC),
        )

    # -- de Source-interface ------------------------------------------------

    def search(
        self, query: str, *, limit: int = 20, language: str | None = None
    ) -> list[SearchResult]:
        """Zoek in de catalogus.

        Een OPDS-catalogus zegt zelf hoe je erin zoekt, via een OpenSearch-
        beschrijving. Ontbreekt die, dan proberen we ``?q=`` — dat doen de
        meeste implementaties toch — en anders filteren we wat de wortelfeed
        teruggeeft op titel. Iets teruggeven is beter dan een foutmelding.
        """
        wortel = self._feed(self._url)
        sjabloon = self._search_template(wortel)

        if sjabloon:
            doel = sjabloon.replace("{searchTerms}", quote(query, safe=""))
            feed = self._feed(urljoin(self._url, doel))
            return [self._to_result(entry, self._url) for entry in self._entries(feed)][:limit]

        gevonden = [self._to_result(entry, self._url) for entry in self._entries(wortel)]
        naald = query.strip().lower()
        passend = [item for item in gevonden if naald in item.title.lower()]
        return (passend or gevonden)[:limit]

    def _search_template(self, feed: Any) -> str | None:
        """Het zoeksjabloon van deze catalogus, als hij er een noemt."""
        for link in _links(feed):
            if link["rel"] != "search" or not link["href"]:
                continue
            if "opensearchdescription" not in link["type"]:
                # Sommige catalogi zetten het sjabloon rechtstreeks in de link.
                return link["href"] if "{searchTerms}" in link["href"] else None
            beschrijving = self._feed(urljoin(self._url, link["href"]))
            for url in beschrijving.findall(f"{{{_OPENSEARCH}}}Url"):
                sjabloon = url.get("template")
                if sjabloon and "{searchTerms}" in sjabloon:
                    return str(sjabloon)
        return None

    def detail(self, ref: str) -> SearchResult:
        feed = self._feed(ref)
        if feed.tag == f"{{{_ATOM}}}entry":
            return self._to_result(feed, ref)
        # Een feed in plaats van één regel: dan is de feed zelf de reeks.
        titel = _text(feed, "title") or "(zonder titel)"
        return SearchResult(ref=ref, title=titel, url=ref)

    def chapters(self, ref: str, *, language: str = "en") -> list[ChapterInfo]:
        """De bestanden onder deze regel.

        Een boek met één bestand levert één hoofdstuk. Een reeks met een eigen
        feed levert er zoveel als er in staan.
        """
        feed = self._feed(ref)
        entries = self._entries(feed) or [feed]
        gevonden: list[ChapterInfo] = []
        for volgnummer, entry in enumerate(entries, start=1):
            bestand = self._acquisition(entry)
            if bestand is None:
                continue
            gevonden.append(
                ChapterInfo(
                    ref=urljoin(ref, bestand["href"]),
                    number=str(volgnummer),
                    volume=None,
                    title=_text(entry, "title") or f"Deel {volgnummer}",
                    language=language,
                    published_at=_text(entry, "updated"),
                )
            )
        return gevonden

    def _acquisition(self, entry: Any) -> dict[str, str] | None:
        """De downloadlink die wij kunnen lezen.

        Een boek staat er vaak in meerdere vormen bij. We nemen de eerste die
        een formaat heeft dat BookPal aankan; kent de catalogus het formaat niet,
        dan gokken we op de eerste downloadlink.
        """
        links = [link for link in _links(entry) if link["rel"].startswith(_ACQUISITION)]
        for link in links:
            suffix = Path(urlparse(link["href"]).path).suffix.lower()
            if suffix in SUPPORTED_EXTENSIONS:
                return link
        return links[0] if links else None

    def covers(self, ref: str, *, limit: int = 100) -> list[CoverInfo]:
        feed = self._feed(ref)
        for link in _links(feed):
            if link["rel"] in _IMAGE_RELS:
                return [CoverInfo(url=urljoin(ref, link["href"]))]
        return []

    def chapter_count(self, ref: str, *, language: str = "en") -> int:
        return len(self.chapters(ref, language=language))

    def page_urls(self, chapter_ref: str, *, data_saver: bool = False) -> list[str]:
        raise SourceError("OPDS levert hele bestanden, geen losse pagina's")

    def download(self, chapter_ref: str, target: Path, *, data_saver: bool = False) -> Path:
        """Haal dit bestand op.

        Naar een tijdelijke naam en dan pas omzetten: een half binnengehaald
        boek mag de scanner nooit als geldig bestand tegenkomen.
        """
        # Zoals bij het Internet Archive: de extensie komt van de bron, niet
        # van wat wij hopen dat het is.
        suffix = Path(urlparse(chapter_ref).path).suffix.lower()
        if suffix and suffix != target.suffix.lower():
            target = target.with_suffix(suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")
        self._limiter.acquire()
        try:
            with self._client.stream("GET", chapter_ref) as response:
                if response.status_code >= 400:
                    raise SourceError(f"de catalogus gaf {response.status_code}")
                with partial.open("wb") as uit:
                    for blok in response.iter_bytes(1024 * 1024):
                        uit.write(blok)
            partial.replace(target)
        except httpx.HTTPError as exc:
            raise SourceError(f"ophalen mislukt: {exc}") from exc
        finally:
            partial.unlink(missing_ok=True)
        return target

    def close(self) -> None:
        self._client.close()
