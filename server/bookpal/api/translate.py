"""Tekstwolkjes vertalen (M8).

Twee manieren om aan een vertaalde pagina te komen:

* ``GET  .../translation`` — wat er al ligt. 404 als het er nog niet is, zodat
  de lezer meteen weet dat hij het origineel moet tonen.
* ``POST .../translation`` — maak hem nu, en wacht erop. Dit is de knop "vertaal
  deze pagina"; de wachtrij is voor alles wat niet in beeld staat.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.db import get_session
from bookpal.images import ImageProfile
from bookpal.schemas import (
    BatchPlanOut,
    BatchStartIn,
    BatchStatusOut,
    BubbleOut,
    PageColourInfoOut,
    PageColourOut,
    PageTranslationOut,
    TranslateBookIn,
    TranslateBookOut,
    TranslateModeIn,
    TranslateModeOut,
    TranslatePageIn,
    TranslationStatusOut,
)
from bookpal.translate import batch, get_translator, is_configured, recolour, sidecar
from bookpal.translate.base import PageResult, TranslationError
from bookpal.translate.imagepage import GeminiPageTranslator
from bookpal.translate.modes import TranslateMode
from bookpal.translate.preferences import (
    get_button_mode,
    get_colour_mode,
    get_mode,
    set_button_mode,
    set_colour_mode,
    set_mode,
)
from bookpal.translate.queue import queue
from bookpal.translate.service import (
    AlreadyColour,
    best_available,
    bubbles_for,
    colorise_page,
    find,
    has_colour,
    has_colour_for_language,
    plan_pages,
    read_colour,
    read_page_image,
    render_for_translation,
    render_layer_for,
    translate_page,
    translate_page_as_image,
    translated_pages,
)

from . import deps

router = APIRouter(prefix="/api/books", tags=["translate"])
# De schakelaar hoort niet bij één boek, dus een eigen pad.
settings_router = APIRouter(prefix="/api/translate", tags=["translate"])

PROVIDER = "gemini"


def _lang(value: str | None) -> str:
    return value or settings.translate_lang


def _parse_mode(value: str) -> TranslateMode:
    try:
        return TranslateMode(value)
    except ValueError as exc:
        allowed = ", ".join(str(mode) for mode in TranslateMode)
        raise HTTPException(
            status_code=400, detail=f"onbekende vertaalstand {value!r}; kies uit: {allowed}"
        ) from exc


# Ruwe richtprijzen per pagina in dollar, zodat de keuze in de instellingen niet
# blind is. Gemeten aan de gepubliceerde tarieven en het tokengebruik van een
# echte pagina; bedoeld als orde van grootte, niet als factuur.
_COSTS = {
    str(TranslateMode.TEXT): 0.002,
    str(TranslateMode.IMAGE_FAST): 0.067,
    str(TranslateMode.IMAGE_PRO): 0.134,
}


def _to_out(
    book_id: int,
    page_index: int,
    target_lang: str,
    result: PageResult,
    mode: TranslateMode = TranslateMode.TEXT,
) -> PageTranslationOut:
    return PageTranslationOut(
        book_id=book_id,
        page_index=page_index,
        target_lang=target_lang,
        provider=mode.provider,
        mode=str(mode),
        model=result.model,
        bubbles=[
            BubbleOut(
                box=[bubble.x0, bubble.y0, bubble.x1, bubble.y1],
                source=bubble.source,
                translation=bubble.translation,
                kind=str(bubble.kind),
                bold=bubble.bold,
                italic=bubble.italic,
            )
            for bubble in result.bubbles
        ],
    )


@router.get("/{book_id}/pages/{page_index}/translation", response_model=PageTranslationOut)
def get_page_translation(
    book_id: int,
    page_index: int,
    lang: str | None = Query(default=None, max_length=8),
    session: Session = Depends(get_session),
) -> PageTranslationOut:
    """Wat er voor deze pagina klaarligt, in de beste stand die beschikbaar is.

    "Beste" en niet "de ingestelde stand": als je één pagina met de hand door
    het dure model hebt gehaald, wil je díe zien — ook als de schakelaar daarna
    weer op goedkoop staat. Er is immers al voor betaald.
    """
    book = deps.get_book(session, book_id)
    target_lang = _lang(lang)
    found = best_available(session, book, page_index, target_lang)
    if found is None:
        raise HTTPException(status_code=404, detail="deze pagina is nog niet vertaald")

    mode, row = found
    if mode.is_image:
        # De hybride krijgt onze eigen tekstvlakken mee: het beeldmodel heeft
        # de ballonnen alleen leeggeveegd, de vertaling zetten wij eroverheen.
        result = (
            bubbles_for(session, book, page_index, target_lang)
            if mode.needs_bubbles
            else PageResult(model=str(row.payload.get("model", "")))
        )
        out = _to_out(book.id, page_index, target_lang, result, mode)
        out.full_page = True
        return out
    return _to_out(book.id, page_index, target_lang, PageResult.from_payload(row.payload), mode)


@router.post("/{book_id}/pages/{page_index}/translation", response_model=PageTranslationOut)
def make_page_translation(
    book_id: int,
    page_index: int,
    lang: str | None = Query(default=None, max_length=8),
    force: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> PageTranslationOut:
    """Vertaal deze pagina nu. Duurt tientallen seconden als hij nog niet klaar
    is; daarna komt hij uit de cache."""
    book = deps.get_book(session, book_id)
    target_lang = _lang(lang)
    if not is_configured():
        raise HTTPException(
            status_code=409,
            detail="er is geen Gemini-sleutel ingesteld (BOOKPAL_GEMINI_API_KEY)",
        )

    translator = get_translator()
    try:
        result = translate_page(
            session, translator, book, page_index, target_lang=target_lang, force=force
        )
    except TranslationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        translator.close()

    # Nu we tóch weten waar je zit: zet vast klaar wat eraan komt.
    queue.notify_reading(book.id, page_index + 1, target_lang)
    return _to_out(book.id, page_index, target_lang, result)


@router.post("/{book_id}/pages/{page_index}/full", response_model=PageTranslationOut)
def make_full_page_translation(
    book_id: int,
    page_index: int,
    payload: TranslatePageIn,
    session: Session = Depends(get_session),
) -> PageTranslationOut:
    """Laat een beeldmodel deze ene pagina helemaal hertekenen mét vertaling.

    Altijd een expliciete keuze per aanroep, ook als de schakelaar in de
    instellingen op de goedkope stand staat: deze standen kosten tientallen
    centen per pagina, dus ze horen nooit vanzelf te lopen. De uitkomst wordt
    naast de collectie bewaard, dus een tweede keer kost niets.
    """
    book = deps.get_book(session, book_id)
    target_lang = _lang(payload.lang)
    mode = _parse_mode(payload.mode)
    if not mode.is_image:
        raise HTTPException(
            status_code=400,
            detail="deze knop is voor de beeldstanden; gebruik .../translation voor de tekststand",
        )
    if not is_configured():
        raise HTTPException(
            status_code=409,
            detail="er is geen Gemini-sleutel ingesteld (BOOKPAL_GEMINI_API_KEY)",
        )

    translator = GeminiPageTranslator(settings.gemini_api_key, mode.model)
    try:
        translate_page_as_image(
            session,
            translator,
            book,
            page_index,
            target_lang=target_lang,
            mode=mode,
            force=payload.force,
        )
    except TranslationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        translator.close()

    return PageTranslationOut(
        book_id=book.id,
        page_index=page_index,
        target_lang=target_lang,
        provider=mode.provider,
        mode=str(mode),
        model=translator.model,
        full_page=True,
    )


@router.get("/{book_id}/pages/{page_index}/full")
def get_full_page_translation(
    book_id: int,
    page_index: int,
    lang: str | None = Query(default=None, max_length=8),
    mode: str | None = Query(default=None, max_length=20),
    session: Session = Depends(get_session),
) -> Response:
    """De hertekende pagina zelf. Zonder ``mode`` wint de duurste die er ligt."""
    book = deps.get_book(session, book_id)
    target_lang = _lang(lang)

    wanted = _parse_mode(mode) if mode else None
    if wanted is None:
        found = best_available(session, book, page_index, target_lang)
        if found is None or not found[0].is_image:
            raise HTTPException(status_code=404, detail="deze pagina is nog niet volledig vertaald")
        wanted = found[0]

    data = read_page_image(session, book, page_index, target_lang, wanted)
    if data is None:
        raise HTTPException(status_code=404, detail="deze pagina is nog niet volledig vertaald")
    return Response(
        content=data,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/{book_id}/pages/{page_index}/overlay")
def get_page_overlay(
    book_id: int,
    page_index: int,
    profile: ImageProfile = deps.ProfileDep,
    lang: str | None = Query(default=None, max_length=8),
    session: Session = Depends(get_session),
) -> Response:
    """De vertaallaag als doorzichtige PNG, op de maat van deze pagina.

    Naast de ingebakken variant (``/pages/{n}?translate=nl``), en voor de meeste
    clients de betere: de pagina zelf blijft één gedeelde afbeelding, de laag is
    een fractie van die bytes, en aan- of uitzetten is een laag tonen of
    verbergen in plaats van de pagina opnieuw ophalen. Werkt ook zonder
    JavaScript — twee gestapelde ``img``'s met CSS doen het in de Kobo-browser.
    """
    book = deps.get_book(session, book_id)
    target_lang = _lang(lang)
    row = find(session, book.id, page_index, target_lang, PROVIDER)
    if row is None:
        raise HTTPException(status_code=404, detail="deze pagina is nog niet vertaald")

    try:
        data = render_layer_for(session, book, page_index, profile, row)
    except TranslationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(
        content=data,
        media_type="image/png",
        # Dezelfde sleutel als de cache: de vertaling zit in het pad verwerkt,
        # dus opnieuw vertalen levert een andere URL-inhoud op en mag de
        # browser deze lang vasthouden.
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.post("/{book_id}/translate", response_model=TranslateBookOut)
def translate_book(
    book_id: int,
    payload: TranslateBookIn,
    session: Session = Depends(get_session),
) -> TranslateBookOut:
    """Zet het hele boek in de wachtrij, vanaf ``from_page``."""
    book = deps.get_book(session, book_id)
    target_lang = _lang(payload.lang)
    if not is_configured():
        raise HTTPException(
            status_code=409,
            detail="er is geen Gemini-sleutel ingesteld (BOOKPAL_GEMINI_API_KEY)",
        )
    if book.page_count is None:
        raise HTTPException(status_code=409, detail="dit boek heeft geen vaste pagina's")

    # In de stand die bij "vanzelf" staat: dit is bulkwerk dat op de achtergrond
    # loopt, en die schakelaar is precies de plek waar je bepaalt wat dat mag
    # kosten.
    mode = get_mode(session)
    todo = plan_pages(
        session,
        book,
        target_lang=target_lang,
        provider=mode.provider,
        from_page=payload.from_page,
    )
    queued = queue.submit(book.id, todo, target_lang, mode=mode)
    done = len(_done_pages(session, book.id, target_lang))
    return TranslateBookOut(queued=queued, already_done=done)


def _done_pages(session: Session, book_id: int, target_lang: str) -> set[int]:
    """Welke pagina's er klaar zijn, in welke stand dan ook.

    Niet per stand tellen: voor de balk in de lezer is de vraag "kan ik deze
    pagina vertaald zien", en dan telt een pagina die je met de hand door het
    dure model haalde net zo goed mee.
    """
    gevonden: set[int] = set()
    for stand in TranslateMode:
        gevonden |= translated_pages(session, book_id, target_lang, stand.provider)
    return gevonden


@router.get("/{book_id}/translation-status", response_model=TranslationStatusOut)
def translation_status(
    book_id: int,
    lang: str | None = Query(default=None, max_length=8),
    session: Session = Depends(get_session),
) -> TranslationStatusOut:
    book = deps.get_book(session, book_id)
    target_lang = _lang(lang)
    return TranslationStatusOut(
        book_id=book.id,
        target_lang=target_lang,
        provider=PROVIDER,
        configured=is_configured(),
        page_count=book.page_count,
        translated=len(_done_pages(session, book.id, target_lang)),
        queued=queue.pending_for(book.id),
    )


@settings_router.get("/mode", response_model=TranslateModeOut)
def read_mode(session: Session = Depends(get_session)) -> TranslateModeOut:
    return _mode_out(session)


def _mode_out(session: Session) -> TranslateModeOut:
    return TranslateModeOut(
        mode=str(get_mode(session)),
        button_mode=str(get_button_mode(session)),
        colour_mode=str(get_colour_mode(session)),
        configured=is_configured(),
        costs=_COSTS,
        sidecar_dir=str(settings.sidecar_dir),
        sidecar_writable=sidecar.is_writable(),
    )


@settings_router.put("/mode", response_model=TranslateModeOut)
def write_mode(
    payload: TranslateModeIn, session: Session = Depends(get_session)
) -> TranslateModeOut:
    """De stand waarin de wachtrij en de gewone vertaalknop werken.

    Twee standen, los van elkaar. ``mode`` is wat er vanzelf gebeurt; die mag
    goedkoop blijven. ``button_mode`` is wat de knop in de lezer doet, voor de
    pagina waarvan jij vindt dat hij het waard is.

    De dure standen mogen hier gekozen worden, maar de wachtrij die vooruit
    leest blijft altijd de goedkope gebruiken — anders zou wegdommelen tijdens
    het lezen een rekening opleveren.
    """
    if payload.mode is not None:
        set_mode(session, _parse_mode(payload.mode))
    if payload.button_mode is not None:
        set_button_mode(session, _parse_mode(payload.button_mode))
    if payload.colour_mode is not None:
        stand = _parse_mode(payload.colour_mode)
        if not stand.is_image:
            raise HTTPException(
                status_code=400, detail="inkleuren vraagt een beeldstand, geen tekststand"
            )
        set_colour_mode(session, stand)
    return _mode_out(session)


@router.post("/{book_id}/pages/{page_index}/colour", response_model=PageColourOut)
def make_page_colour(
    book_id: int,
    page_index: int,
    lang: str | None = Query(default=None, max_length=8),
    force: bool = Query(default=False, description="Opnieuw laten inkleuren."),
    session: Session = Depends(get_session),
) -> PageColourOut:
    """Kleur deze pagina in.

    Een aparte handeling en geen vertaalstand: inkleuren verandert niets aan de
    tekst, en een ingekleurde pagina hoort nooit in de plaats te komen van een
    vertaalde. Het kost per pagina hetzelfde als het hertekenen, dus het gebeurt
    alleen als je erom vraagt.
    """
    book = deps.get_book(session, book_id)
    if not is_configured():
        raise HTTPException(
            status_code=409,
            detail="er is geen Gemini-sleutel ingesteld (BOOKPAL_GEMINI_API_KEY)",
        )

    # Standaard het snelle model, in te stellen bij Instellingen -> Vertaling.
    # Dat het snelle model bij vertalen tekortschiet geldt hier niet: er komt
    # geen letter aan te pas, en het lijnwerk houden we zelf vast.
    translator = GeminiPageTranslator(settings.gemini_api_key, get_colour_mode(session).model)
    try:
        colorise_page(session, translator, book, page_index, force=force)
    except AlreadyColour as exc:
        # 412 en geen 502: er is niets kapot. De lezer herkent deze code, vraagt
        # het je, en stuurt het dan opnieuw met force.
        raise HTTPException(status_code=412, detail=str(exc)) from exc
    except TranslationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        translator.close()

    return PageColourOut(book_id=book.id, page_index=page_index, available=True)


@router.get("/{book_id}/pages/{page_index}/colour/info", response_model=PageColourInfoOut)
def page_colour_info(
    book_id: int,
    page_index: int,
    lang: str | None = Query(default=None, max_length=8),
    session: Session = Depends(get_session),
) -> PageColourInfoOut:
    """Is er kleur voor deze pagina, en van wie?

    Het renderen om te kijken of de pagina van zichzelf al kleur heeft doen we
    alleen als er geen ingekleurde versie ligt: dan is het antwoord toch al ja,
    en scheelt het werk bij elke paginawissel.
    """
    book = deps.get_book(session, book_id)
    taal = _lang(lang)
    met_tekst = lang is not None and has_colour_for_language(session, book, page_index, taal)
    if met_tekst or has_colour(session, book, page_index):
        return PageColourInfoOut(available=True, native=False, translated=met_tekst)
    try:
        image, _media_type = render_for_translation(session, book, page_index)
    except TranslationError:
        return PageColourInfoOut(available=False, native=False)
    return PageColourInfoOut(available=False, native=recolour.is_colour(image))


@router.get("/{book_id}/pages/{page_index}/colour")
def get_page_colour(
    book_id: int,
    page_index: int,
    lang: str | None = Query(default=None, max_length=8),
    session: Session = Depends(get_session),
) -> Response:
    """De ingekleurde pagina zelf.

    Met een taal erbij krijg je de versie die van de vertaalde pagina is
    gemaakt, als die er is — kleur en vertaalde tekst in één beeld. Zonder taal
    alleen het ingekleurde origineel, want met de vertaling uit hoor je geen
    Nederlandse tekst te zien.
    """
    book = deps.get_book(session, book_id)
    data = read_colour(session, book, page_index, lang)
    if data is None:
        raise HTTPException(status_code=404, detail="deze pagina is nog niet ingekleurd")
    return Response(
        content=data,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# -- een heel hoofdstuk in één keer -------------------------------------
#
# Via de batch-API van Gemini: die doet er minuten over ongeacht hoeveel
# pagina's je meegeeft, en kost de helft. Precies verkeerd voor de pagina waar
# je op wacht, precies goed voor een hoofdstuk dat je klaarzet voor vanavond.


def _plan_out(plan: batch.BatchPlan) -> BatchPlanOut:
    return BatchPlanOut(
        kind=plan.kind,
        mode=str(plan.mode),
        pages=len(plan.pages),
        price_per_page=plan.price_per_page,
        total=plan.total,
        batch_factor=batch.BATCH_FACTOR,
    )


def _status_out(state: batch.BatchState) -> BatchStatusOut:
    return BatchStatusOut(
        kind=state.kind,
        book_id=state.book_id,
        mode=str(state.mode),
        state=state.state,
        done=state.done,
        total=state.total,
        failed=state.failed,
        error=state.error,
    )


@router.get("/{book_id}/batch/plan", response_model=BatchPlanOut)
def batch_plan(
    book_id: int,
    kind: str = Query(max_length=20),
    from_page: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> BatchPlanOut:
    """Hoeveel pagina's er nog moeten en wat dat kost.

    Apart van het starten, zodat de lezer eerst het bedrag kan tonen. Een knop
    die ongevraagd een hoofdstuk afrekent is precies wat je hier niet wilt.
    """
    book = deps.get_book(session, book_id)
    if kind not in batch.SOORTEN:
        raise HTTPException(status_code=400, detail=f"onbekende soort: {kind!r}")
    try:
        return _plan_out(batch.plan(session, book, kind=kind, from_page=from_page))
    except TranslationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{book_id}/batch", response_model=BatchStatusOut)
def batch_start(
    book_id: int,
    payload: BatchStartIn,
    session: Session = Depends(get_session),
) -> BatchStatusOut:
    """Zet het hoofdstuk in de batch."""
    book = deps.get_book(session, book_id)
    if payload.kind not in batch.SOORTEN:
        raise HTTPException(status_code=400, detail=f"onbekende soort: {payload.kind!r}")
    if not is_configured():
        raise HTTPException(
            status_code=409,
            detail="er is geen Gemini-sleutel ingesteld (BOOKPAL_GEMINI_API_KEY)",
        )
    try:
        plan = batch.plan(session, book, kind=payload.kind, from_page=payload.from_page)
        return _status_out(batch.start(book.id, plan))
    except TranslationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{book_id}/batch", response_model=BatchStatusOut | None)
def batch_status(book_id: int) -> BatchStatusOut | None:
    """Wat er loopt. Ook van een ander boek: er kan er maar één tegelijk."""
    state = batch.status()
    return None if state is None else _status_out(state)
