"""PDF via PyMuPDF.

In tegenstelling tot cbz/cbr bestaan de pagina's hier nog niet als beeld; ze
worden gerenderd. Daarom gebruikt deze adapter de ``target_width``-hint: direct
op de gevraagde breedte renderen scheelt zowel geheugen als tijd ten opzichte
van groot renderen en daarna verkleinen — wat op een N100 het verschil maakt.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from bookpal.formats.base import BookFile, BookMetadata, RawPage, TocEntry
from bookpal.models import BookKind

# Waar PyMuPDF standaard op rendert; de schaalfactor rekent hier vanaf.
BASE_DPI = 72.0
DEFAULT_DPI = 150.0
MAX_SCALE = 6.0


class PdfBook(BookFile):
    kind = BookKind.PDF

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._doc = pymupdf.open(path)

    def page_count(self) -> int:
        return int(self._doc.page_count)

    def _scanned_width(self, page: pymupdf.Page) -> int | None:
        """De pixelbreedte van een gescande pagina, als het er één beeld is.

        Een pdf heeft geen eigen resolutie: hij wordt gerenderd op de breedte
        die je vraagt. Bij een gescande strip zit daar één beeld in van een
        vaste grootte, en daarboven renderen levert alleen grotere bestanden op
        zonder één detail extra — bij het vertalen betaal je dat in tokens.

        Alleen bij precies één beeld op de pagina. Een pdf met losse panelen of
        met tekst erin moet gewoon op de gevraagde breedte gerenderd worden,
        anders wordt die juist onleesbaar.
        """
        try:
            beelden = page.get_images(full=True)
        except (RuntimeError, ValueError):
            return None
        if len(beelden) != 1:
            return None
        breedte = int(beelden[0][2] or 0)
        return breedte or None

    def get_page(self, index: int, target_width: int | None = None) -> RawPage:
        if not 0 <= index < self.page_count():
            raise IndexError(f"pagina {index} bestaat niet ({self.page_count()} pagina's)")
        page = self._doc.load_page(index)
        if target_width:
            gescand = self._scanned_width(page)
            if gescand:
                target_width = min(target_width, gescand)
            width_pt = page.rect.width or 1.0
            scale = min(target_width / width_pt, MAX_SCALE)
        else:
            scale = DEFAULT_DPI / BASE_DPI
        scale = max(scale, 0.1)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return RawPage(data=pixmap.tobytes("png"), media_type="image/png")

    def metadata(self) -> BookMetadata:
        meta = BookMetadata()
        info = self._doc.metadata or {}
        meta.title = (info.get("title") or "").strip() or None
        author = (info.get("author") or "").strip()
        if author:
            meta.authors = [part.strip() for part in author.split(",") if part.strip()]
        keywords = (info.get("keywords") or "").strip()
        if keywords:
            meta.tags = [
                part.strip() for part in keywords.replace(";", ",").split(",") if part.strip()
            ]
        meta.summary = (info.get("subject") or "").strip() or None
        return meta

    def toc(self) -> list[TocEntry]:
        entries: list[TocEntry] = []
        for level, title, page_no in self._doc.get_toc():
            entries.append(
                TocEntry(title=str(title), target=str(page_no - 1), level=int(level) - 1)
            )
        return entries

    def close(self) -> None:
        self._doc.close()
