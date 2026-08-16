"""Een heel hoofdstuk in één keer, via de batch-API van Gemini.

Waarom apart van de wachtrij: die doet pagina's één voor één en houdt je bij
tijdens het lezen, met een antwoord binnen tientallen seconden. Dit is het
omgekeerde — je zet een hoofdstuk klaar en komt later terug. Gemeten kostte
een batch van twee pagina's 129 seconden (tekst) en 174 seconden (beeld),
ongeacht of het er twee of tweehonderd zijn: je wacht op de wachtrij van
Google, niet op het rekenen zelf. Daar staat tegenover dat batchwerk bij
Google de helft kost.

Bewust één klus tegelijk, net als bij het ophalen van een deellink: twee
batches tegelijk maken het niet sneller en de melding onduidelijker.

De naam van de lopende opdracht gaat naar de instellingen-tabel. Draait de
container opnieuw op terwijl er een batch loopt, dan is die bij Google gewoon
nog bezig — en zonder die naam zouden we betaald werk laten liggen.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.db import session_scope
from bookpal.library import export
from bookpal.models import Book, Series, Setting
from bookpal.translate import sidecar
from bookpal.translate.base import TranslationError
from bookpal.translate.gemini import API_BASE, build_text_request, parse_result
from bookpal.translate.imagepage import build_colour_request, build_image_request, read_image
from bookpal.translate.modes import TranslateMode
from bookpal.translate.preferences import get_button_mode, get_colour_mode
from bookpal.translate.service import (
    COLOUR_PROVIDER,
    _record,
    colour_base,
    colour_variant,
    plan_pages,
    recompose_to_webp,
    render_for_translation,
)

logger = logging.getLogger(__name__)

#: Wat batchwerk bij Google kost ten opzichte van een gewone aanroep. Uit hun
#: documentatie; wij kunnen het tarief niet uit de API lezen, dus het blijft
#: een richtprijs — net als de bedragen per stand.
BATCH_FACTOR = 0.5

#: Hoe vaak we vragen of de batch klaar is. Ruim: het duurt toch minuten, en
#: elke vraag is een verzoek naar buiten.
POLL_SECONDS = 20.0

#: Waar de naam van de lopende opdracht blijft staan bij een herstart.
STATE_KEY = "batch.lopend"

#: De drie soorten klussen. Expliciet en niet afgeleid van de schakelaars: als
#: je een heel hoofdstuk klaarzet, wil je zelf zeggen wát je klaarzet.
TEKST = "tekst"
HERTEKEND = "hertekend"
KLEUREN = "kleuren"
SOORTEN = (TEKST, HERTEKEND, KLEUREN)


@dataclass
class BatchPlan:
    """Wat een klus gaat inhouden, vóór je hem start."""

    kind: str
    mode: TranslateMode
    pages: list[int]
    price_per_page: float

    @property
    def total(self) -> float:
        return round(len(self.pages) * self.price_per_page, 3)


@dataclass
class BatchState:
    """Wat er op dit moment loopt of als laatste liep."""

    kind: str
    book_id: int
    mode: TranslateMode
    pages: list[int]
    state: str = "bezig"  # bezig | klaar | mislukt
    done: int = 0
    failed: int = 0
    error: str | None = None
    operation: str | None = None
    started_at: float = field(default_factory=time.time)

    @property
    def running(self) -> bool:
        return self.state == "bezig"

    @property
    def total(self) -> int:
        return len(self.pages)


_lock = threading.Lock()
_current: BatchState | None = None


def status() -> BatchState | None:
    with _lock:
        return _current


def plan(session: Session, book: Book, *, kind: str, from_page: int = 0) -> BatchPlan:
    """Welke pagina's er nog moeten, en wat dat ongeveer kost."""
    if kind == KLEUREN:
        mode = get_colour_mode(session)
        pages = _colour_todo(session, book, from_page)
        return BatchPlan(kind=kind, mode=mode, pages=pages, price_per_page=_price(mode))

    if kind == TEKST:
        mode = TranslateMode.TEXT
    elif kind == HERTEKEND:
        # De knopstand, want dit is dezelfde handeling als "volledig" in de
        # lezer — alleen dan voor het hele hoofdstuk. Staat die op tekst, dan
        # is de goedkoopste beeldstand de bedoeling.
        gekozen = get_button_mode(session)
        mode = gekozen if gekozen.is_image else TranslateMode.IMAGE_FAST
    else:
        raise TranslationError(f"onbekende soort klus: {kind!r}")

    pages = plan_pages(
        session,
        book,
        target_lang=settings.translate_lang,
        provider=mode.provider,
        from_page=from_page,
    )
    return BatchPlan(kind=kind, mode=mode, pages=pages, price_per_page=_price(mode))


def _price(mode: TranslateMode) -> float:
    from bookpal.api.translate import _COSTS

    return round(_COSTS.get(str(mode), 0.0) * BATCH_FACTOR, 4)


