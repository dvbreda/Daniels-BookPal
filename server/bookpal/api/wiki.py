"""Wikipedia-achtergrond bij een serie, boek of auteur."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from bookpal.db import get_session
from bookpal.schemas import WikiHitOut, WikiSuggestieOut
from bookpal.wiki import WikiError, article_epub, search

from . import deps

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


#: Hoeveel treffers per zoekterm. Eén is te weinig — Wikipedia's eerste
#: resultaat is bij een korte reeksnaam nogal eens een doorverwijspagina —
#: en meer dan drie maakt de lijst in de app langer dan de serie zelf.
_PER_TERM = 3


@router.get("/for-series/{series_id}", response_model=list[WikiSuggestieOut])
def wiki_voor_serie(
    series_id: int,
    lang: str = Query(default="nl", max_length=8),
    session: Session = Depends(get_session),
) -> list[WikiSuggestieOut]:
    """Wat er op Wikipedia over deze reeks en zijn makers te vinden is.

    Bestond alleen als losse zoekbalk, waar je zelf de naam moest intikken. Bij
    een boek is dat te doen; bij Power Unlimited of een manga waarvan je de
    tekenaar niet uit je hoofd kent niet. De serie weet zelf hoe hij heet en wie
    hem gemaakt heeft, dus dat hoort de server te vragen.

    Zoekt per taal en valt terug op het Engels: over een Nederlandse
    stripreeks staat vaak alleen daar iets, en andersom.
    """
    series = deps.get_series(session, series_id)

    termen: list[tuple[str, str]] = [("reeks", series.title)]
    termen += [("maker", auteur) for auteur in series.authors[:3] if auteur.strip()]

    gevonden: list[WikiSuggestieOut] = []
    gezien: set[str] = set()
    for rol, term in termen:
        for taal in dict.fromkeys([lang, "en"]):
            try:
                treffers = search(term, lang=taal, limit=_PER_TERM)
            except WikiError:
                # Eén term die niets oplevert mag de rest niet meenemen: een
                # tekenaar zonder artikel is de normaalste zaak.
                continue
            if not treffers:
                continue
            for hit in treffers:
                sleutel = f"{hit.lang}:{hit.key}"
                if sleutel in gezien:
                    continue
                gezien.add(sleutel)
                gevonden.append(
                    WikiSuggestieOut(
                        rol=rol,
                        voor=term,
                        title=hit.title,
                        key=hit.key,
                        description=hit.description,
                        lang=hit.lang,
                    )
                )
            break  # deze taal leverde iets op; niet ook nog Engels erbij
    return gevonden


@router.get("/search", response_model=list[WikiHitOut])
def wiki_search(
    q: str = Query(min_length=1, max_length=200),
    lang: str = Query(default="nl", max_length=8),
    limit: int = Query(default=5, ge=1, le=20),
) -> list[WikiHitOut]:
    try:
        hits = search(q, lang=lang, limit=limit)
    except WikiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [
        WikiHitOut(title=hit.title, key=hit.key, description=hit.description, lang=hit.lang)
        for hit in hits
    ]


@router.get("/article.epub")
def wiki_article(
    key: str = Query(min_length=1, max_length=300),
    lang: str = Query(default="nl", max_length=8),
) -> Response:
    """Het artikel als epub, zodat het in dezelfde lezer opengaat als je boeken."""
    try:
        title, data = article_epub(key, lang=lang)
    except WikiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(
        content=data,
        media_type="application/epub+zip",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(title)}.epub",
            # Een artikel verandert zelden binnen een leessessie, maar wel
            # tussen sessies; een uur is een redelijk midden.
            "Cache-Control": "public, max-age=3600",
        },
    )
