"""De ``Tracker``-interface (M7, docs/architectuur.md).

Eenrichtingsverkeer: BookPal duwt naar buiten en leest nooit terug. Dat scheelt
alle conflictafhandeling — er is één bron van waarheid (je bibliotheek) en de
tracker is een afgeleide. Het scheelt ook een hele klasse fouten waarbij een
tracker je leesvoortgang zou kunnen overschrijven.

Elke implementatie moet zacht falen. Een tracker die stukgaat mag nooit het
lezen in de weg zitten; dat is de reden dat ``push`` een resultaat teruggeeft
in plaats van een uitzondering te gooien bij het gewone falen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TrackerError(RuntimeError):
    """Onherstelbaar: ontbrekende koppeling, ongeldige instellingen."""


class ReadingStatus(StrEnum):
    """De statussen die beide trackers kennen."""

    READING = "reading"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"
    PLAN_TO_READ = "plan_to_read"


@dataclass(frozen=True, slots=True)
class TrackerEntry:
    """Wat er over één serie naar buiten gaat."""

    series_id: int
    title: str
    #: De id bij deze tracker, uit ``Series.tracker_ids``.
    remote_id: str | None
    status: ReadingStatus
    chapters_read: int = 0
    volumes_read: int = 0
    score: int | None = None


@dataclass(frozen=True, slots=True)
class PushResult:
    """Wat er (zou zijn) gebeurd.

    ``dry_run`` is geen bijzaak: het is de manier om te zien wat een tracker
    zou doen voordat je hem loslaat op je echte lijst.
    """

    entry: TrackerEntry
    pushed: bool
    dry_run: bool
    detail: str = ""

    @property
    def summary(self) -> str:
        wat = "zou pushen" if self.dry_run else ("gepusht" if self.pushed else "overgeslagen")
        return f"{self.title_or_id}: {wat}{f' — {self.detail}' if self.detail else ''}"

    @property
    def title_or_id(self) -> str:
        return self.entry.title or str(self.entry.series_id)


class Tracker(ABC):
    """Wat elke tracker moet kunnen."""

    #: Sleutel in de database (``TrackerAccount.provider``) en in
    #: ``Series.tracker_ids``.
    provider: str

    @abstractmethod
    def __init__(self, credentials: dict[str, Any]) -> None:
        """``credentials`` is ``TrackerAccount.credentials`` — per tracker
        andere sleutels (client_id/secret, tokens), vandaar vormvrij."""

    @abstractmethod
    def push(self, entry: TrackerEntry, *, dry_run: bool) -> PushResult:
        """Werk één serie bij op de tracker."""

    def close(self) -> None:  # noqa: B027 — bewust een optionele hook, niet abstract
        """Ruim netwerkverbindingen op. Standaard niets te doen."""


@dataclass
class PushReport:
    """De uitkomst van een ronde, zoals de API en de UI hem tonen."""

    provider: str
    results: list[PushResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Overgeslagen omdat de tracker al verder stond. Geen fout: dat is precies
    # wat er hoort te gebeuren als je elders verder hebt gelezen.
    skipped: list[str] = field(default_factory=list)

    @property
    def pushed(self) -> int:
        return sum(1 for result in self.results if result.pushed)
