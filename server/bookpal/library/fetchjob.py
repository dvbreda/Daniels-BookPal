"""Een deellink ophalen op de achtergrond, met iets om naar te kijken.

Een gedeelde Dropbox-map is zomaar een gigabyte. Dat ophalen in het verzoek
zelf betekent minutenlang een browser die niets zegt, en dat is niet te
onderscheiden van "er gebeurt niets" — precies de klacht die dit oplost.

Bewust simpel gehouden: één klus tegelijk, in het geheugen. Een tweede klus
starten terwijl er één loopt wordt geweigerd in plaats van in een wachtrij
gezet; twee downloads tegelijk maken het alleen maar trager en de melding
onduidelijker. Bij een herstart is de stand weg — dan is de download ook weg,
dus dat is geen verlies dat je moet bijhouden.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bookpal.library import remote

logger = logging.getLogger(__name__)


@dataclass
class FetchJob:
    """Wat er op dit moment binnenkomt."""

    url: str
    folder: str | None = None
    state: str = "bezig"  # bezig | klaar | mislukt
    bytes_done: int = 0
    # Wat de server zei dat er zou komen; vaak weet hij dat zelf niet.
    bytes_total: int | None = None
    saved: list[str] = field(default_factory=list)
    skipped: int = 0
    error: str | None = None

    @property
    def running(self) -> bool:
        return self.state == "bezig"


_lock = threading.Lock()
_current: FetchJob | None = None


def status() -> FetchJob | None:
    """De klus die loopt of als laatste liep."""
    with _lock:
        return _current


def start(url: str, target_dir: Path) -> FetchJob:
    """Begin met ophalen en geef meteen terug wat de stand is.

    Gooit ``RuntimeError`` als er al iets loopt: dan is er niets te starten en
    hoort de client dat te horen in plaats van een tweede download ernaast te
    krijgen.
    """
    global _current
    with _lock:
        if _current is not None and _current.running:
            raise RuntimeError("er wordt al iets opgehaald")
        job = FetchJob(url=url, folder=target_dir.name)
        _current = job

    def loop() -> None:
        try:
            report = remote.download(url, target_dir, on_progress=_note(job))
            with _lock:
                job.saved = report.saved
                job.skipped = report.skipped
                job.state = "klaar"
        except (remote.RemoteError, OSError) as exc:
            logger.warning("ophalen van %s: %s", url, exc)
            with _lock:
                job.error = str(exc)
                job.state = "mislukt"

    # Geen daemon: een halve download afbreken bij het afsluiten laat rommel
    # achter, en de tijdelijke naam wordt alleen opgeruimd als de lus afloopt.
    threading.Thread(target=loop, name="bookpal-fetch", daemon=False).start()
    return job


def _note(job: FetchJob) -> Callable[[int, int | None], None]:
    def bijwerken(gedaan: int, totaal: int | None) -> None:
        with _lock:
            job.bytes_done = gedaan
            job.bytes_total = totaal

    return bijwerken


def reset() -> None:
    """Vergeet de laatste klus. Alleen voor tests."""
    global _current
    with _lock:
        _current = None


__all__ = ["FetchJob", "reset", "start", "status"]
