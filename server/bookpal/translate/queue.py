"""Achtergrondwachtrij voor bubbelvertaling (M8).

De architectuur vraagt: "de queue geeft prioriteit aan de pagina's vóór je
leespositie, zodat de NAS vooruitloopt op wat je leest". Dat is hier letterlijk
zo gebouwd — de wachtrij is geen FIFO maar een gesorteerde verzameling, en een
voortgangsupdate zet de pagina's vlak vóór je uit vooraan.

Eén thread, en dat is een keuze: op een N100 telt het uitserveren van beeld
zwaarder dan snel vertalen, en het weghalen van gelijktijdige aanroepen scheelt
ook aan de kant van de API-limiet.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from bookpal.config import settings
from bookpal.db import session_scope
from bookpal.models import Book
from bookpal.translate import get_translator
from bookpal.translate.base import TranslationError
from bookpal.translate.imagepage import GeminiPageTranslator
from bookpal.translate.modes import TranslateMode
from bookpal.translate.preferences import get_mode
from bookpal.translate.service import readahead_pages, translate_page, translate_page_as_image

logger = logging.getLogger(__name__)


@dataclass(order=True)
class _Job:
    """Lager sorteert eerder. ``priority`` 0 is "de gebruiker wacht hierop"."""

    priority: int
    book_id: int = field(compare=True)
    page_index: int = field(compare=True)
    target_lang: str = field(compare=True)
    # In welke stand deze pagina gedaan wordt. Meegegeven en niet ter plekke
    # opgehaald: verzet je de schakelaar terwijl de wachtrij loopt, dan hoort
    # wat er al klaarstaat te blijven zoals het bedoeld was.
    mode: TranslateMode = field(default=TranslateMode.TEXT, compare=False)


class TranslationQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._jobs: list[_Job] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Wat er nú onderhanden is, zodat de API kan zeggen "bezig" in plaats
        # van "bestaat niet".
        self._active: tuple[int, int] | None = None

    # -- vullen ---------------------------------------------------------

    def submit(
        self,
        book_id: int,
        pages: list[int],
        target_lang: str,
        *,
        priority: int = 5,
        mode: TranslateMode = TranslateMode.TEXT,
    ) -> int:
        """Zet pagina's in de wachtrij. Dubbelen worden stilgehouden, en een
        pagina die al met een hogere prioriteit klaarstaat, houdt die."""
        added = 0
        with self._lock:
            existing = {
                (job.book_id, job.page_index, job.target_lang, job.mode): job for job in self._jobs
            }
            for page_index in pages:
                key = (book_id, page_index, target_lang, mode)
                current = existing.get(key)
                if current is not None:
                    current.priority = min(current.priority, priority)
                    continue
                job = _Job(priority, book_id, page_index, target_lang, mode)
                self._jobs.append(job)
                existing[key] = job
                added += 1
            self._jobs.sort()
        if added:
            self._wake.set()
        return added

    def notify_reading(self, book_id: int, page_index: int, target_lang: str) -> int:
        """Je bent op deze pagina; zet wat eraan komt vooraan.

        In de stand die je bij "vanzelf" hebt gekozen — en die staat standaard
        op de goedkope, want dit loopt zonder dat je erom vraagt.
        """
        if not settings.gemini_api_key or settings.translate_readahead_pages <= 0:
            return 0
        with session_scope() as session:
            book = session.get(Book, book_id)
            if book is None:
                return 0
            mode = get_mode(session)
            pages = readahead_pages(
                session,
                book,
                target_lang=target_lang,
                provider=mode.provider,
                current_page=page_index,
            )
        return self.submit(book_id, pages, target_lang, priority=1, mode=mode)

    # -- draaien --------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None or not settings.translations_enabled:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bookpal-translate", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _take(self) -> _Job | None:
        with self._lock:
            if not self._jobs:
                return None
            job = self._jobs.pop(0)
            self._active = (job.book_id, job.page_index)
            return job

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._take()
            if job is None:
                self._active = None
                self._wake.wait(timeout=30.0)
                self._wake.clear()
                continue
            try:
                self._do(job)
            except Exception:
                # Eén pagina die klapt mag de wachtrij niet stilzetten.
                logger.exception(
                    "vertalen van boek %s pagina %s mislukt", job.book_id, job.page_index
                )
            finally:
                self._active = None

    def _do(self, job: _Job) -> None:
        if job.mode.is_image:
            self._do_image(job)
            return
        translator = get_translator()
        try:
            with session_scope() as session:
                book = session.get(Book, job.book_id)
                if book is None:
                    return
                translate_page(
                    session,
                    translator,
                    book,
                    job.page_index,
                    target_lang=job.target_lang,
                )
        except TranslationError as exc:
            # Zacht falen: de lezer toont gewoon het origineel. Niet opslaan,
            # zodat een volgende poging het nog eens mag proberen — een
            # rate-limit van vanmiddag is morgen weer weg.
            logger.warning("vertalen mislukt (boek %s p%s): %s", job.book_id, job.page_index, exc)
        finally:
            translator.close()

    def _do_image(self, job: _Job) -> None:
        """Dezelfde lus, maar dan met het beeldmodel.

        Apart gehouden omdat het een andere vertaler en een andere bewaarplek
        heeft; de wachtrij zelf hoeft dat verschil verder niet te kennen.
        """
        translator = GeminiPageTranslator(settings.gemini_api_key, job.mode.model)
        try:
            with session_scope() as session:
                book = session.get(Book, job.book_id)
                if book is None:
                    return
                translate_page_as_image(
                    session,
                    translator,
                    book,
                    job.page_index,
                    target_lang=job.target_lang,
                    mode=job.mode,
                )
        except TranslationError as exc:
            logger.warning(
                "hertekenen mislukt (boek %s p%s): %s", job.book_id, job.page_index, exc
            )
        finally:
            translator.close()

    # -- inzicht --------------------------------------------------------

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._jobs) + (1 if self._active is not None else 0)

    def pending_for(self, book_id: int) -> int:
        """Inclusief de pagina die nú onderhanden is.

        Zonder die telt een pagina die al uit de rij is gehaald maar nog niet
        klaar, als nóch openstaand nóch vertaald — en dan meldt de lezer "klaar"
        terwijl er nog een pagina onderweg is.
        """
        with self._lock:
            active = 1 if self._active is not None and self._active[0] == book_id else 0
            return sum(1 for job in self._jobs if job.book_id == book_id) + active

    def is_active(self, book_id: int, page_index: int) -> bool:
        return self._active == (book_id, page_index)


queue = TranslationQueue()
