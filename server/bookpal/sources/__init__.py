"""Externe bronnen (M5). Eén interface, per bron een implementatie."""

from __future__ import annotations

import inspect
from typing import Any

from bookpal.ratelimit import RateLimiter
from bookpal.sources.archiveorg import ArchiveOrgSource
from bookpal.sources.base import ChapterInfo, SearchResult, Source, SourceError
from bookpal.sources.mangadex import MangaDexSource
from bookpal.sources.opds import OpdsSource

#: Bron-implementaties op ``Source.type``. Een nieuwe bron is een regel erbij.
REGISTRY: dict[str, type[Source]] = {
    MangaDexSource.type: MangaDexSource,
    ArchiveOrgSource.type: ArchiveOrgSource,
    OpdsSource.type: OpdsSource,
}


def get_source(source_type: str, config: dict[str, Any] | None = None) -> Source:
    """Maak een bron aan op type, zoals opgeslagen in ``Source.type``.

    ``config`` komt uit ``Source.config`` en is wat een bron nodig heeft die je
    zelf toevoegt — bij OPDS het adres van de catalogus. Onbekende sleutels
    negeren we: dan kost een oude instelling geen foutmelding.
    """
    implementation = REGISTRY.get(source_type)
    if implementation is None:
        raise SourceError(f"onbekende bron: {source_type}")
    if not config:
        return implementation()

    velden = inspect.signature(implementation.__init__).parameters
    bruikbaar = {
        sleutel: waarde
        for sleutel, waarde in config.items()
        if sleutel in velden and sleutel not in ("self", "client")
    }
    return implementation(**bruikbaar)


__all__ = [
    "REGISTRY",
    "ArchiveOrgSource",
    "ChapterInfo",
    "MangaDexSource",
    "OpdsSource",
    "RateLimiter",
    "SearchResult",
    "Source",
    "SourceError",
    "get_source",
]
