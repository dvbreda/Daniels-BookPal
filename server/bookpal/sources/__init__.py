"""Externe bronnen (M5). Eén interface, per bron een implementatie."""

from __future__ import annotations

from bookpal.sources.base import ChapterInfo, SearchResult, Source, SourceError
from bookpal.sources.mangadex import MangaDexSource
from bookpal.sources.ratelimit import RateLimiter

#: Bron-implementaties op ``Source.type``. Een nieuwe bron is een regel erbij.
REGISTRY: dict[str, type[Source]] = {
    MangaDexSource.type: MangaDexSource,
}


def get_source(source_type: str) -> Source:
    """Maak een bron aan op type, zoals opgeslagen in ``Source.type``."""
    implementation = REGISTRY.get(source_type)
    if implementation is None:
        raise SourceError(f"onbekende bron: {source_type}")
    return implementation()


__all__ = [
    "REGISTRY",
    "ChapterInfo",
    "MangaDexSource",
    "RateLimiter",
    "SearchResult",
    "Source",
    "SourceError",
    "get_source",
]
