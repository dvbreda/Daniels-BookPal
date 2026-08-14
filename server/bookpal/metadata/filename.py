"""Serie, deel en hoofdstuk uit een bestandsnaam halen.

Dit is de vangnetlaag: als een bestand geen ComicInfo.xml of OPF heeft — en dat
geldt voor een groot deel van elke echte collectie — is de bestandsnaam alles
wat er is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Groepen die niets over de serie zeggen: scanlator-tags, jaartallen, kwaliteit.
_BRACKETS = re.compile(r"[\[\{(][^\]\})]*[\]\})]")
_UNDERSCORES = re.compile(r"_+")
# Punten scheiden vaak woorden ("Serie.Naam.01"), maar een punt tússen cijfers
# is een decimaal hoofdstuknummer — c012.5 mag niet tot 012 verminken.
_DOTS = re.compile(r"(?<!\d)\.+|\.+(?!\d)")
_WHITESPACE = re.compile(r"\s+")

# "v01", "vol. 3", "deel 2", "T5" (tome, gebruikelijk bij Franstalige albums)
_VOLUME = re.compile(
    r"(?:^|[\s\-])(?:v|vol|volume|deel|tome|t)\.?\s*(\d{1,4})(?=$|[\s\-])", re.IGNORECASE
)
# "c012", "ch. 5", "chapter 7", "hoofdstuk 3", "#12"
_CHAPTER = re.compile(
    r"(?:^|[\s\-])(?:c|ch|chapter|chap|hoofdstuk|#)\.?\s*(\d{1,5}(?:\.\d{1,2})?)(?=$|[\s\-])",
    re.IGNORECASE,
)
# Een kaal nummer aan het eind: "De Testreeks 01"
_TRAILING_NUMBER = re.compile(r"^(?P<series>.*?)[\s\-]+(?P<number>\d{1,5}(?:\.\d{1,2})?)$")


@dataclass(slots=True)
class ParsedName:
    series: str | None = None
    number: str | None = None
    volume: str | None = None
    title: str | None = None


def _clean(text: str) -> str:
    text = _BRACKETS.sub(" ", text)
    text = _UNDERSCORES.sub(" ", text)
    text = _DOTS.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip(" -–—")


def normalise_number(raw: str | None) -> float:
    """Nummer naar iets sorteerbaars.

    Ontbrekende nummers gaan achteraan in plaats van vooraan: een los album
    zonder nummer hoort niet vóór deel 1 te staan.
    """
    if raw is None:
        return float("inf")
    try:
        return float(raw)
    except ValueError:
        digits = re.search(r"\d+(?:\.\d+)?", raw)
        return float(digits.group()) if digits else float("inf")


def parse_filename(stem: str) -> ParsedName:
    """Ontleed een bestandsnaam zonder extensie."""
    result = ParsedName()
    text = _clean(stem)
    if not text:
        return result

    volume_match = _VOLUME.search(text)
    if volume_match:
        result.volume = volume_match.group(1)
        text = (text[: volume_match.start()] + " " + text[volume_match.end() :]).strip()

    chapter_match = _CHAPTER.search(text)
    if chapter_match:
        result.number = chapter_match.group(1)
        series = text[: chapter_match.start()].strip(" -–—")
        remainder = text[chapter_match.end() :].strip(" -–—")
        result.series = _clean(series) or None
        result.title = _clean(remainder) or None
        if result.series is None and result.title:
            result.series, result.title = result.title, None
        return result

    # "Serie - 012 - Titel"
    parts = [part.strip() for part in text.split(" - ") if part.strip()]
    if len(parts) >= 2 and re.fullmatch(r"\d{1,5}(?:\.\d{1,2})?", parts[1]):
        result.series = parts[0]
        result.number = parts[1]
        result.title = " - ".join(parts[2:]) or None
        return result

    trailing = _TRAILING_NUMBER.match(text)
    if trailing:
        series = trailing.group("series").strip(" -–—")
        if series:
            result.series = series
            result.number = trailing.group("number")
            return result

    # Geen nummer gevonden: het hele ding is de titel.
    result.title = text
    result.series = text
    if result.volume is not None and result.number is None:
        result.number = result.volume
    return result


def sort_title(title: str) -> str:
    """Lidwoorden vooraan negeren bij het sorteren, zoals elke bibliotheek doet.

    Kleine letters, en dat is niet cosmetisch: SQLite sorteert standaard op
    tekencode, dus "Claire" komt vóór "crayon". Een lijst die deels met en deels
    zonder hoofdletters is opgeslagen valt daardoor in tweeën.
    """
    lowered = title.strip()
    for article in ("de ", "het ", "een ", "the ", "a ", "an ", "l'", "le ", "la ", "les "):
        if lowered.lower().startswith(article):
            return (lowered[len(article) :].strip() or lowered).lower()
    return lowered.lower()
