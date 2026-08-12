"""De ``Source``-interface (M5, docs/architectuur.md).

Eén contract voor elke externe bron, zodat een tweede bron later een los
bestand is in plaats van een verbouwing. De vier methodes lopen van breed naar
smal: zoeken levert treffers, detail vult een serie, chapters somt de delen op,
en download haalt er één binnen als cbz.

Bewust géén scrapers: een bron hoort een gepubliceerde API te hebben waarvan
het gebruik is toegestaan.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


class SourceError(RuntimeError):
    """De bron deed niet wat we verwachtten — netwerk, rate limit of contract."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Eén treffer. ``ref`` is de identifier binnen de bron zelf."""

    ref: str
    title: str
    description: str | None = None
    year: int | None = None
    status: str | None = None
    cover_url: str | None = None
    # De herkomst-keten (ontwerp 1) gebruikt dit als stap 2 — sterker dan wat
    # een bestandsnaam of maponderdeel prijsgeeft.
    original_language: str | None = None
    # {"mal": "2435", "anilist": "32435"} — M7 krijgt de koppeling zo gratis.
    tracker_ids: dict[str, str] = field(default_factory=dict)
    # Schrijver en tekenaar. Een scanlation-cbz heeft zelden ComicInfo, dus
    # voor gevolgde series is dit de enige plek waar de auteur vandaan komt.
    authors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CoverInfo:
    """Eén omslag bij een reeks. ``volume`` is None voor de hoofdomslag."""

    url: str
    volume: str | None = None


@dataclass(frozen=True, slots=True)
class ChapterInfo:
    """Eén hoofdstuk bij een serie.

    Let op ``group_id``: dezelfde aflevering kan meerdere keren voorkomen,
    vertaald door verschillende groepen. Wie dat vertaald heeft is het enige
    bruikbare onderscheid — nummer, volume en paginatelling zijn dan gelijk.
    """

    ref: str
    number: str | None
    volume: str | None
    title: str | None
    language: str
    page_count: int | None = None
    published_at: str | None = None
    group_id: str | None = None
    group_name: str | None = None


class Source(ABC):
    """Wat elke bron moet kunnen."""

    #: Sleutel in de database (``Source.type``).
    type: str

    @abstractmethod
    def search(self, query: str, *, limit: int = 20) -> list[SearchResult]:
        """Zoek series op titel."""

    @abstractmethod
    def detail(self, ref: str) -> SearchResult:
        """Alles wat de bron over één serie weet."""

    @abstractmethod
    def chapters(self, ref: str, *, language: str = "en") -> list[ChapterInfo]:
        """De hoofdstukken van een serie, oplopend gesorteerd."""

    @abstractmethod
    def page_urls(self, chapter_ref: str, *, data_saver: bool = False) -> list[str]:
        """Directe URL's van de pagina's van één hoofdstuk."""

    @abstractmethod
    def download(self, chapter_ref: str, target: Path, *, data_saver: bool = False) -> Path:
        """Haal een hoofdstuk op en schrijf het als cbz naar ``target``."""
