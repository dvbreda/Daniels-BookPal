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
from bookpal.translate import service as translation_service
from bookpal.translate.base import PageResult
from bookpal.translate.overlay import bake

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
        statement.order_by(Book.series_id, Book.sort_volume, Book.sort_number)
        .offset(offset)
        .limit(limit)
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
    translate: str | None = Query(default=None, max_length=8),
    session: Session = Depends(get_session),
) -> Response:
    """Eén pagina, klaargemaakt voor het gevraagde apparaat.

    ``translate=nl`` bakt een al gemaakte vertaling in het beeld. Dat is er
    voor de Kobo en voor BookPal Lite: die kunnen geen overlay tekenen, maar
    krijgen hun pagina's toch al server-side klaargemaakt. Nog niet vertaald?
    Dan gewoon het origineel — een lezer hoort niet te blokkeren op een
    vertaling die nog moet komen.
    """
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

    data = rendered.data
    media_type = rendered.media_type
    if translate:
        found = translation_service.best_available(session, book, index, translate)
        if found is not None:
            mode, row = found
            if mode.is_image:
                # De hele pagina is al hertekend; die vervangt het origineel in
                # zijn geheel. Kan ontbreken als de sidecar-map is opgeruimd —
                # dan gewoon het origineel, want blokkeren helpt de lezer niet.
                replacement = translation_service.read_page_image(
                    session, book, index, translate, mode
                )
                if replacement is not None:
                    data, media_type = replacement, "image/webp"
                    if mode.needs_bubbles:
                        # Hybride: het model heeft alleen leeggeveegd, dus onze
                        # eigen tekst moet er nog overheen — zonder wit vlakje,
                        # want er valt niets meer af te dekken.
                        ours = translation_service.bubbles_for(
                            session, book, index, translate
                        ).bubbles
                        if ours:
                            data = bake(data, ours, media_type=media_type, boxes=False)
            else:
                bubbles = PageResult.from_payload(row.payload).bubbles
                if bubbles:
                    data = bake(data, bubbles, media_type=media_type)

    return Response(
        content=data,
        media_type=media_type,
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

    # Een handmatig gekozen omslagpagina geldt voor de hele serie, niet alleen
    # voor het eerste deel: bij scanlations zit de reclame op pagina 1 van elk
    # hoofdstuk, dus juist de deel-kaartjes hebben die keuze nodig.
    page_index = book.series.cover_page_index if book.series is not None else None
    if page_index is not None:
        try:
            chosen = render_page(source, page_index, profile, source_id=source_id_for(path))
            return Response(
                content=chosen.data,
                media_type=chosen.media_type,
                headers={
                    "Cache-Control": COVER_CACHE_CONTROL,
                    "X-BookPal-Cache": "hit" if chosen.from_cache else "miss",
                },
            )
        except (IndexError, UnsupportedOperation):
            pass  # dit deel is korter, of heeft geen vaste pagina's; val terug

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


# Python's mimetypes kent cbz/cbr/cb7 niet en geeft voor epub op sommige
# systemen niets terug; dan valt FileResponse terug op octet-stream. Clients
# die op het mediatype afgaan zien zo'n bestand niet voor wat het is.
FILE_MEDIA_TYPES = {
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
    ".cbz": "application/vnd.comicbook+zip",
    ".cbr": "application/vnd.comicbook-rar",
    ".cb7": "application/x-cb7",
}


@router.get("/{book_id}/file")
def get_file(book_id: int, session: Session = Depends(get_session)) -> FileResponse:
    """Het originele bestand.

    Dit is hoe epub en pdf bij de client komen: die renderen zelf (foliate-js in
    web en iOS, crengine op de Kobo), want herschikbare tekst laat zich niet
    server-side in pagina's knippen.
    """
    book = deps.get_book(session, book_id)
    path = deps.book_file_path(session, book)
    return FileResponse(
        path,
        filename=path.name,
        media_type=FILE_MEDIA_TYPES.get(path.suffix.lower()),
    )
