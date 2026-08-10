"""CBZ — een zip met paginabeelden."""

from __future__ import annotations

import zipfile
from pathlib import Path

from bookpal.formats.base import (
    MEDIA_TYPES,
    BookFile,
    BookMetadata,
    RawPage,
    is_image,
    natural_key,
)
from bookpal.formats.comicinfo import parse_comicinfo
from bookpal.models import BookKind


class CbzBook(BookFile):
    kind = BookKind.COMIC

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._zip = zipfile.ZipFile(path)
        self._names = sorted(
            (n for n in self._zip.namelist() if is_image(n)),
            key=natural_key,
        )

    def page_count(self) -> int:
        return len(self._names)

    def get_page(self, index: int, target_width: int | None = None) -> RawPage:
        if not 0 <= index < len(self._names):
            raise IndexError(f"pagina {index} bestaat niet ({len(self._names)} pagina's)")
        name = self._names[index]
        data = self._zip.read(name)
        suffix = Path(name).suffix.lower()
        return RawPage(data=data, media_type=MEDIA_TYPES.get(suffix, "application/octet-stream"))

    def metadata(self) -> BookMetadata:
        for name in self._zip.namelist():
            if name.rsplit("/", 1)[-1].lower() == "comicinfo.xml":
                return parse_comicinfo(self._zip.read(name))
        return BookMetadata()

    def close(self) -> None:
        self._zip.close()
