"""Vooruit downloaden terwijl je leest (M5-bijwerk).

De worker uit M5 haalt hoofdstukken vooruit op, maar op een interval van een
uur. Dat is prima om een serie bij te houden en te trage om achter je aan te
lopen: sla je drie hoofdstukken achter elkaar om, dan sta je bij het vierde
alsnog te wachten.

Deze trigger hangt aan je voortgang in plaats van aan de klok. Hij is
gedebounced per serie, net als de tracker-push van M7 — bij het doorbladeren
komt er tientallen keren per minuut een voortgangsupdate binnen, en die mogen
niet allemaal een downloadronde starten.

Eén thread tegelijk, en met opzet: op een N100 telt het uitserveren van de
pagina die je nú leest zwaarder dan het binnenhalen van de pagina die je
straks misschien leest.
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select

from bookpal.config import settings
from bookpal.db import current_user, session_scope
from bookpal.models import Series, Source, Subscription, SubscriptionPolicy
from bookpal.sources import SourceError, get_source
from bookpal.sources import service as source_service
from bookpal.sources.worker import plan_readahead

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_timers: dict[int, threading.Timer] = {}
# Eén downloadronde tegelijk, ongeacht hoeveel series er triggeren.
_downloading = threading.Lock()


def notify_progress(series_id: int) -> None:
    """Je leest in deze serie; kijk zo of er iets vooruit gehaald moet worden."""
    if not settings.subscriptions_enabled or settings.readahead_debounce_seconds <= 0:
        return
    with _lock:
        existing = _timers.get(series_id)
        if existing is not None:
            existing.cancel()
        timer = threading.Timer(settings.readahead_debounce_seconds, _fire, args=(series_id,))
        timer.daemon = True
        _timers[series_id] = timer
        timer.start()


def _fire(series_id: int) -> None:
    with _lock:
        _timers.pop(series_id, None)
    # Loopt er al een ronde? Dan doet die het werk wel; nog een keer beginnen
    # zou alleen de bandbreedte verdelen over twee series tegelijk.
    if not _downloading.acquire(blocking=False):
        return
    try:
        _download_ahead(series_id)
    except Exception:
        logger.exception("vooruitlezen voor serie %s mislukt", series_id)
    finally:
        _downloading.release()


def _download_ahead(series_id: int) -> None:
    with session_scope() as session:
        subscription = session.scalar(
            select(Subscription).where(Subscription.series_id == series_id)
        )
        if subscription is None:
            return
        series = session.get(Series, series_id)
        source_row = session.get(Source, subscription.source_id)
        if series is None or source_row is None or not source_row.enabled:
            return

        user = current_user(session)
        wanted = plan_readahead(session, subscription, user)
        if not wanted:
            return

        try:
            implementation = get_source(source_row.type)
        except SourceError as exc:
            logger.warning("bron %s niet te starten: %s", source_row.type, exc)
            return

        temporary = subscription.policy is SubscriptionPolicy.READAHEAD
        for book in wanted:
            try:
                source_service.download_book(
                    session,
                    implementation,
                    book,
                    temporary=temporary,
                    ttl_days=subscription.ttl_days,
                )
                session.commit()
                logger.info("vooruit opgehaald: %s %s", series.title, book.number or book.title)
            except SourceError as exc:
                # Eén hoofdstuk dat hapert mag de rest niet tegenhouden.
                logger.warning("vooruitlezen %s: %s", series.title, exc)
                session.rollback()


def stop_all() -> None:
    """Voor tests en een nette shutdown."""
    with _lock:
        for timer in _timers.values():
            timer.cancel()
        _timers.clear()
