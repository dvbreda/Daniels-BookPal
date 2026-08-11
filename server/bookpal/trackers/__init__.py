"""Trackers (M7). Eén interface, per tracker een implementatie."""

from __future__ import annotations

from typing import Any

from bookpal.trackers.base import (
    PushReport,
    PushResult,
    ReadingStatus,
    Tracker,
    TrackerEntry,
    TrackerError,
)
from bookpal.trackers.goodreads import GoodreadsRow, export_csv
from bookpal.trackers.mal import MyAnimeListTracker

#: Tracker-implementaties op ``TrackerAccount.provider``. Goodreads staat er
#: bewust niet in: die is een export, geen live koppeling met eigen
#: credentials, en heeft dus geen ``Tracker``-instantie nodig.
REGISTRY: dict[str, type[Tracker]] = {
    MyAnimeListTracker.provider: MyAnimeListTracker,
}


def get_tracker(provider: str, credentials: dict[str, Any]) -> Tracker:
    implementation = REGISTRY.get(provider)
    if implementation is None:
        raise TrackerError(f"onbekende tracker: {provider}")
    return implementation(credentials)


__all__ = [
    "REGISTRY",
    "GoodreadsRow",
    "MyAnimeListTracker",
    "PushReport",
    "PushResult",
    "ReadingStatus",
    "Tracker",
    "TrackerEntry",
    "TrackerError",
    "export_csv",
    "get_tracker",
]
