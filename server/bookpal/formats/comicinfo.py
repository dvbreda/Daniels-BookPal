"""ComicInfo.xml — de de-facto standaard die in vrijwel elke cbz/cbr zit."""

from __future__ import annotations

from typing import Any

from lxml import etree

from bookpal.formats.base import BookMetadata

# Velden die we als losse tags overnemen.
_TAG_FIELDS = ("Genre", "Tags", "Characters", "Teams")


def _text(root: Any, name: str) -> str | None:
    node = root.find(name)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def parse_comicinfo(data: bytes) -> BookMetadata:
    meta = BookMetadata()
    try:
        parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
        root = etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError:
        return meta
    if root is None:
        return meta

    meta.series = _text(root, "Series")
    meta.number = _text(root, "Number")
    meta.volume = _text(root, "Volume")
    meta.title = _text(root, "Title")
    meta.publisher = _text(root, "Publisher")
    meta.summary = _text(root, "Summary")
    meta.language = _text(root, "LanguageISO")

    for field_name in ("Writer", "Penciller", "Inker", "Colorist", "Letterer"):
        value = _text(root, field_name)
        if value:
            meta.authors.extend(part.strip() for part in value.split(",") if part.strip())

    for field_name in _TAG_FIELDS:
        value = _text(root, field_name)
        if value:
            meta.tags.extend(part.strip() for part in value.split(",") if part.strip())

    # ComicInfo kent geen land van herkomst, alleen deze signalen. Ze gaan door
    # naar de herkomst-keten in bookpal.metadata.origin.
    manga = _text(root, "Manga")
    if manga:
        meta.raw["Manga"] = manga
        if manga.lower() == "yesandrighttoleft":
            meta.right_to_left = True
    for key in ("Publisher", "LanguageISO", "Imprint", "Web", "AgeRating", "Format"):
        value = _text(root, key)
        if value:
            meta.raw[key] = value

    # Dedupliceer met behoud van volgorde.
    meta.authors = list(dict.fromkeys(meta.authors))
    meta.tags = list(dict.fromkeys(meta.tags))
    return meta