def _colour_todo(session: Session, book: Book, from_page: int) -> list[int]:
    """Pagina's zonder ingekleurde versie.

    Kijkt op schijf en niet in de database: de sidecar is de waarheid, en na
    een herbouwde database ligt het werk er nog steeds.
    """
    if book.page_count is None:
        return []
    series = session.get(Series, book.series_id)
    todo = []
    for index in range(from_page, book.page_count):
        path = sidecar.variant_path(series, book, index, colour_variant(None))
        if not path.is_file():
            todo.append(index)
    return todo


def start(book_id: int, plan: BatchPlan) -> BatchState:
    """Dien de klus in en volg hem op de achtergrond."""
    global _current
    if not plan.pages:
        raise TranslationError("er is niets te doen voor dit hoofdstuk")
    if not settings.gemini_api_key:
        raise TranslationError("geen Gemini-sleutel ingesteld (BOOKPAL_GEMINI_API_KEY)")

    with _lock:
        if _current is not None and _current.running:
            raise TranslationError("er loopt al een klus")
        state = BatchState(kind=plan.kind, book_id=book_id, mode=plan.mode, pages=list(plan.pages))
        _current = state

    threading.Thread(target=_run, args=(state,), name="bookpal-batch", daemon=False).start()
    return state


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE,
        timeout=300.0,
        headers={"x-goog-api-key": settings.gemini_api_key},
    )


