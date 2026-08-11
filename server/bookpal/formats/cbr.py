"""CBR — een RAR met paginabeelden, gelezen via libarchive.

Bewust libarchive en niet ``unrar``: libarchive leest ook RAR5, zit als
systeembibliotheek overal in, en heeft geen licentie die met distributie
botst.

RAR is een sequentieel formaat, dus willekeurig naar pagina 80 springen zou
telkens het hele archief opnieuw doorlopen. Daarom pakken we bij de eerste
pagina-aanvraag alles één keer uit naar een tijdelijke map; daarna is elke
pagina een gewone bestandslezing. De beeldcache ervóór zorgt dat dit per boek
hooguit één keer per serverstart gebeurt.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import libarchive

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


class CbrBook(BookFile):
    kind = BookKind.COMIC

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._tempdir: Path | None = None
        self._extracted: dict[str, Path] = {}
        self._comicinfo: bytes | None = None
        self._names: list[str] = []
        self._scan()

    def _scan(self) -> None:
        """Loop het archief één keer door voor de inhoudsopgave."""
        names: list[str] = []
        with libarchive.file_reader(str(self.path)) as archive:
            for entry in archive:
                name = str(entry.pathname)
                if entry.isdir:
                    continue
                if is_image(name):
                    names.append(name)
                elif name.rsplit("/", 1)[-1].lower() == "comicinfo.xml":
                    self._comicinfo = b"".join(entry.get_blocks())
        self._names = sorted(names, key=natural_key)

    def _ensure_extracted(self) -> None:
        if self._tempdir is not None:
            return
        tempdir = Path(tempfile.mkdtemp(prefix="bookpal-cbr-"))
        self._tempdir = tempdir
        wanted = set(self._names)
        with libarchive.file_reader(str(self.path)) as archive:
            for entry in archive:
                name = str(entry.pathname)
                if name not in wanted:
                    continue
                # Plat wegschrijven op index: archiefpaden mogen niet buiten de
                # tijdelijke map wijzen.
                target = tempdir / f"{self._names.index(name):06d}{Path(name).suffix.lower()}"
                with target.open("wb") as handle:
                    for block in entry.get_blocks():
                        handle.write(block)
                self._extracted[name] = target

    def page_count(self) -> int:
        return len(self._names)

    def get_page(self, index: int, target_width: int | None = None) -> RawPage:
        if not 0 <= index < len(self._names):
            raise IndexError(f"pagina {index} bestaat niet ({len(self._names)} pagina's)")
        self._ensure_extracted()
        name = self._names[index]
        extracted = self._extracted.get(name)
        if extracted is None or not extracted.exists():
            raise OSError(f"kon pagina {index} niet uitpakken uit {self.path.name}")
        suffix = Path(name).suffix.lower()
        return RawPage(
            data=extracted.read_bytes(),
            media_type=MEDIA_TYPES.get(suffix, "application/octet-stream"),
        )

    def metadata(self) -> BookMetadata:
        if self._comicinfo is not None:
            return parse_comicinfo(self._comicinfo)
        return BookMetadata()

    def close(self) -> None:
        if self._tempdir is not None:
            shutil.rmtree(self._tempdir, ignore_errors=True)
            self._tempdir = None
            self._extracted.clear()
