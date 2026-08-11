"""Bron naar datamodel: abonneren en hoofdstukken binnenhalen (M5).

Het kernidee uit het datamodel: een ``Book`` heeft een bestand **of** een
bron-referentie. Abonneren maakt dus boeken zonder bestand aan; downloaden vult
er een bestand bij zonder de bron-referentie weg te gooien. Daardoor kan de
TTL-opruiming een bestand later weer weghalen zonder dat het hoofdstuk
verdwijnt uit je bibliotheek.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.metadata.origin import Origin, from_online, resolve
from bookpal.models import (
    Book,
    BookKind,
    File,
    LibraryRoot,
    Series,
    Source,
    Subscription,
    SubscriptionPolicy,
    utcnow,
)
from bookpal.sources import ChapterInfo, SearchResult
from bookpal.sources import Source as SourceImpl
from bookpal.sources.base import SourceError

logger = logging.getLogger(__name__)

#: Naam van de map waarin gedownloade hoofdstukken belanden.
DOWNLOAD_ROOT_NAME = "Downloads"

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text: str, *, fallback: str = "zonder-titel", limit: int = 120) -> str:
    """Een titel als mapnaam, zonder tekens die een bestandssysteem breken."""
    cleaned = _UNSAFE.sub("", text).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:limit].strip() or fallback)


def download_root(session: Session) -> LibraryRoot:
    """De library-root voor downloads, aangemaakt als hij nog niet bestaat.

    Bewust een gewone root: gedownloade hoofdstukken lopen daarna door
    dezelfde scanner, formats en beeldpipeline als je eigen bestanden.
    """
    path = str(settings.download_dir.resolve())
    root = session.scalar(select(LibraryRoot).where(LibraryRoot.path == path))
    if root is None:
        settings.download_dir.mkdir(parents=True, exist_ok=True)
        root = LibraryRoot(name=DOWNLOAD_ROOT_NAME, path=path)
        session.add(root)
        session.flush()
    return root


def upsert_series(session: Session, source: Source, result: SearchResult) -> Series:
    """Maak of werk de serie bij die bij een bron-treffer hoort."""
    series = session.scalar(
        select(Series).where(Series.source_id == source.id, Series.source_ref == result.ref)
    )
    if series is None:
        series = Series(
            title=result.title,
            sort_title=result.title.lower(),
            library_root_id=download_root(session).id,
            source_id=source.id,
            source_ref=result.ref,
        )
        session.add(series)
        # Direct flushen, net als de scanner doet: column-defaults (tags,
        # tracker_ids) worden pas dan gevuld.
        session.flush()

    series.summary = result.description or series.summary
    if result.tracker_ids:
        # Let op de `or {}`: column-defaults vullen pas bij het flushen, dus op
        # een net aangemaakte serie staat hier nog None.
        series.tracker_ids = {**(series.tracker_ids or {}), **result.tracker_ids}

    # Stap 2 van de herkomst-keten. resolve() weegt dit tegen wat er al staat,
    # dus een handmatige keuze blijft vanzelf overeind.
    if result.original_language:
        current = Origin(
            series.origin_language,
            series.origin_country,
            series.origin_region,
            series.origin_source,
        )
        chosen = resolve(from_online(result.original_language), current=current)
        series.origin_language = chosen.language
        series.origin_country = chosen.country
        series.origin_region = chosen.region
        series.origin_source = chosen.source

    session.flush()
    return series


def sync_chapters(
    session: Session, series: Series, chapters: list[ChapterInfo]
) -> tuple[int, int]:
    """Zet de hoofdstukkenlijst van een bron om in boeken zonder bestand.

    Geeft (nieuw, ongewijzigd) terug. Bestaande boeken worden niet aangeraakt,
    ook niet als ze inmiddels een bestand hebben.
    """
    existing = {
        book.source_ref: book
        for book in session.scalars(select(Book).where(Book.series_id == series.id))
        if book.source_ref
    }
    added = 0
    for chapter in chapters:
        if chapter.ref in existing:
            continue
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title=chapter.title or _default_title(chapter),
                number=chapter.number,
                volume=chapter.volume,
                sort_number=_sort_number(chapter.number),
                page_count=chapter.page_count,
                # Manga leest van rechts naar links; dat is bij een
                # manga-bron de juiste aanname.
                right_to_left=True,
                source_id=series.source_id,
                source_ref=chapter.ref,
            )
        )
        added += 1
    session.flush()
    return added, len(existing)


def _default_title(chapter: ChapterInfo) -> str:
    parts = []
    if chapter.volume:
        parts.append(f"Vol. {chapter.volume}")
    if chapter.number:
        parts.append(f"Hoofdstuk {chapter.number}")
    return " ".join(parts) or "Hoofdstuk"


def _sort_number(number: str | None) -> float:
    try:
        return float(number) if number is not None else 0.0
    except ValueError:
        return 0.0


def subscribe(
    session: Session,
    source_row: Source,
    implementation: SourceImpl,
    ref: str,
    *,
    policy: SubscriptionPolicy = SubscriptionPolicy.READAHEAD,
    readahead_n: int = 3,
    ttl_days: int = 14,
    language: str = "en",
) -> tuple[Series, Subscription, int]:
    """Volg een serie: serie + hoofdstukken aanmaken en het abonnement vastleggen."""
    detail = implementation.detail(ref)
    series = upsert_series(session, source_row, detail)
    chapters = implementation.chapters(ref, language=language)
    added, _ = sync_chapters(session, series, chapters)

    subscription = session.scalar(
        select(Subscription).where(
            Subscription.source_id == source_row.id, Subscription.series_id == series.id
        )
    )
    if subscription is None:
        subscription = Subscription(source_id=source_row.id, series_id=series.id)
        session.add(subscription)
    subscription.policy = policy
    subscription.readahead_n = readahead_n
    subscription.ttl_days = ttl_days
    subscription.last_checked_at = utcnow()
    session.flush()
    return series, subscription, added


def chapter_path(series: Series, book: Book) -> Path:
    """Waar een gedownload hoofdstuk komt te staan.

    Absoluut, want ``File.path`` is elders in de app ook absoluut en
    ``download_root`` legt de root met een opgelost pad vast.
    """
    parts = []
    if book.volume:
        parts.append(f"v{book.volume}")
    if book.number:
        parts.append(f"c{book.number}")
    stem = " ".join(parts) or (book.source_ref or str(book.id))
    return settings.download_dir.resolve() / safe_name(series.title) / f"{safe_name(stem)}.cbz"


def download_book(
    session: Session,
    implementation: SourceImpl,
    book: Book,
    *,
    data_saver: bool = False,
    temporary: bool = False,
    ttl_days: int = 14,
) -> Book:
    """Haal één hoofdstuk binnen en hang het bestand aan het boek.

    ``temporary`` zet een vervaldatum: dat is het "tijdelijk downloaden om
    vooruit te lezen" uit het datamodel. De bron-referentie blijft staan, dus
    na het opruimen is het hoofdstuk nog steeds zichtbaar — alleen niet meer
    lokaal.
    """
    if book.source_ref is None:
        raise SourceError("dit boek heeft geen bron-referentie om te downloaden")

    # Een file_id alleen zegt niets: het bestand kan weg zijn (opgeruimd,
    # volume kwijt, handmatig verwijderd). Alleen overslaan als het er echt
    # nog staat, anders halen we het gewoon opnieuw op.
    if book.file_id is not None:
        existing = session.get(File, book.file_id)
        if existing is not None and Path(existing.path).is_file():
            return book

    series = session.get(Series, book.series_id)
    if series is None:
        raise SourceError("serie niet gevonden")

    target = chapter_path(series, book)
    implementation.download(book.source_ref, target, data_saver=data_saver)

    stat = target.stat()
    file_row = session.scalar(select(File).where(File.path == str(target)))
    if file_row is None:
        file_row = File(
            library_root_id=download_root(session).id,
            path=str(target),
            size=stat.st_size,
            mtime=stat.st_mtime,
            extension=".cbz",
        )
        session.add(file_row)
        session.flush()
    else:
        file_row.size = stat.st_size
        file_row.mtime = stat.st_mtime
        file_row.missing = False

    book.file_id = file_row.id
    book.expires_at = utcnow() + timedelta(days=ttl_days) if temporary else None
    session.flush()
    logger.info("hoofdstuk %s opgehaald naar %s", book.source_ref, target)
    return book


def expire_downloads(session: Session, *, now: datetime | None = None) -> int:
    """Ruim tijdelijke downloads op waarvan de TTL voorbij is.

    Het bestand gaat weg, het boek blijft: de bron-referentie maakt het straks
    opnieuw op te halen.
    """
    moment = now or utcnow()
    expired = session.scalars(
        select(Book).where(
            Book.expires_at.isnot(None),
            Book.expires_at <= moment,
            Book.file_id.isnot(None),
        )
    ).all()

    removed = 0
    for book in expired:
        file_row = session.get(File, book.file_id) if book.file_id else None
        if file_row is not None:
            Path(file_row.path).unlink(missing_ok=True)
            session.delete(file_row)
        book.file_id = None
        book.expires_at = None
        removed += 1
    session.flush()
    return removed