def _run(state: BatchState) -> None:
    try:
        with _client() as client:
            verzoeken, invoer = _requests(state)
            state.operation = _submit(client, state, verzoeken)
            _remember(state)
            payload = _wait(client, state)
            _store(state, invoer, payload)
        state.state = "mislukt" if state.done == 0 and state.failed else "klaar"
        if state.done:
            # Een batch is precies het moment waarop een heel hoofdstuk in één
            # keer compleet kan raken; buiten de sessie hierboven, want die is
            # dicht zodra `_store` klaar is.
            with session_scope() as sessie:
                boek = sessie.get(Book, state.book_id)
                if boek is not None:
                    export.probeer_alle(sessie, boek)
    except (TranslationError, httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("batch %s mislukt: %s", state.kind, exc)
        state.error = str(exc)
        state.state = "mislukt"
    finally:
        _forget()


def _requests(state: BatchState) -> tuple[list[dict[str, Any]], dict[int, bytes]]:
    """De verzoeken zelf, plus de ingestuurde pagina per index.

    Die pagina houden we vast omdat we hem straks nodig hebben: bij inkleuren
    is het origineel de bron van het lijnwerk, en bij het hertekenen is het de
    maat waarop het antwoord teruggeschaald wordt.
    """
    verzoeken: list[dict[str, Any]] = []
    invoer: dict[int, bytes] = {}
    with session_scope() as session:
        book = session.get(Book, state.book_id)
        if book is None:
            raise TranslationError("dit boek bestaat niet meer")
        for index in state.pages:
            if state.kind == KLEUREN:
                image, media_type = colour_base(session, book, index)
                verzoek = build_colour_request(image, media_type)
            elif state.kind == HERTEKEND:
                image, media_type = render_for_translation(session, book, index)
                verzoek = build_image_request(image, media_type, settings.translate_lang)
            else:
                image, media_type = render_for_translation(session, book, index)
                verzoek = build_text_request(image, media_type, settings.translate_lang)
            invoer[index] = image
            verzoeken.append({"request": verzoek, "metadata": {"key": f"p{index}"}})
    return verzoeken, invoer


def _submit(client: httpx.Client, state: BatchState, verzoeken: list[dict[str, Any]]) -> str:
    response = client.post(
        f"/models/{state.mode.model}:batchGenerateContent",
        json={
            "batch": {
                "display_name": f"bookpal-{state.kind}-{state.book_id}",
                "input_config": {"requests": {"requests": verzoeken}},
            }
        },
    )
    if response.status_code >= 400:
        raise TranslationError(f"Gemini gaf {response.status_code} bij het indienen")
    naam = str(response.json().get("name") or "")
    if not naam:
        raise TranslationError("Gemini gaf geen opdrachtnummer terug")
    return naam


def _wait(client: httpx.Client, state: BatchState) -> dict[str, Any]:
    """Wachten tot de batch klaar is, en ondertussen de stand bijhouden."""
    while True:
        time.sleep(POLL_SECONDS)
        response = client.get(f"/{state.operation}")
        if response.status_code >= 400:
            raise TranslationError(f"Gemini gaf {response.status_code} bij het opvragen")
        payload: dict[str, Any] = response.json()
        stats = payload.get("metadata", {}).get("batchStats", {})
        open_nog = int(stats.get("pendingRequestCount", 0) or 0)
        state.done = max(0, state.total - open_nog)
        state.failed = int(stats.get("failedRequestCount", 0) or 0)
        if payload.get("done"):
            return payload


def _store(state: BatchState, invoer: dict[int, bytes], payload: dict[str, Any]) -> None:
    """Zet de antwoorden weg op precies dezelfde plek als het losse werk.

    Alles per pagina in een eigen try: één pagina die terugkomt met een filter
    of een leeg antwoord mag de andere honderd niet weggooien — daar is voor
    betaald.
    """
    antwoorden = payload.get("response", {}).get("inlinedResponses", {}).get("inlinedResponses", [])
    gelukt = 0
    with session_scope() as session:
        book = session.get(Book, state.book_id)
        if book is None:
            raise TranslationError("dit boek bestaat niet meer")
        series = session.get(Series, book.series_id)
        for index, item in zip(state.pages, antwoorden, strict=False):
            if "response" not in item:
                logger.warning("batch: pagina %s kwam niet terug", index)
                continue
            try:
                _store_one(session, book, series, state, index, invoer[index], item["response"])
            except (TranslationError, ValueError, OSError) as exc:
                logger.warning("batch: pagina %s niet bewaard: %s", index, exc)
                continue
            gelukt += 1
    state.done = gelukt
    state.failed = state.total - gelukt


def _store_one(
    session: Session,
    book: Book,
    series: Series | None,
    state: BatchState,
    index: int,
    origineel: bytes,
    response: dict[str, Any],
) -> None:
    taal = settings.translate_lang
    if state.kind == KLEUREN:
        geverfd = read_image(response, origineel, keep_gray=False)
        sidecar.write_bytes(
            sidecar.variant_path(series, book, index, colour_variant(None)),
            recompose_to_webp(origineel, geverfd),
        )
        _record(session, book, index, "src", COLOUR_PROVIDER, {"model": state.mode.model})
        return

    if state.kind == HERTEKEND:
        hertekend = read_image(response, origineel, keep_gray=True)
        sidecar.write_bytes(sidecar.image_path(series, book, index, taal, state.mode), hertekend)
        _record(
            session,
            book,
            index,
            taal,
            state.mode.provider,
            {"full_page": True, "model": state.mode.model},
        )
        return

    resultaat = parse_result(response, state.mode.model)
    payload = resultaat.to_payload()
    sidecar.write_json(sidecar.json_path(series, book, index, taal), payload)
    _record(session, book, index, taal, state.mode.provider, payload)


# -- overleven van een herstart ------------------------------------------


def _remember(state: BatchState) -> None:
    with session_scope() as session:
        row = session.get(Setting, STATE_KEY)
        if row is None:
            row = Setting(key=STATE_KEY, value={})
            session.add(row)
        row.value = {
            "operation": state.operation,
            "kind": state.kind,
            "book_id": state.book_id,
            "mode": str(state.mode),
            "pages": state.pages,
        }
        session.commit()


def _forget() -> None:
    with session_scope() as session:
        row = session.get(Setting, STATE_KEY)
        if row is not None:
            session.delete(row)
            session.commit()


def resume() -> BatchState | None:
    """Een batch die nog liep toen de server stopte weer oppikken.

    Bij Google draait hij gewoon door; zonder dit zouden we betaald werk laten
    liggen omdat niemand het antwoord nog ophaalt.
    """
    global _current
    with session_scope() as session:
        row = session.get(Setting, STATE_KEY)
        if row is None:
            return None
        bewaard = dict(row.value)
    try:
        state = BatchState(
            kind=str(bewaard["kind"]),
            book_id=int(bewaard["book_id"]),
            mode=TranslateMode(str(bewaard["mode"])),
            pages=[int(page) for page in bewaard["pages"]],
            operation=str(bewaard["operation"]),
        )
    except (KeyError, ValueError, TypeError):
        logger.warning("onbruikbare batchstand in instellingen: %r", bewaard)
        _forget()
        return None

    with _lock:
        if _current is not None and _current.running:
            return _current
        _current = state

    def verder() -> None:
        try:
            with _client() as client:
                payload = _wait(client, state)
                verzoeken, invoer = _requests(state)  # alleen voor de originelen
                del verzoeken
                _store(state, invoer, payload)
            state.state = "klaar"
        except (TranslationError, httpx.HTTPError, OSError, ValueError) as exc:
            logger.warning("hervatte batch mislukt: %s", exc)
            state.error = str(exc)
            state.state = "mislukt"
        finally:
            _forget()

    logger.info("batch %s hervat na herstart", state.operation)
    threading.Thread(target=verder, name="bookpal-batch-hervat", daemon=False).start()
    return state


def reset() -> None:
    """Vergeet de laatste klus. Alleen voor tests."""
    global _current
    with _lock:
        _current = None


__all__ = [
    "BATCH_FACTOR",
    "HERTEKEND",
    "KLEUREN",
    "SOORTEN",
    "TEKST",
    "BatchPlan",
    "BatchState",
    "plan",
    "reset",
    "resume",
    "start",
    "status",
]
