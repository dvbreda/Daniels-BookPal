"""Externe bronnen (M5). Eén interface, per bron een implementatie."""

from __future__ import annotations

from bookpal.ratelimit import RateLimiter
from bookpal.sources.archiveorg import ArchiveOrgSource
from bookpal.sources.base import ChapterInfo, SearchResult, Source, SourceError
from bookpal.sources.mangadex import MangaDexSource

#: Bron-implementaties op ``Source.type``. Een nieuwe bron is een regel erbij.
REGISTRY: dict[str, type[Source]] = {
    MangaDexSource.type: MangaDexSource,
    ArchiveOrgSource.type: ArchiveOrgSource,
}


def get_source(source_type: str) -> Source:
    """Maak een bron aan op type, zoals opgeslagen in ``Source.type``."""
    implementation = REGISTRY.get(source_type)
    if implementation is None:
        raise SourceError(f"onbekende bron: {source_type}")
    return implementation()


__all__ = [
    "REGISTRY",
    "ArchiveOrgSource",
    "ChapterInfo",
    "MangaDexSource",
    "RateLimiter",
    "SearchResult",
    "Source",
    "SourceError",
    "get_source",
]
