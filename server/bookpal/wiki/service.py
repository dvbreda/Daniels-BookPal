"""Zoeken op Wikipedia en een artikel omzetten naar een epub."""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass
from html import escape
from io import BytesIO

import httpx
from lxml import html as lxml_html

logger = logging.getLogger(__name__)

# Wikipedia vraagt om een herkenbare User-Agent bij geautomatiseerd gebruik.
USER_AGENT = "DanielsBookPal/0.1 (persoonlijke bibliotheek; +https://github.com/dvbreda)"

# Alleen echte taalcodes; dit gaat rechtstreeks in een hostnaam.
_LANG = re.compile(r"^[a-z]{2,3}(-[a-z]{2,8})?$")

# Wat er uit een artikel weg mag voordat het een leesbaar hoofdstuk wordt.
# Wikipedia's HTML zit vol navigatie, bewerkknoppen en verwijzingen die in een
# epub alleen maar in de weg staan.
# XPath/tag-namen en geen CSS-selectors: cssselect is een extra afhankelijkheid
# voor iets wat lxml zelf al kan, en die zat niet in de image.
_STRIP_TAGS = ("style", "script", "noscript", "link", "meta", "img", "figure", "table")
_STRIP_CLASSES = frozenset(
    {
        "navbox",
        "vertical-navbox",
        "ambox",
        "metadata",
        "hatnote",
        "thumb",
        "reference",
        "mw-editsection",
        "reflist",
        "references",
        "infobox",
        "mw-references-wrap",
        "sistersitebox",
        "noprint",
        "mw-empty-elt",
    }
)

# Secties die na de eigenlijke tekst komen en in een epub niets toevoegen.
_TAIL_SECTIONS = {
    "references",
    "external links",
    "further reading",
    "see also",
    "notes",
    "bibliography",
    "sources",
    "referenties",
    "externe links",
    "zie ook",
    "bronnen",
    "noten",
    "literatuur",
}


class WikiError(RuntimeError):
    """Ophalen mislukt. Zacht: de lezer toont een nette melding."""


@dataclass(frozen=True, slots=True)
class WikiHit:
    title: str
    key: str
    description: str | None
    lang: str


def _check_lang(lang: str) -> str:
    if not _LANG.match(lang):
        raise WikiError(f"ongeldige taalcode: {lang!r}")
    return lang


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=20.0,
        follow_redirects=True,
    )


def search(query: str, *, lang: str = "nl", limit: int = 5) -> list[WikiHit]:
    """Zoek artikelen, met het Engels erbij.

    Veel manga en strips hebben geen Nederlands artikel, maar de Nederlandse
    zoekmachine geeft dan wél resultaten — alleen niet de goede. Op "Oishinbo"
    kwam er "Lijst van NES-spellen" uit, puur omdat de titel ergens in die
    lijst voorkomt. Daarom niet alleen terugvallen als er níets is, maar
    beoordelen of er een treffer bij zit die echt over dit onderwerp gaat, en
    anders het Engels erbij halen.
    """
    _check_lang(lang)
    hits = _search_one(query, lang, limit)
    if not _has_close_match(hits, query) and lang != "en":
        hits = hits + [
            hit for hit in _search_one(query, "en", limit) if hit.key not in {h.key for h in hits}
        ]
    # Een titel die op de zoekterm lijkt hoort bovenaan, ongeacht de taal.
    return sorted(hits, key=lambda hit: (not _close(hit.title, query), len(hit.title)))[:limit]


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _close(title: str, query: str) -> bool:
    a, b = _normalise(title), _normalise(query)
    return bool(a) and bool(b) and (a == b or a.startswith(b) or b.startswith(a))


def _has_close_match(hits: list[WikiHit], query: str) -> bool:
    return any(_close(hit.title, query) for hit in hits)


def _search_one(query: str, lang: str, limit: int) -> list[WikiHit]:
    with _client() as client:
        try:
            response = client.get(
                f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page",
                params={"q": query, "limit": limit},
            )
        except httpx.HTTPError as exc:
            raise WikiError(f"Wikipedia niet bereikbaar: {exc}") from exc
    if response.status_code >= 400:
        raise WikiError(f"Wikipedia gaf {response.status_code}")

    return [
        WikiHit(
            title=str(page.get("title", "")),
            key=str(page.get("key", "")),
            description=page.get("description"),
            lang=lang,
        )
        for page in response.json().get("pages", [])
        if page.get("key")
    ]


