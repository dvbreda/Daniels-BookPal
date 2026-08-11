"""Formaatherkenning en een kleine cache van geopende bestanden."""

from __future__ import annotations

import enum
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path

from bookpal.formats.base import (
    BookFile,
    BookMetadata,
    RawPage,
    TocEntry,
    UnsupportedOperation,
)
from bookpal.models import BookKind


class Format(enum.StrEnum):
    CBZ = "cbz"
    CBR = "cbr"
    CB7 = "cb7"
    EPUB = "epub"
    PDF = "pdf"


SUPPORTED_EXTENSIONS = frozenset({".cbz", ".cbr", ".cb7", ".epub", ".pdf", ".zip", ".rar", ".7z"})

FORMAT_KINDS = {
    Format.CBZ: BookKind.COMIC,
    Format.CBR: BookKind.COMIC,
    Format.CB7: BookKind.COMIC,
    Format.EPUB: BookKind.EPUB,
    Format.PDF: BookKind.PDF,
}

_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_RAR_MAGIC = (b"Rar!\x1a\x07",)
_SEVENZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"
_PDF_MAGIC = b"%PDF"


def detect_format(path: Path) -> Format | None:
    """Bepaal het formaat aan de hand van de inhoud, niet de extensie.

    Misbenoemde bestanden zijn eerder regel dan uitzondering in stripcollecties:
    een ``.cbr`` die eigenlijk een zip is komt constant voor. Sniffen scheelt
    een hoop onnavolgbare fouten verderop.
    """
    try:
        with path.open("rb") as handle:
            magic = handle.read(8)
    except OSError:
        return None

    if magic.startswith(_PDF_MAGIC):
        return Format.PDF
    if magic.startswith(_RAR_MAGIC):
        return Format.CBR
    if magic.startswith(_SEVENZIP_MAGIC):
        return Format.CB7
    if magic.startswith(_ZIP_MAGIC):
        return Format.EPUB if _is_epub(path) else Format.CBZ

    # Geen herkenbare magic; val terug op de extensie.
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return Format.PDF
    if suffix in {".cbz", ".zip"}:
        return Format.CBZ
    if suffix in {".cbr", ".rar"}:
        return Format.CBR
    if suffix in {".cb7", ".7z"}:
        return Format.CB7
    if suffix == ".epub":
        return Format.EPUB
    return None


def _is_epub(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                return archive.read("mimetype").strip() == b"application/epub+zip"
            except KeyError:
                return "META-INF/container.xml" in archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def open_book(path: Path, fmt: Format | None = None) -> BookFile:
    fmt = fmt or detect_format(path)
    if fmt is None:
        raise UnsupportedOperation(f"onbekend formaat: {path.name}")

    # Lokale import houdt de zware afhankelijkheden (PyMuPDF, libarchive) buiten
    # het importpad van wie alleen de formaatherkenning nodig heeft.
    if fmt is Format.CBZ:
        from bookpal.formats.cbz import CbzBook

        return CbzBook(path)
    if fmt in (Format.CBR, Format.CB7):
        from bookpal.formats.cbr import CbrBook

        return CbrBook(path)
    if fmt is Format.EPUB:
        from bookpal.formats.epub import EpubBook

        return EpubBook(path)
    from bookpal.formats.pdf import PdfBook

    return PdfBook(path)


class BookFileCache:
    """Houdt een handvol bestanden open.

    Zonder dit zou elke pagina-aanvraag het archief opnieuw openen — en bij cbr
    zelfs opnieuw uitpakken. De sleutel bevat mtime en grootte, dus een gewijzigd
    bestand levert vanzelf een nieuw exemplaar op.
    """

    def __init__(self, max_entries: int = 4) -> None:
        self._max = max_entries
        self._lock = threading.Lock()
        self._items: OrderedDict[tuple[str, float, int], BookFile] = OrderedDict()

    def get(self, path: Path) -> BookFile:
        stat = path.stat()
        key = (str(path), stat.st_mtime, stat.st_size)
        with self._lock:
            existing = self._items.get(key)
            if existing is not None:
                self._items.move_to_end(key)
                return existing

        book = open_book(path)

        with self._lock:
            # Een andere thread kan ondertussen hetzelfde bestand geopend hebben.
            existing = self._items.get(key)
            if existing is not None:
                book.close()
                self._items.move_to_end(key)
                return existing
            self._items[key] = book
            while len(self._items) > self._max:
                _, evicted = self._items.popitem(last=False)
                evicted.close()
            return book

    def clear(self) -> None:
        with self._lock:
            for book in self._items.values():
                book.close()
            self._items.clear()


book_cache = BookFileCache()

__all__ = [
    "FORMAT_KINDS",
    "SUPPORTED_EXTENSIONS",
    "BookFile",
    "BookFileCache",
    "BookMetadata",
    "Format",
    "RawPage",
    "TocEntry",
    "UnsupportedOperation",
    "book_cache",
    "detect_format",
    "open_book",
]
