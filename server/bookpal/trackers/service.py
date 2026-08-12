"""Tracker naar datamodel: welke status heeft een serie, en wat gaat er naar
buiten (M7, docs/architectuur.md).

Eenrichting: dit leest de bibliotheek en schrijft naar een tracker, nooit
andersom. Er is dus geen conflictafhandeling nodig — de bibliotheek is de ene
bron van waarheid.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

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

logger = logging.getLogger(__name__)


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


def _furthest(finished: list[Book], nummer: Callable[[Book], float]) -> int:
    """Hoe ver je bent: het hoogste nummer dat je uit hebt.

    Tellen hoeveel bestanden er af zijn geeft het verkeerde getal, en op twee
    manieren. Heb je een serie in twee uitgaven — de gekleurde en de
    zwart-witte — dan telt hoofdstuk 5 dubbel en meldt de tracker dat je op 10
    zit. En mist je bibliotheek een paar delen, dan blijft de teller juist
    achter bij waar je werkelijk bent.

    Dit is ook precies de kant op waarmee we voortgang binnenhalen: daar
    markeren we alles tot en met het nummer dat de tracker noemt. Zo blijven
    heen en terug elkaars spiegelbeeld.
    """
    nummers = [
        waarde
        for book in finished
        if (waarde := nummer(book)) > 0 and waarde != float("inf")
    ]
    if not nummers:
        # Niets met een bruikbaar nummer — bij losse boeken is "hoeveel je er
        # uit hebt" dan alsnog het beste antwoord.
        return len(finished)
    return int(max(nummers))


def entry_for_series(session: Session, user: User, series: Series, provider: str) -> TrackerEntry:
    """Bouwt wat er voor deze serie naar de tracker toe zou gaan."""
    books = list(series.books)
    status = reading_status_for(session, user, series)
    finished = _finished_books(session, user, books)
    return TrackerEntry(
        series_id=series.id,
        title=series.title,
        remote_id=series.tracker_ids.get(provider),
        status=status,
        chapters_read=_furthest(finished, lambda book: book.sort_number),
        volumes_read=_furthest(
            [book for book in finished if book.volume], lambda book: book.sort_volume
        ),
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


def remote_progress(tracker: Tracker) -> dict[str, int]:
    """Wat de tracker zelf al denkt, per id.

    Nodig om nooit achteruit te schrijven. Kan een tracker zijn eigen lijst niet
    teruggeven — Goodreads bijvoorbeeld — dan komt er een lege kaart terug en
    valt de bewaking weg; dat is beter dan helemaal niet kunnen pushen.
    """
    lezer = getattr(tracker, "read_list", None)
    if lezer is None:
        return {}
    try:
        return {
            str(item["mal_id"]): int(item.get("chapters_read") or 0) for item in lezer()
        }
    except TrackerError as exc:
        logger.warning("kon de lijst van %s niet lezen: %s", tracker.provider, exc)
        return {}


def _ahead_at_tracker(entry: TrackerEntry, remote: dict[str, int]) -> int | None:
    """Hoe ver de tracker staat, als dat verder is dan wij.

    Je leest ook buiten BookPal om — op papier, in een app, op een ander
    apparaat. Die stand terugzetten naar wat wij toevallig lokaal hebben is
    verlies dat je niet ziet gebeuren.
    """
    if entry.remote_id is None:
        return None
    daar = remote.get(str(entry.remote_id))
    if daar is not None and daar > entry.chapters_read:
        return daar
    return None


def _catch_up(
    session: Session, user: User, entry: TrackerEntry, tot: int, report: PushReport
) -> None:
    """Neem over wat de tracker verder was.

    Het hoogste wint, en dat betekent niet alleen "niet achteruit pushen" maar
    ook: hier bijwerken. Anders blijf je elke ronde hetzelfde verschil zien
    zonder dat het ooit gladgestreken wordt.
    """
    series = session.get(Series, entry.series_id)
    if series is None:
        return
    gemarkeerd, _bekeken = import_progress(session, user, series, tot)
    report.pulled.append(
        f"{entry.title}: {tot} van de tracker overgenomen "
        f"(wij stonden op {entry.chapters_read}, {gemarkeerd} bijgewerkt)"
    )


def push_series(
    session: Session,
    tracker: Tracker,
    account: TrackerAccount,
    user: User,
    series: Series,
    *,
    remote: dict[str, int] | None = None,
) -> PushResult | None:
    """Werk één serie bij — het gerichte pad achter de gedebouncede trigger.

    ``None`` als deze serie geen id voor deze tracker heeft, of als de tracker
    al verder staat dan wij; in beide gevallen is er niets te doen en is dat
    geen fout.
    """
    if account.provider not in series.tracker_ids:
        return None
    entry = entry_for_series(session, user, series, account.provider)
    kaart = remote if remote is not None else remote_progress(tracker)
    verder = _ahead_at_tracker(entry, kaart)
    if verder is not None:
        if not account.dry_run:
            import_progress(session, user, series, verder)
        return None
    return tracker.push(entry, dry_run=account.dry_run)


def push_all(session: Session, tracker: Tracker, account: TrackerAccount, user: User) -> PushReport:
    """Eén ronde: elke serie met een id voor deze tracker bijwerken.

    Faalt zacht per serie — één hapering mag de rest van de ronde niet
    stoppen, en zeker het lezen niet in de weg zitten.
    """
    report = PushReport(provider=account.provider)
    entries = entries_for_provider(session, user, account.provider)
    # Eén keer ophalen wat daar staat, niet per serie: het is één verzoek voor
    # de hele lijst.
    remote = remote_progress(tracker)
    for entry in entries:
        verder = _ahead_at_tracker(entry, remote)
        if verder is not None:
            # Niet alleen niet-achteruit-pushen: die hogere stand hoort hier ook
            # binnen te komen, anders zie je elke ronde hetzelfde verschil.
            if account.dry_run:
                report.skipped.append(
                    f"{entry.title}: de tracker staat op {verder}, wij op "
                    f"{entry.chapters_read} — dat zou hier overgenomen worden"
                )
            else:
                _catch_up(session, user, entry, verder, report)
            continue
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
