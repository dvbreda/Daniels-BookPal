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
    BubbleOut,
    PageTranslationOut,
    TranslateBookIn,
    TranslateBookOut,
    TranslationStatusOut,
)
from bookpal.translate import get_translator, is_configured
from bookpal.translate.base import PageResult, TranslationError
from bookpal.translate.queue import queue
from bookpal.translate.service import (
    find,
    plan_pages,
    render_layer_for,
    translate_page,
    translated_pages,
)

from . import deps

router = APIRouter(prefix="/api/books", tags=["translate"])

PROVIDER = "gemini"


def _lang(value: str | None) -> str:
    return value or settings.translate_lang


def _to_out(book_id: int, page_index: int, target_lang: str, result: PageResult) -> (
    PageTranslationOut
):
    return PageTranslationOut(
        book_id=book_id,
        page_index=page_index,
        target_lang=target_lang,
        provider=PROVIDER,
        model=result.model,
        bubbles=[
            BubbleOut(
                box=[bubble.x0, bubble.y0, bubble.x1, bubble.y1],
                source=bubble.source,
                translation=bubble.translation,
                kind=str(bubble.kind),
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
    book = deps.get_book(session, book_id)
    target_lang = _lang(lang)
    row = find(session, book.id, page_index, target_lang, PROVIDER)
    if row is None:
        raise HTTPException(status_code=404, detail="deze pagina is nog niet vertaald")
    return _to_out(book.id, page_index, target_lang, PageResult.from_payload(row.payload))


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

    todo = plan_pages(
        session,
        book,
        target_lang=target_lang,
        provider=PROVIDER,
        from_page=payload.from_page,
    )
    queued = queue.submit(book.id, todo, target_lang)
    done = len(translated_pages(session, book.id, target_lang, PROVIDER))
    return TranslateBookOut(queued=queued, already_done=done)


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
        translated=len(translated_pages(session, book.id, target_lang, PROVIDER)),
        queued=queue.pending_for(book.id),
    )
