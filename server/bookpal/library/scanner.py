"""De bibliotheekscanner.

Incrementeel van opzet: een bestand waarvan grootte en mtime niet veranderd
zijn wordt niet eens geopend. Dat is het verschil tussen een rescan van seconden
en één van een half uur op een collectie van duizenden bestanden.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.formats import FORMAT_KINDS, SUPPORTED_EXTENSIONS, detect_format, open_book
from bookpal.formats.base import BookMetadata
from bookpal.metadata import (
    from_embedded,
    from_root_default,
    normalise_number,
    parse_filename,
    resolve,
    sort_title,
)
from bookpal.metadata.origin import Origin
from bookpal.models import Book, BookKind, File, LibraryRoot, OriginRegion, Series, utcnow

logger = logging.getLogger(__name__)

# Hoeveel bytes er in de vinger-afdruk gaan. Een volledige hash van een cbz van
# een halve gigabyte kost meer dan hij oplevert; kop plus grootte is genoeg om
# duplicaten te herkennen.
HASH_BYTES = 65536

# Als een root ineens leeg lijkt terwijl er nog zoveel bestanden in de database
# staan, gaan we ervan uit dat de mount weg is in plaats van dat de collectie
# verdwenen is.
EMPTY_ROOT_GUARD = 5


class ScanAborted(Exception):
    """De root is onbereikbaar of verdacht leeg — we raken de database niet aan."""


@dataclass(slots=True)
class ScanResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


def partial_hash(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    digest.update(str(size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(HASH_BYTES))
    return digest.hexdigest()


def iter_book_files(root_path: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if any(part.startswith(".") or part == "__MACOSX" for part in path.parts):
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            found.append(path)
    return found


def _series_title(meta: BookMetadata, path: Path, root_path: Path, kind: BookKind) -> str:
    """De serie waar dit bestand bij hoort, van sterk naar zwak signaal.

    Expliciete metadata wint altijd. Daarna loopt het uiteen per soort, en dat
    verschil is wezenlijk:

    * **Strips** — een eigen submap betekent een serie. Wie zijn bestanden in
      ``Crayon Shin-Chan/`` zet, zegt daarmee dat het één reeks is; hetzelfde
      uitgangspunt als Komga en Kavita. De bestandsnaam is hier het zwakste
      signaal, want de titel staat er lang niet altijd vooraan:
      ``Vol.15 Ch.005.002 - Part 002 - ... - Crayon Shin-chan.cbz`` levert bij
      ontleden per hoofdstuk een eigen "serie" op, en één map wordt tachtig
      reeksen.
    * **Boeken** — een map is daar juist meestal een categorie ("boeken",
      "sci-fi") en niet een reeks. Een epub of pdf is in zijn eentje een boek,
      dus de eigen titel gaat vóór de map.
    """
    if meta.series:
        return meta.series.strip()

    parent = path.parent
    in_subfolder = parent != root_path

    if kind is BookKind.COMIC:
        if in_subfolder:
            return parent.name
        parsed = parse_filename(path.stem)
        return parsed.series or path.stem

    # Boeken: eigen titel eerst, map als laatste redmiddel.
    if meta.title:
        return meta.title.strip()
    parsed = parse_filename(path.stem)
    if parsed.series:
        return parsed.series
    if in_subfolder:
        return parent.name
    return path.stem


def _get_or_create_series(
    session: Session, root: LibraryRoot, title: str, folder: Path | None
) -> Series:
    existing = session.scalar(
        select(Series).where(Series.library_root_id == root.id, Series.title == title)
    )
    if existing is not None:
        return existing
    series = Series(
        title=title,
        sort_title=sort_title(title),
        library_root_id=root.id,
        folder_path=str(folder) if folder else None,
    )
    session.add(series)
    session.flush()
    return series


def _apply_origin(series: Series, meta: BookMetadata, root: LibraryRoot, kind: BookKind) -> None:
    """Werk de herkomst bij volgens de keten uit ``metadata.origin``.

    Een handmatige keuze blijft staan doordat ``resolve`` de huidige waarde als
    kandidaat meeneemt met zijn eigen rangorde.
    """
    current = Origin(
        language=series.origin_language,
        country=series.origin_country,
        region=series.origin_region,
        source=series.origin_source,
    )
    embedded = from_embedded(
        publisher=meta.publisher or meta.raw.get("Publisher"),
        language=meta.language or meta.raw.get("LanguageISO"),
        manga_flag=meta.raw.get("Manga"),
        weak_language_ok=kind is BookKind.COMIC,
    )
    root_default = from_root_default(root.default_origin_language, root.default_origin_region)
    best = resolve(embedded, root_default, current=current)
    series.origin_language = best.language
    series.origin_country = best.country
    series.origin_region = best.region
    series.origin_source = best.source


def _index_file(session: Session, root: LibraryRoot, path: Path, file_row: File) -> None:
    """Lees het bestand uit en werk Series en Book bij."""
    fmt = detect_format(path)
    if fmt is None:
        raise ValueError(f"onbekend formaat: {path.name}")

    with open_book(path, fmt) as book_file:
        meta = book_file.metadata()
        page_count = book_file.page_count()

    parsed = parse_filename(path.stem)
    root_path = Path(root.path)
    series_title = _series_title(meta, path, root_path, FORMAT_KINDS[fmt])
    folder = path.parent.relative_to(root_path) if path.parent != root_path else None
    series = _get_or_create_series(session, root, series_title, folder)

    if meta.publisher and not series.publisher:
        series.publisher = meta.publisher
    if meta.tags:
        series.tags = list(dict.fromkeys([*series.tags, *meta.tags]))
    if meta.summary and not series.summary:
        series.summary = meta.summary
    _apply_origin(series, meta, root, FORMAT_KINDS[fmt])

    number = meta.number or parsed.number
    book = session.scalar(select(Book).where(Book.file_id == file_row.id))
    if book is None:
        book = Book(series_id=series.id, file_id=file_row.id, kind=FORMAT_KINDS[fmt], title="")
        session.add(book)

    if book.source_ref is not None:
        # Dit hoofdstuk komt van een abonnement (M5) en is daar al ingedeeld en
        # benoemd. De scanner weet hier minder dan de bron: de bestandsnaam van
        # een download zegt niets over volgorde of titel, en het boek staat in
        # de serie van het abonnement. Alleen wat de scanner écht als enige
        # weet — dat het bestand er is en hoeveel pagina's het heeft — mag hij
        # bijwerken. Zonder deze uitzondering trok elke scan zulke hoofdstukken
        # uit hun abonnement en in een serie die op de mapnaam was verzonnen.
        book.page_count = page_count
        session.flush()
        return

    book.series_id = series.id
    book.kind = FORMAT_KINDS[fmt]
    book.title = meta.title or parsed.title or path.stem
    book.number = number
    book.sort_number = normalise_number(number)
    book.volume = meta.volume or parsed.volume
    book.sort_volume = normalise_number(book.volume)
    book.page_count = page_count
    # Manga leest van rechts naar links; het ComicInfo-veld is de enige plek
    # waar dat expliciet in staat.
    book.right_to_left = meta.right_to_left or series.origin_region is OriginRegion.JAPAN
    session.flush()


def scan_root(session: Session, root: LibraryRoot, *, force: bool = False) -> ScanResult:
    """Scan één library-root.

    ``force`` negeert de mtime-controle en leest elk bestand opnieuw uit.
    """
    result = ScanResult()
    root_path = Path(root.path)
    if not root_path.is_dir():
        raise ScanAborted(f"library-root {root.path!r} is niet bereikbaar")

    known_count = session.scalar(select(File.id).where(File.library_root_id == root.id).limit(1))
    on_disk = iter_book_files(root_path)
    if not on_disk and known_count is not None:
        existing_total = len(
            session.scalars(select(File.id).where(File.library_root_id == root.id)).all()
        )
        if existing_total >= EMPTY_ROOT_GUARD:
            # Vrijwel zeker een niet-gemounte NAS-share. Niets verwijderen.
            raise ScanAborted(
                f"library-root {root.path!r} is leeg terwijl er {existing_total} bestanden "
                "bekend zijn — mount waarschijnlijk niet beschikbaar, scan afgebroken"
            )

    existing_files = {
        row.path: row
        for row in session.scalars(select(File).where(File.library_root_id == root.id))
    }
    seen: set[str] = set()

    for path in on_disk:
        key = str(path)
        seen.add(key)
        try:
            stat = path.stat()
        except OSError as exc:
            result.errors.append(f"{path.name}: {exc}")
            continue

        file_row = existing_files.get(key)
        unchanged = (
            file_row is not None
            and not force
            and not file_row.missing
            and file_row.size == stat.st_size
            and abs(file_row.mtime - stat.st_mtime) < 0.001
        )
        if unchanged:
            result.unchanged += 1
            continue

        is_new = file_row is None
        if file_row is None:
            file_row = File(
                library_root_id=root.id,
                path=key,
                size=stat.st_size,
                mtime=stat.st_mtime,
                extension=path.suffix.lower(),
            )
            session.add(file_row)
        else:
            file_row.size = stat.st_size
            file_row.mtime = stat.st_mtime
            file_row.extension = path.suffix.lower()
            file_row.missing = False
        session.flush()

        try:
            file_row.content_hash = partial_hash(path, stat.st_size)
            _index_file(session, root, path, file_row)
        except Exception as exc:  # één kapot bestand mag de scan niet stoppen
            logger.warning("kon %s niet indexeren: %s", path, exc)
            result.errors.append(f"{path.name}: {exc}")
            session.flush()
            continue

        if is_new:
            result.added += 1
        else:
            result.updated += 1

    for path_str, file_row in existing_files.items():
        if path_str in seen:
            continue
        session.delete(file_row)
        result.removed += 1

    session.flush()
    _prune(session, root)
    root.last_scan_at = utcnow()
    session.flush()
    return result


def _prune(session: Session, root: LibraryRoot) -> None:
    """Ruim boeken op zonder bestand én zonder bron, en daarna lege series.

    Een geabonneerd hoofdstuk (``source_ref``) blijft staan als de tijdelijke
    download verdwijnt — dat is precies het punt van readahead.
    """
    orphan_books = session.scalars(
        select(Book)
        .join(Series, Book.series_id == Series.id)
        .where(
            Series.library_root_id == root.id,
            Book.file_id.is_(None),
            Book.source_ref.is_(None),
        )
    ).all()
    for book in orphan_books:
        session.delete(book)
    session.flush()

    empty_series = session.scalars(
        select(Series).where(Series.library_root_id == root.id, ~Series.books.any())
    ).all()
    for series in empty_series:
        session.delete(series)
    session.flush()


def scan_all(session: Session, *, force: bool = False) -> dict[str, ScanResult]:
    results: dict[str, ScanResult] = {}
    for root in session.scalars(select(LibraryRoot).where(LibraryRoot.enabled.is_(True))):
        try:
            results[root.name] = scan_root(session, root, force=force)
        except ScanAborted as exc:
            failed = ScanResult()
            failed.errors.append(str(exc))
            results[root.name] = failed
    return results
