"""Series doorbladeren."""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.formats.base import UnsupportedOperation
from bookpal.images import ImageProfile, render_remote_cover
from bookpal.models import Book, BookKind, File, OriginRegion, OriginSource, Series
from bookpal.schemas import (
    AttachCoverIn,
    OriginPatch,
    Paginated,
    SeriesDetailOut,
    SeriesOut,
)
from bookpal.sources import SourceError
from bookpal.sources import service as source_service

from . import deps

router = APIRouter(prefix="/api/series", tags=["series"])


SelectT = TypeVar("SelectT", bound=Select[Any])


def _apply_filters(
    statement: SelectT,
    *,
    root_id: int | None,
    region: OriginRegion | None,
    kind: BookKind | None,
    search: str | None,
) -> SelectT:
    if root_id is not None:
        statement = statement.where(Series.library_root_id == root_id)
    if region is not None:
        statement = statement.where(Series.origin_region == region)
    if kind is not None:
        statement = statement.where(Series.books.any(Book.kind == kind))
    if search:
        statement = statement.where(Series.title.ilike(f"%{search}%"))
    return statement


@router.get("", response_model=Paginated[SeriesOut])
def list_series(
    root_id: int | None = None,
    region: OriginRegion | None = None,
    kind: BookKind | None = None,
    search: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=500),
    session: Session = Depends(get_session),
) -> Paginated[SeriesOut]:
    """Bladeren met de filters die M3 straks als regelboom automatiseert.

    Nu nog losse query-parameters; de tab-regels compileren later naar precies
    deze where-clausules.
    """
    base = _apply_filters(select(Series), root_id=root_id, region=region, kind=kind, search=search)
    total = session.scalar(
        _apply_filters(
            select(func.count(Series.id)),
            root_id=root_id,
            region=region,
            kind=kind,
            search=search,
        )
    )
    rows = session.scalars(base.order_by(Series.sort_title).offset(offset).limit(limit)).all()
    items = deps.series_out_list(session, list(rows))

    return Paginated(items=items, total=int(total or 0), offset=offset, limit=limit)


@router.get("/{series_id}", response_model=SeriesDetailOut)
def get_series(series_id: int, session: Session = Depends(get_session)) -> SeriesDetailOut:
    series = deps.get_series(session, series_id)
    user = current_user(session)
    books = list(series.books)
    progress = deps.progress_for(session, user, [book.id for book in books])
    extensions = {
        row.id: row.extension
        for row in session.scalars(
            select(File).where(File.id.in_([b.file_id for b in books if b.file_id]))
        )
    }

    detail = SeriesDetailOut(
        **deps.to_series_out(
            series, len(books), sorted({book.kind.value for book in books})
        ).model_dump()
    )
    detail.books = [
        deps.to_book_out(book, progress.get(book.id), extensions.get(book.file_id or -1))
        for book in books
    ]
    return detail


@router.patch("/{series_id}/origin", response_model=SeriesOut)
def set_origin(
    series_id: int, payload: OriginPatch, session: Session = Depends(get_session)
) -> SeriesOut:
    """Handmatig de herkomst corrigeren.

    Dit zet ``origin_source`` op MANUAL, en dat is het hele punt: vanaf nu
    overschrijft geen enkele rescan of online-bron deze keuze meer.
    """
    series = deps.get_series(session, series_id)
    series.origin_language = payload.origin_language
    series.origin_country = payload.origin_country
    series.origin_region = payload.origin_region
    series.origin_source = OriginSource.MANUAL
    session.commit()

    book_count = int(
        session.scalar(select(func.count(Book.id)).where(Book.series_id == series.id)) or 0
    )
    return deps.to_series_out(series, book_count, [])


@router.post("/{series_id}/cover", response_model=SeriesOut)
def attach_cover(
    series_id: int, payload: AttachCoverIn, session: Session = Depends(get_session)
) -> SeriesOut:
    """Koppel de officiële omslag van een bron aan deze serie.

    Nuttig bij scanlaties: 'pagina 1 van hoofdstuk 1' is daar vaak een
    credits-pagina van de vertaalgroep over de echte omslag heen. Werkt ook
    voor een serie die je zelf hebt gescand — er komt geen abonnement bij,
    alleen de omslag zelf.
    """
    series = deps.get_series(session, series_id)
    source = deps.get_source_row(session, payload.source_id)
    implementation = deps.get_source_implementation(source)
    try:
        source_service.attach_cover(series, implementation, payload.ref)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.commit()

    book_count = int(
        session.scalar(select(func.count(Book.id)).where(Book.series_id == series.id)) or 0
    )
    return deps.to_series_out(series, book_count, [])


@router.get("/{series_id}/cover")
def get_series_cover(
    series_id: int,
    profile: ImageProfile = deps.ProfileDep,
    session: Session = Depends(get_session),
) -> Response:
    """De omslag van de bron, als die gekoppeld is.

    Geen fallback naar 'pagina 1 van het eerste boek' hier — dat blijft aan de
    client, want alleen die weet welk boek daarvoor het eerste is.
    """
    series = deps.get_series(session, series_id)
    if not series.cover_url:
        raise HTTPException(status_code=404, detail="deze serie heeft geen omslag van een bron")
    try:
        rendered = render_remote_cover(
            series.cover_url, profile, source_id=f"series-cover:{series.id}:{series.cover_url}"
        )
    except UnsupportedOperation as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=rendered.data,
        media_type=rendered.media_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-BookPal-Cache": "hit" if rendered.from_cache else "miss",
        },
    )
