"""Wikipedia-achtergrond bij een serie, boek of auteur."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from bookpal.schemas import WikiHitOut
from bookpal.wiki import WikiError, article_epub, search

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


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
