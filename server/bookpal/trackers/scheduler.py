"""Gedebouncede tracker-push na een voortgangsupdate (M7).

De architectuur is expliciet: pushen gebeurt "bij het uitlezen van een
hoofdstuk of boek, gedebounced per serie" — niet bij elke paginawissel apart,
dat zou een tracker met tientallen aanroepen per leessessie bestoken. Elke
voortgangsupdate reset een timer per serie; pas als het een paar seconden
stil is gebleven, gaat de push voor precies díe serie uit — nooit de rest van
de bibliotheek, ook niet als er meerdere accounts of tracker-ids zijn.

Dry-run staat bij een nieuw account standaard aan (``TrackerAccount.dry_run``),
dus deze trigger is uit zichzelf onschadelijk: hij *rapporteert* pas
daadwerkelijk iets zodra je dat bewust aanzet.
"""

from __future__ import annotations

import logging
import threading

from bookpal.config import settings
from bookpal.db import current_user, session_scope
from bookpal.models import Series, TrackerAccount, utcnow
from bookpal.trackers import REGISTRY, get_tracker
from bookpal.trackers.base import TrackerError
from bookpal.trackers.service import push_series

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_timers: dict[int, threading.Timer] = {}


def notify_progress(series_id: int) -> None:
    """Een boek in deze serie kreeg zonet voortgang. Reset de debounce-timer."""
    if not settings.trackers_enabled:
        return
    with _lock:
        existing = _timers.get(series_id)
        if existing is not None:
            existing.cancel()
        timer = threading.Timer(settings.tracker_debounce_seconds, _fire, args=(series_id,))
        timer.daemon = True
        _timers[series_id] = timer
        timer.start()


def _fire(series_id: int) -> None:
    with _lock:
        _timers.pop(series_id, None)
    try:
        _push_series(series_id)
    except Exception:
        logger.exception("tracker-push voor serie %s mislukt", series_id)


def _push_series(series_id: int) -> None:
    with session_scope() as session:
        series = session.get(Series, series_id)
        if series is None:
            return
        user = current_user(session)
        accounts = session.query(TrackerAccount).filter_by(enabled=True).all()
        for account in accounts:
            # Bv. goodreads: alleen een export, geen live koppeling om naar
            # te pushen.
            if account.provider not in REGISTRY:
                continue
            try:
                tracker = get_tracker(account.provider, account.credentials)
            except TrackerError as exc:
                logger.warning("tracker %s niet te starten: %s", account.provider, exc)
                continue
            try:
                result = push_series(session, tracker, account, user, series)
            except TrackerError as exc:
                logger.warning("tracker %s voor serie %s: %s", account.provider, series.title, exc)
                continue
            finally:
                tracker.close()
            if result is not None:
                account.last_sync_at = utcnow()
                logger.info("tracker %s: %s", account.provider, result.summary)


def stop_all() -> None:
    """Voor tests en een nette shutdown: alle openstaande timers afbreken."""
    with _lock:
        for timer in _timers.values():
            timer.cancel()
        _timers.clear()
