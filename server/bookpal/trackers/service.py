"""Tracker naar datamodel: welke status heeft een serie, en wat gaat er naar
buiten (M7, docs/architectuur.md).

Eenrichting: dit leest de bibliotheek en schrijft naar een tracker, nooit
andersom. Er is dus geen conflictafhandeling nodig — de bibliotheek is de ene
bron van waarheid.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.models import (
    Book,
    BookKind,
    OriginRegion,
    Progress,
    Series,
    TrackerAccount,
    User,
    utcnow,
)
from bookpal.trackers.base import (
    PushReport,
    PushResult,
    ReadingStatus,
    Tracker,
    TrackerEntry,
    TrackerError,
)
from bookpal.trackers.goodreads import GoodreadsRow


def reading_status_for(session: Session, user: User, series: Series) -> ReadingStatus:
    """Onbegonnen, bezig of uitgelezen — afgeleid uit voortgang, niet apart
    bijgehouden. ``ON_HOLD``/``DROPPED`` bestaan bij geen van beide trackers
    automatisch: dat zijn keuzes die je alleen bij de tracker zelf zou maken,
    dus daar bemoeien we ons niet mee.
    """
    books = list(series.books)
    if not books:
        return ReadingStatus.PLAN_TO_READ

    book_ids = [book.id for book in books]
    finished_ids = {
        row.book_id
        for row in session.scalars(
            select(Progress).where(
                Progress.user_id == user.id,
                Progress.finished.is_(True),
                Progress.book_id.in_(book_ids),
            )
        )
    }
    has_any_progress = (
        session.scalar(
            select(Progress.id)
            .where(Progress.user_id == user.id, Progress.book_id.in_(book_ids))
            .limit(1)
        )
        is not None
    )

    books_with_file = [book for book in books if book.file_id is not None]
    all_finished = bool(books_with_file) and all(
        book.id in finished_ids for book in books_with_file
    )

    if all_finished:
        return ReadingStatus.COMPLETED
    if has_any_progress:
        return ReadingStatus.READING
    return ReadingStatus.PLAN_TO_READ


def _finished_books(session: Session, user: User, books: list[Book]) -> list[Book]:
    if not books:
        return []
    finished_ids = {
        row.book_id
        for row in session.scalars(
            select(Progress).where(
                Progress.user_id == user.id,
                Progress.finished.is_(True),
                Progress.book_id.in_([book.id for book in books]),
            )
        )
    }
    return [book for book in books if book.id in finished_ids]


def entry_for_series(session: Session, user: User, series: Series, provider: str) -> TrackerEntry:
    """Bouwt wat er voor deze serie naar de tracker toe zou gaan."""
    books = list(series.books)
    status = reading_status_for(session, user, series)
    finished = _finished_books(session, user, books)
    volumes = {book.volume for book in finished if book.volume}
    return TrackerEntry(
        series_id=series.id,
        title=series.title,
        remote_id=series.tracker_ids.get(provider),
        status=status,
        chapters_read=len(finished),
        volumes_read=len(volumes),
    )


def entries_for_provider(
    session: Session, user: User, provider: str, *, only_with_progress: bool = True
) -> list[TrackerEntry]:
    """Eén entry per serie die een id voor deze tracker heeft.

    ``only_with_progress`` laat series zonder enige leespositie weg — anders
    zou het inschakelen van een tracker in één klap je hele bibliotheek als
    "plan to read" pushen. Voor een export (Goodreads-CSV) wil je juist wél
    de volledige lijst, dus staat die daar uit.
    """
    series_rows = session.scalars(select(Series)).all()
    entries = []
    for series in series_rows:
        if provider not in series.tracker_ids:
            continue
        if not suits_provider(session, series, provider):
            continue
        entry = entry_for_series(session, user, series, provider)
        if only_with_progress and entry.status is ReadingStatus.PLAN_TO_READ:
            continue
        entries.append(entry)
    return entries


def push_series(
    session: Session, tracker: Tracker, account: TrackerAccount, user: User, series: Series
) -> PushResult | None:
    """Werk één serie bij — het gerichte pad achter de gedebouncede trigger.

    ``None`` als deze serie geen id voor deze tracker heeft; dan is er niets
    te doen en is dat geen fout.
    """
    if account.provider not in series.tracker_ids:
        return None
    entry = entry_for_series(session, user, series, account.provider)
    return tracker.push(entry, dry_run=account.dry_run)


def push_all(session: Session, tracker: Tracker, account: TrackerAccount, user: User) -> PushReport:
    """Eén ronde: elke serie met een id voor deze tracker bijwerken.

    Faalt zacht per serie — één hapering mag de rest van de ronde niet
    stoppen, en zeker het lezen niet in de weg zitten.
    """
    report = PushReport(provider=account.provider)
    entries = entries_for_provider(session, user, account.provider)
    for entry in entries:
        try:
            result = tracker.push(entry, dry_run=account.dry_run)
        except TrackerError as exc:
            report.errors.append(f"{entry.title}: {exc}")
            continue
        report.results.append(result)
    return report


def goodreads_rows(session: Session, user: User) -> Iterable[GoodreadsRow]:
    """De hele bibliotheek als Goodreads-rijen — dit is een export, geen
    gedebouncede push, dus hier wél de volledige lijst inclusief onbegonnen."""
    for series in session.scalars(select(Series)).all():
        entry = entry_for_series(session, user, series, "goodreads")
        author = series.authors[0] if series.authors else None
        yield GoodreadsRow(title=series.title, author=author, status=entry.status)


def shelf_rows(
    session: Session, user: User, provider: str = "goodreads"
) -> list[tuple[Series, TrackerEntry, int, float]]:
    """Elke serie met zijn leesstatus, voortgang en aantal hoofdstukken.

    Gedeeld door de export en het overzicht in de instellingen, zodat wat je op
    het scherm ziet precies is wat er de deur uit zou gaan. De ``provider``
    bepaalt of er een id bij zit: bij MyAnimeList kan alleen gepusht worden wat
    zo'n id heeft, en dat wil je juist zien.
    """
    rows: list[tuple[Series, TrackerEntry, int, float]] = []
    for series in session.scalars(select(Series)).all():
        if not suits_provider(session, series, provider):
            continue
        entry = entry_for_series(session, user, series, provider)
        books = list(session.scalars(select(Book).where(Book.series_id == series.id)))
        total = len(books)
        percent = (entry.chapters_read / total * 100.0) if total else 0.0
        rows.append((series, entry, total, percent))
    return rows


# MyAnimeList gaat over manga, niet over boeken. Een kookboek van Monty Don
# hoort daar niet in een lijst te verschijnen, ook niet als "wil ik lezen".
# Goodreads kent juist wél boeken én manga, dus daar filteren we niets weg.
_MAL_SKIP_REGIONS = (OriginRegion.EUROPE, OriginRegion.US)


def suits_provider(session: Session, series: Series, provider: str) -> bool:
    """Hoort deze serie bij deze tracker?

    Voor MyAnimeList: alleen strips, en niet die van duidelijk westerse
    herkomst. Een epub of pdf is per definitie geen manga, en een Europese
    strip hoort er evenmin.
    """
    if provider != "mal":
        return True

    kinds = {
        kind
        for (kind,) in session.execute(
            select(Book.kind).where(Book.series_id == series.id).distinct()
        )
    }
    if kinds and not kinds <= {BookKind.COMIC}:
        return False
    return series.origin_region not in _MAL_SKIP_REGIONS


def import_progress(
    session: Session, user: User, series: Series, chapters_read: int
) -> tuple[int, int]:
    """Markeer wat je bij de tracker al gelezen had als gelezen.

    Op hoofdstuk**nummer** en niet op positie: als je bibliotheek gaten heeft
    (een ontbrekend hoofdstuk, een extra omnibus) zou tellen de grens
    verschuiven en zou je net te veel of te weinig als gelezen wegzetten.

    Wat al uitgelezen is blijft ongemoeid, en er wordt nooit iets terug op
    'ongelezen' gezet — dit vult aan, het overschrijft niet.
    """
    if chapters_read <= 0:
        return 0, 0

    books = list(
        session.scalars(
            select(Book)
            .where(Book.series_id == series.id, Book.sort_number <= float(chapters_read))
            .order_by(Book.sort_volume, Book.sort_number)
        )
    )
    bestaand = {
        row.book_id: row
        for row in session.scalars(
            select(Progress).where(
                Progress.user_id == user.id,
                Progress.book_id.in_([book.id for book in books]),
            )
        )
    }

    gemarkeerd = 0
    for book in books:
        row = bestaand.get(book.id)
        if row is not None and row.finished:
            continue
        if row is None:
            row = Progress(user_id=user.id, book_id=book.id)
            session.add(row)
        row.percent = 100.0
        row.finished = True
        row.position = {"page": max(0, (book.page_count or 1) - 1)}
        row.device = "mal"
        row.updated_at = utcnow()
        gemarkeerd += 1

    session.commit()
    return gemarkeerd, len(books)
