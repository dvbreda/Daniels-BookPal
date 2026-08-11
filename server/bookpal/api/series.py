"""Series doorbladeren."""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.formats.base import UnsupportedOperation
from bookpal.images import (
    ImageProfile,
    RenderedImage,
    open_source,
    render_cover,
    render_page,
    render_remote_cover,
    source_id_for,
)
from bookpal.models import Book, BookKind, File, OriginRegion, OriginSource, Series
from bookpal.schemas import (
    AttachCoverIn,
    ContinueOut,
    MarkReadBeforeOut,
    OriginPatch,
    Paginated,
    SeriesDetailOut,
    SeriesOut,
    SetCoverPageIn,
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
    # Een net gekozen bron-omslag mag niet verborgen blijven achter een oude
    # handmatige paginakeuze; die kan altijd terug via .../cover-page.
    series.cover_page_index = None
    session.commit()

    book_count = int(
        session.scalar(select(func.count(Book.id)).where(Book.series_id == series.id)) or 0
    )
    return deps.to_series_out(series, book_count, [])


@router.patch("/{series_id}/cover-page", response_model=SeriesOut)
def set_cover_page(
    series_id: int, payload: SetCoverPageIn, session: Session = Depends(get_session)
) -> SeriesOut:
    """Een vaste pagina van het eerste boek als omslag.

    Nuttig als er geen bron met een schone omslag bestaat, of als 'pagina 1'
    domweg niet de omslag is. Wint van een eerder gekoppelde bron-omslag —
    die blijft ondertussen bewaard en komt terug zodra je dit weer op de
    standaardkeuze zet (``page_index: null``).
    """
    series = deps.get_series(session, series_id)
    if payload.page_index is not None:
        first = series.books[0] if series.books else None
        if first is None:
            raise HTTPException(status_code=409, detail="deze serie heeft nog geen boeken")
        if first.kind is BookKind.EPUB:
            raise HTTPException(
                status_code=409,
                detail="een epub heeft geen vaste pagina's om als omslag te kiezen",
            )
        if first.page_count is not None and payload.page_index >= first.page_count:
            raise HTTPException(
                status_code=400,
                detail=f"pagina {payload.page_index} bestaat niet; {first.title} heeft er "
                f"{first.page_count}",
            )
    series.cover_page_index = payload.page_index
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
    """De omslag van deze serie: eerst een handmatig gekozen pagina, dan een
    omslag van de bron, dan pagina 1 van het eerste boek.

    Alle drie via dezelfde cache en beeldpipeline als elke andere afbeelding
    — dus ook grijswaarden en dithering voor de Kobo.
    """
    series = deps.get_series(session, series_id)

    if series.cover_page_index is not None:
        first = series.books[0] if series.books else None
        if first is not None and first.file_id is not None:
            path = deps.book_file_path(session, first)
            source = open_source(path)
            try:
                rendered = render_page(
                    source, series.cover_page_index, profile, source_id=source_id_for(path)
                )
                return _cover_response(rendered)
            except (IndexError, UnsupportedOperation):
                pass  # gekozen pagina bestaat niet meer; val terug

    if series.cover_url:
        try:
            rendered = render_remote_cover(
                series.cover_url, profile, source_id=f"series-cover:{series.id}:{series.cover_url}"
            )
        except UnsupportedOperation as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _cover_response(rendered)

    first = series.books[0] if series.books else None
    if first is not None and first.file_id is not None:
        path = deps.book_file_path(session, first)
        source = open_source(path)
        maybe_rendered = render_cover(source, profile, source_id=source_id_for(path))
        if maybe_rendered is not None:
            return _cover_response(maybe_rendered)

    raise HTTPException(status_code=404, detail="deze serie heeft nog geen omslag")


def _cover_response(rendered: RenderedImage) -> Response:
    return Response(
        content=rendered.data,
        media_type=rendered.media_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-BookPal-Cache": "hit" if rendered.from_cache else "miss",
        },
    )