def fetch_html(key: str, *, lang: str = "nl") -> tuple[str, str]:
    """Het artikel als (titel, opgeschoonde HTML)."""
    _check_lang(lang)
    with _client() as client:
        try:
            response = client.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/html/{key}")
        except httpx.HTTPError as exc:
            raise WikiError(f"Wikipedia niet bereikbaar: {exc}") from exc
    if response.status_code == 404:
        raise WikiError("dit artikel bestaat niet")
    if response.status_code >= 400:
        raise WikiError(f"Wikipedia gaf {response.status_code}")

    return _clean(response.text, key)


def _clean(raw: str, key: str) -> tuple[str, str]:
    document = lxml_html.fromstring(raw)

    title_nodes = document.xpath("//title/text()")
    title = str(title_nodes[0]) if title_nodes else key.replace("_", " ")

    body = document.find("body")
    root = body if body is not None else document

    for tag in _STRIP_TAGS:
        for node in list(root.iter(tag)):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

    for node in list(root.iterdescendants()):
        if _STRIP_CLASSES.intersection((node.get("class") or "").split()):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

    # Alles vanaf "Referenties" en verder weghalen: in een epub lees je geen
    # voetnotenlijst, en het is vaak de helft van het document.
    _drop_tail_sections(root)

    pieces: list[str] = []
    for node in root.iterchildren():
        if node.tag in ("section", "p", "h2", "h3", "h4", "ul", "ol", "blockquote", "dl"):
            pieces.append(lxml_html.tostring(node, encoding="unicode", method="html"))
    cleaned = "".join(pieces) or lxml_html.tostring(root, encoding="unicode", method="html")

    # De epub-lezer verwacht XHTML; losse attributen zonder waarde en
    # niet-gesloten tags maken hem stuk.
    cleaned = lxml_html.tostring(
        lxml_html.fromstring(f"<div>{cleaned}</div>"), encoding="unicode", method="xml"
    )
    return title, cleaned


def _drop_tail_sections(root: lxml_html.HtmlElement) -> None:
    dropping = False
    for node in list(root.iterdescendants()):
        if node.tag in ("h2", "h3"):
            heading = " ".join(node.itertext()).strip().lower()
            dropping = heading in _TAIL_SECTIONS
        if dropping:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)


def article_epub(key: str, *, lang: str = "nl") -> tuple[str, bytes]:
    """Het artikel als (titel, epub-bytes)."""
    title, content = fetch_html(key, lang=lang)
    return title, _build_epub(title, content, lang, key)


def _build_epub(title: str, content: str, lang: str, key: str) -> bytes:
    safe_title = escape(title)
    source = f"https://{lang}.wikipedia.org/wiki/{key}"
    chapter = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        f"<head><title>{safe_title}</title></head>"
        f"<body><h1>{safe_title}</h1>{content}"
        # De herkomst hoort erbij: dit is Wikipedia's tekst, niet de onze.
        f'<hr/><p><small>Van Wikipedia, <a href="{escape(source)}">{escape(source)}</a> — '
        "tekst onder CC BY-SA.</small></p>"
        "</body></html>"
    )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        # mimetype moet als eerste en ongecomprimeerd in het archief staan.
        archive.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr("OEBPS/artikel.xhtml", chapter)
        archive.writestr(
            "OEBPS/nav.xhtml",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
            '<nav epub:type="toc"><ol>'
            f'<li><a href="artikel.xhtml">{safe_title}</a></li>'
            "</ol></nav></body></html>",
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="bookid">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{safe_title}</dc:title>"
            "<dc:creator>Wikipedia</dc:creator>"
            f"<dc:language>{escape(lang)}</dc:language>"
            f"<dc:source>{escape(source)}</dc:source>"
            "<dc:rights>CC BY-SA</dc:rights>"
            f'<dc:identifier id="bookid">urn:wikipedia:{escape(lang)}:{escape(key)}</dc:identifier>'
            "</metadata>"
            "<manifest>"
            '<item id="art" href="artikel.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            "</manifest>"
            '<spine><itemref idref="art"/></spine>'
            "</package>",
        )
    return buffer.getvalue()
