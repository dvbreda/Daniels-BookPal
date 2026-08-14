"""Achtergrondwerk voor abonnementen (M5).

Drie taken, in deze volgorde:

1. **Bijwerken** — nieuwe hoofdstukken van de bron ophalen als boeken zonder
   bestand.
2. **Vooruitlezen** — de eerstvolgende ``readahead_n`` ongelezen hoofdstukken
   binnenhalen, zodat je verder kunt lezen zonder te wachten (en zonder net.
   Handig op de Kobo, die vaak offline is).
3. **Opruimen** — verlopen tijdelijke downloads weggooien.

De planning zit in ``plan_readahead`` als pure functie: die is los te testen
zonder netwerk, en dat is precies het stuk waar de logica in zit.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.db import session_scope
from bookpal.models import (
    Book,
    Progress,
    Series,
    Source,
    Subscription,
    SubscriptionPolicy,
    User,
    utcnow,
)
from bookpal.sources import get_source
from bookpal.sources import service as source_service
from bookpal.sources.base import SourceError

logger = logging.getLogger(__name__)


@dataclass
class RunReport:
    """Wat één ronde heeft gedaan. Ook het antwoord van de handmatige trigger."""

    subscriptions: int = 0
    chapters_added: int = 0
    downloaded: int = 0
    expired: int = 0
    errors: list[str] = field(default_factory=list)


def plan_readahead(session: Session, subscription: Subscription, user: User) -> list[Book]:
    """Welke hoofdstukken zou deze ronde moeten ophalen?

    "Vooruit" betekent: vanaf het eerste hoofdstuk dat je nog niet uit hebt.
    Alles daarvóór laten we met rust, ook als het geen bestand heeft — dat is
    al gelezen of bewust overgeslagen, en opnieuw ophalen zou de bandbreedte
    verspillen die juist voor het vooruitlezen bedoeld is.
    """
    if subscription.readahead_n <= 0:
        return []

    books = list(
        session.scalars(
            select(Book)
            .where(Book.series_id == subscription.series_id)
            .order_by(Book.sort_volume, Book.sort_number, Book.id)
        )
    )
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

    # Begin bij het eerste nog niet uitgelezen deel.
    start = 0
    for index, book in enumerate(books):
        if book.id not in finished_ids:
            start = index
            break
    else:
        # Alles uit: niets vooruit te lezen.
        return []

    wanted: list[Book] = []
    for book in books[start:]:
        if len(wanted) >= subscription.readahead_n:
            break
        if book.file_id is None and book.source_ref:
            wanted.append(book)
    return wanted


def run_once(session: Session, *, refresh: bool = True, download: bool = True) -> RunReport:
    """Eén ronde over alle abonnementen."""
    report = RunReport()
    user = session.scalars(select(User).order_by(User.id)).first()
    if user is None:
        return report

    subscriptions = list(session.scalars(select(Subscription).order_by(Subscription.id)))
    report.subscriptions = len(subscriptions)

    for subscription in subscriptions:
        series = session.get(Series, subscription.series_id)
        source_row = session.get(Source, subscription.source_id)
        if series is None or source_row is None or not source_row.enabled:
            continue

        try:
            implementation = get_source(source_row.type, source_row.config)
        except SourceError as exc:
            report.errors.append(f"{source_row.name}: {exc}")
            continue

        # De reeks van dít abonnement. Een serie kan er meerdere hebben — een
        # gekleurde uitgave naast de zwart-witte — en dan wijst Series.source_ref
        # er maar naar één. Zonder dit onderscheid haalt elk abonnement de
        # hoofdstukken van dezelfde reeks op.
        ref = subscription.source_ref or series.source_ref
        if refresh and ref:
            try:
                # Ook de serie-metadata zelf bijwerken, niet alleen de
                # hoofdstukkenlijst: auteur, omslag en tracker-ids komen bij een
                # bron later nog wel eens goed te staan, en zonder deze aanroep
                # zou een serie voor altijd blijven zitten met wat er toevallig
                # bekend was op de dag dat je 'm ging volgen. Eén extra verzoek
                # naast de gepagineerde hoofdstukkenfeed valt in het niet.
                detail = implementation.detail(ref)
                source_service.upsert_series(session, source_row, detail)
                chapters = implementation.chapters(ref, language=subscription.language)
                added, _ = source_service.sync_chapters(
                    session,
                    series,
                    chapters,
                    subscription=subscription,
                    source_title=detail.title,
                )
                report.chapters_added += added
                subscription.last_checked_at = utcnow()
                session.commit()
            except SourceError as exc:
                # Eén bron die hapert mag de rest van de ronde niet stoppen.
                report.errors.append(f"{series.title}: {exc}")
                session.rollback()

        if not download:
            continue

        temporary = subscription.policy is SubscriptionPolicy.READAHEAD
        for book in plan_readahead(session, subscription, user):
            try:
                source_service.download_book(
                    session,
                    implementation,
                    book,
                    temporary=temporary,
                    ttl_days=subscription.ttl_days,
                )
                session.commit()
                report.downloaded += 1
            except SourceError as exc:
                report.errors.append(f"{series.title} {book.number or book.id}: {exc}")
                session.rollback()
                break  # bron hapert; volgende serie

    report.expired = source_service.expire_downloads(session)
    session.commit()
    return report


class SubscriptionWorker:
    """Draait ``run_once`` op een interval in een achtergrond-thread.

    Bewust een thread en geen asyncio-taak: het ophalen zelf is synchroon
    (httpx + zipfile), en dat hoort niet in de event loop van de API.
    """

    def __init__(self, interval_seconds: float) -> None:
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="bookpal-subscriptions", daemon=True
        )
        self._thread.start()
        logger.info("abonnementen-worker gestart, elke %s minuten", self.interval / 60)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _loop(self) -> None:
        # Niet meteen bij het opstarten: laat de server eerst rustig beginnen.
        while not self._stop.wait(self.interval):
            try:
                with session_scope() as session:
                    report = run_once(session)
                if report.downloaded or report.chapters_added or report.expired:
                    logger.info(
                        "abonnementen: %s nieuw, %s opgehaald, %s verlopen",
                        report.chapters_added,
                        report.downloaded,
                        report.expired,
                    )
                for error in report.errors:
                    logger.warning("abonnementen: %s", error)
            except Exception:
                logger.exception("abonnementen-ronde mislukt")


_worker: SubscriptionWorker | None = None


def start_worker() -> SubscriptionWorker | None:
    """Start de worker als hij aan staat in de instellingen."""
    global _worker
    if not settings.subscriptions_enabled:
        return None
    if _worker is None:
        _worker = SubscriptionWorker(settings.subscriptions_interval_minutes * 60)
        _worker.start()
    return _worker


def stop_worker() -> None:
    global _worker
    if _worker is not None:
        _worker.stop()
        _worker = None
