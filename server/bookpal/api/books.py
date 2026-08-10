"""Boeken, pagina's, covers en het originele bestand."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.formats.base import UnsupportedOperation
from bookpal.images import (
    ImageProfile,
    open_source,
    render_cover,
    render_page,
    source_id_for,
)
from bookpal.models import Book, BookKind, File, Series
from bookpal.schemas import BookDetailOut, BookOut, Paginated, TocEntryOut

from . import deps

router = APIRouter(prefix="/api/books", tags=["books"])

# Pagina's zijn onveranderlijk zolang het bronbestand niet wijzigt, en de
# cachesleutel bevat de mtime. Daarom mag de browser ze lang vasthouden.
PAGE_CACHE_CONTROL = "public, max-age=604800, immutable"
COVER_CACHE_CONTROL = "public, max-age=86400"


@router.get("", response_model=Paginated[BookOut])
def list_books(
    series_id: int | None = None,
    kind: BookKind | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=500),
    session: Session = Depends(get_session),
) -> Paginated[BookOut]:
    statement = select(Book)
    counter = select(func.count(Book.id))
    if series_id is not None:
        statement = statement.where(Book.series_id == series_id)
        counter = counter.where(Book.series_id == series_id)
    if kind is not None:
        statement = statement.where(Book.kind == kind)
        counter = counter.where(Book.kind == kind)

    total = int(session.scalar(counter) or 0)
    books = session.scalars(
        statement.order_by(Book.series_id, Book.sort_number).offset(offset).limit(limit)
    ).all()

    user = current_user(session)
    progress = deps.progress_for(session, user, [book.id for book in books])
    extensions = {
        row.id: row.extension
        for row in session.scalars(
            select(File).where(File.id.in_([b.file_id for b in books if b.file_id]))
        )
    }
    items = [
        deps.to_book_out(book, progress.get(book.id), extensions.get(book.file_id or -1))
        for book in books
    ]
    return Paginated(items=items, total=total, offset=offset, limit=limit)


@router.get("/{book_id}", response_model=BookDetailOut)
def get_book(book_id: int, session: Session = Depends(get_session)) -> BookDetailOut:
    book = deps.get_book(session, book_id)
    series = session.get(Series, book.series_id)
    user = current_user(session)
    progress = deps.progress_for(session, user, [book.id]).get(book.id)
    extension = None
    if book.file_id is not None:
        file_row = session.get(File, book.file_id)
        extension = file_row.extension if file_row else None

    detail = BookDetailOut(
        **deps.to_book_out(book, progress, extension).model_dump(),
        series_title=series.title if series else "",
    )

    if book.file_id is not None:
        try:
            path = deps.book_file_path(session, book)
            source = open_source(path)
            detail.toc = [
                TocEntryOut(title=entry.title, target=entry.target, level=entry.level)
                for entry in source.toc()
            ]
        except HTTPException:
            pass
        except (OSError, UnsupportedOperation):
            pass
    return detail


@router.get("/{book_id}/pages/{index}")
def get_page(
    book_id: int,
    index: int,
    profile: ImageProfile = deps.ProfileDep,
    session: Session = Depends(get_session),
) -> Response:
    """Eén pagina, klaargemaakt voor het gevraagde apparaat."""
    book = deps.get_book(session, book_id)
    if book.kind is BookKind.EPUB:
        raise HTTPException(
            status_code=409,
            detail="een epub heeft geen vaste pagina's; haal het bestand op via /file",
        )
    if index < 0:
        raise HTTPException(status_code=400, detail="paginanummer moet 0 of hoger zijn")

    path = deps.book_file_path(session, book)
    source = open_source(path)
    try:
        rendered = render_page(source, index, profile, source_id=source_id_for(path))
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnsupportedOperation as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(
        content=rendered.data,
        media_type=rendered.media_type,
        headers={
            "Cache-Control": PAGE_CACHE_CONTROL,
            "X-BookPal-Cache": "hit" if rendered.from_cache else "miss",
            "X-BookPal-Profile": profile.name,
        },
    )


@router.get("/{book_id}/cover")
def get_cover(
    book_id: int,
    profile: ImageProfile = deps.ProfileDep,
    session: Session = Depends(get_session),
) -> Response:
    book = deps.get_book(session, book_id)
    path = deps.book_file_path(session, book)
    source = open_source(path)
    rendered = render_cover(source, profile, source_id=source_id_for(path))
    if rendered is None:
        raise HTTPException(status_code=404, detail="dit boek heeft geen omslag")
    return Response(
        content=rendered.data,
        media_type=rendered.media_type,
        headers={
            "Cache-Control": COVER_CACHE_CONTROL,
            "X-BookPal-Cache": "hit" if rendered.from_cache else "miss",
        },
    )


@router.get("/{book_id}/file")
def get_file(book_id: int, session: Session = Depends(get_session)) -> FileResponse:
    """Het originele bestand.

    Dit is hoe epub en pdf bij de client komen: die renderen zelf (foliate-js in
    web en iOS, crengine op de Kobo), want herschikbare tekst laat zich niet
    server-side in pagina's knippen.
    """
    book = deps.get_book(session, book_id)
    path = deps.book_file_path(session, book)
    return FileResponse(path, filename=path.name)