def _readable_books(session: Session, series_id: int) -> list[Book]:
    """De hoofdstukken in leesvolgorde, alleen wat je daadwerkelijk kunt openen.

    Hoofdstukken zonder bestand (een abonnement dat nog niet is opgehaald)
    slaan we over: "lees verder" hoort je niet op een lege pagina te zetten.
    """
    return list(
        session.scalars(
            select(Book)
            .where(Book.series_id == series_id, Book.file_id.isnot(None))
            .order_by(Book.sort_volume, Book.sort_number)
        )
    )


@router.get("/{series_id}/continue", response_model=ContinueOut)
def continue_reading(series_id: int, session: Session = Depends(get_session)) -> ContinueOut:
    """Waar je verder leest: het eerste hoofdstuk dat nog niet uit is.

    Eerst iets dat je al begonnen was — daar wil je terug naar de pagina waar
    je gebleven bent. Is er niets half af, dan het eerste dat je nog niet hebt
    aangeraakt. Bewust op leesvolgorde en niet op "laatst gelezen": bij manga
    lees je vooruit, en een serie waarin je een oud hoofdstuk hebt teruggekeken
    hoort je niet daarheen terug te sturen.
    """
    deps.get_series(session, series_id)
    books = _readable_books(session, series_id)
    if not books:
        raise HTTPException(status_code=404, detail="deze serie heeft nog niets te lezen")

    user = current_user(session)
    progress = deps.progress_for(session, user, [book.id for book in books])

    started: Book | None = None
    fresh: Book | None = None
    for book in books:
        row = progress.get(book.id)
        if row is not None and row.finished:
            continue
        if row is not None and row.percent > 0:
            started = book
            break
        if fresh is None:
            fresh = book

    target = started or fresh
    if target is None:
        # Alles uit: dan maar het laatste hoofdstuk, zodat de knop iets doet
        # in plaats van te verdwijnen.
        target = books[-1]

    row = progress.get(target.id)
    position = row.position if row is not None else {}
    page = position.get("page") if isinstance(position, dict) else None

    unread_before = sum(
        1
        for book in books
        if (book.sort_volume, book.sort_number) < (target.sort_volume, target.sort_number)
        and not (progress.get(book.id) is not None and progress[book.id].finished)
    )

    return ContinueOut(
        book_id=target.id,
        title=target.title,
        number=target.number,
        page=page if isinstance(page, int) and page >= 0 else 0,
        resuming=row is not None and row.percent > 0 and not row.finished,
        unread_before=unread_before,
    )


@router.post("/{series_id}/mark-read-before/{book_id}", response_model=MarkReadBeforeOut)
def mark_read_before(
    series_id: int, book_id: int, session: Session = Depends(get_session)
) -> MarkReadBeforeOut:
    """Alles vóór dit hoofdstuk als gelezen wegzetten.

    Voor de gewone situatie dat je elders al tot hier was, of dat je een serie
    halverwege oppakt. Het hoofdstuk zelf blijft ongemoeid — daar ga je juist
    lezen.
    """
    deps.get_series(session, series_id)
    target = deps.get_book(session, book_id)
    if target.series_id != series_id:
        raise HTTPException(status_code=400, detail="dit hoofdstuk hoort niet bij deze serie")

    user = current_user(session)
    books = _readable_books(session, series_id)
    progress = deps.progress_for(session, user, [book.id for book in books])

    marked = 0
    for book in books:
        if (book.sort_volume, book.sort_number) >= (target.sort_volume, target.sort_number):
            continue
        row = progress.get(book.id)
        if row is not None and row.finished:
            continue
        deps.upsert_progress(
            session,
            user,
            book.id,
            series_id=series_id,
            position={"page": max(0, (book.page_count or 1) - 1)},
            percent=100.0,
            device="web",
            finished=True,
        )
        marked += 1
    return MarkReadBeforeOut(marked=marked)
