"""Gedeelde interface voor alle bestandsformaten.

Elke adapter levert hetzelfde contract op, zodat de scanner, de API en de
beeldpipeline niets van cbz, cbr, epub of pdf hoeven te weten.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bookpal.models import BookKind

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".jxl"})

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
    ".jxl": "image/jxl",
}

_NUM_CHUNK = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple[object, ...]:
    """Sorteersleutel waarbij ``page2`` vóór ``page10`` komt.

    Zonder dit staat pagina 10 tussen 1 en 2, wat in vrijwel elk stripbestand
    zichtbaar misgaat.
    """
    parts = _NUM_CHUNK.split(name.lower())
    return tuple(int(p) if p.isdigit() else p for p in parts)


def is_image(name: str) -> bool:
    if name.endswith("/"):
        return False
    base = name.rsplit("/", 1)[-1]
    if not base or base.startswith("."):
        return False
    # Archieven van macOS bevatten een schaduwmap met resource forks.
    if "__MACOSX" in name:
        return False
    return Path(name).suffix.lower() in IMAGE_EXTENSIONS


@dataclass(slots=True)
class RawPage:
    data: bytes
    media_type: str


@dataclass(slots=True)
class TocEntry:
    title: str
    target: str
    level: int = 0


@dataclass(slots=True)
class BookMetadata:
    """Wat we uit het bestand zelf konden halen. Alles optioneel — de scanner
    vult ontbrekende velden aan vanuit de bestandsnaam."""

    title: str | None = None
    series: str | None = None
    number: str | None = None
    volume: str | None = None
    publisher: str | None = None
    language: str | None = None
    summary: str | None = None
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # Ruwe signalen voor de herkomst-keten (ontwerp 1), bv. ComicInfo's Manga-veld.
    raw: dict[str, Any] = field(default_factory=dict)
    right_to_left: bool = False


class UnsupportedOperation(Exception):
    """Bijvoorbeeld: een pagina als beeld opvragen uit een epub."""


class BookFile(ABC):
    """Een geopend bestand."""

    kind: BookKind

    def __init__(self, path: Path) -> None:
        self.path = path

    @abstractmethod
    def page_count(self) -> int: ...

    @abstractmethod
    def get_page(self, index: int, target_width: int | None = None) -> RawPage:
        """Lever pagina ``index`` als beeld.

        ``target_width`` is een hint: vaste-opmaakformaten renderen meteen op de
        gevraagde breedte in plaats van groot renderen en daarna verkleinen.
        """

    def cover(self) -> RawPage | None:
        if self.page_count() > 0:
            return self.get_page(0)
        return None

    def metadata(self) -> BookMetadata:
        return BookMetadata()

    def toc(self) -> list[TocEntry]:
        return []

    def close(self) -> None:
        return None

    def __enter__(self) -> BookFile:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
