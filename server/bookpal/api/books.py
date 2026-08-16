"""Boeken, pagina's, covers en het originele bestand."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.formats.base import UnsupportedOperation
from bookpal.images import (
    ImageProfile,
    get_profile,
    open_source,
    panels,
    render_cover,
    render_page,
    render_remote_cover,
    source_id_for,
)
from bookpal.images.adjust import Adjustments
from bookpal.library import editions
from bookpal.models import Book, BookKind, Edition, File, Progress, Series, utcnow
from bookpal.schemas import (
    BookDetailOut,
    BookOut,
    NextChapterOut,
    Paginated,
    PanelOut,
    PanelsOut,
    ReadStateIn,
    ReadStateOut,
    TocEntryOut,
)
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


@router.get("/{book_id}/next", response_model=NextChapterOut)
def next_chapter(book_id: int, session: Session = Depends(get_session)) -> NextChapterOut:
    """Wat er na dit hoofdstuk komt in leesvolgorde.

    Inclusief hoofdstukken die nog opgehaald moeten worden: juist als je er een
    uit hebt wil je weten dat het volgende bestaat, ook al staat het nog niet
    op schijf. De client biedt dan "ophalen en lezen" aan in plaats van niets.
    """
    book = deps.get_book(session, book_id)
    later = session.scalars(
        select(Book)
        .where(
            Book.series_id == book.series_id,
            tuple_(Book.sort_volume, Book.sort_number, Book.id)
            > (book.sort_volume, book.sort_number, book.id),
        )
        .order_by(Book.sort_volume, Book.sort_number, Book.id)
        .limit(1)
    ).first()
    if later is None:
        raise HTTPException(status_code=404, detail="dit was het laatste hoofdstuk")

    return NextChapterOut(
        book_id=later.id,
        title=later.title,
        number=later.number,
        volume=later.volume,
        has_file=later.file_id is not None,
    )


@router.get("/{book_id}/pages/{index}")
def get_page(
    book_id: int,
    index: int,
    profile: ImageProfile = deps.ProfileDep,
    adjustments: Adjustments = deps.AdjustDep,
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
        rendered = render_page(
            source, index, profile, source_id=source_id_for(path), adjustments=adjustments
        )
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


@router.get("/{book_id}/pages/{index}/panels", response_model=PanelsOut)
def get_page_panels(
    book_id: int,
    index: int,
    session: Session = Depends(get_session),
) -> PanelsOut:
    """Waar de panelen op deze pagina zitten.

    Zonder model: een stripbladzijde heeft goten tussen de panelen, en die zijn
    met rekenwerk te vinden (recursieve XY-cut, zie `images/panels.py`). Dat
    kost milliseconden in plaats van honderden megabytes aan gewichten —
    dezelfde afweging als bij M8.

    Server-side en niet per client, om dezelfde reden als de beeldprofielen: het
    antwoord is voor iedereen gelijk, het is te cachen, en web, iOS en Kobo
    hoeven het niet ieder apart na te bouwen.
    """
    book = deps.get_book(session, book_id)
    if book.kind is BookKind.EPUB:
        raise HTTPException(
            status_code=409, detail="een epub heeft geen vaste pagina's"
        )
    if index < 0:
        raise HTTPException(status_code=400, detail="paginanummer moet 0 of hoger zijn")

    path = deps.book_file_path(session, book)
    source = open_source(path)
    try:
        rendered = render_page(
            source, index, get_profile("web"), source_id=source_id_for(path)
        )
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="pagina bestaat niet") from exc
    finally:
        source.close()

    gevonden = panels.detect(rendered.data, right_to_left=book.right_to_left)
    heel = len(gevonden) == 1 and gevonden[0].oppervlak > 0.98
    return PanelsOut(
        book_id=book.id,
        page_index=index,
        panels=[PanelOut(box=paneel.as_list()) for paneel in gevonden],
        whole_page=heel,
    )


@router.get("/{book_id}/cover")
def get_cover(
    book_id: int,
    profile: ImageProfile = deps.ProfileDep,
    session: Session = Depends(get_session),
) -> Response:
    book = deps.get_book(session, book_id)

    # De omslag van dít deel bij de bron wint van "pagina 1": bij scanlations
    # staat daar vaak een credits-pagina van de vertaalgroep. Een handmatig
    # gekozen paginanummer gaat hier weer boven, want dat is een echte keuze.
    gekozen_pagina = book.cover_page_index
    if gekozen_pagina is None and book.series is not None:
        gekozen_pagina = book.series.cover_page_index

    if book.cover_url and gekozen_pagina is None:
        try:
            remote = render_remote_cover(
                book.cover_url, profile, source_id=f"book-cover:{book.id}:{book.cover_url}"
            )
            return Response(
                content=remote.data,
                media_type=remote.media_type,
                headers={
                    "Cache-Control": COVER_CACHE_CONTROL,
                    "X-BookPal-Cache": "hit" if remote.from_cache else "miss",
                },
            )
        except UnsupportedOperation:
            pass  # bron onbereikbaar; val terug op de pagina zelf

    path = deps.book_file_path(session, book)
    source = open_source(path)

    # Een handmatig gekozen omslagpagina geldt voor de hele serie, niet alleen
    # voor het eerste deel: bij scanlations zit de reclame op pagina 1 van elk
    # hoofdstuk, dus juist de deel-kaartjes hebben die keuze nodig.
    page_index = gekozen_pagina
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


@router.post("/{book_id}/read-state", response_model=ReadStateOut)
def set_read_state(
    book_id: int, payload: ReadStateIn, session: Session = Depends(get_session)
) -> ReadStateOut:
    """Zelf zeggen of je dit gelezen hebt.

    Nodig omdat de automatiek soms te gretig is: een kort hoofdstuk staat na één
    blik op 100%, en "markeer eerdere als gelezen" pakt weleens één deel te
    veel. Zonder weg terug blijft dat staan.

    Het geldt voor de aflevering en niet voor het bestand: heb je hoofdstuk 5 in
    de gekleurde uitgave gelezen en zet je hem hier op ongelezen, dan verdwijnt
    ook het vinkje op de zwart-witte. Anders zou hij bij het wisselen van
    voorkeur weer opduiken.
    """
    book = deps.get_book(session, book_id)
    user = current_user(session)

    boeken = list(session.scalars(select(Book).where(Book.series_id == book.series_id)))
    uitgaven = list(session.scalars(select(Edition).where(Edition.series_id == book.series_id)))
    familie = [book]
    for slot in editions.slots(boeken, uitgaven):
        if any(item.id == book.id for item in slot.books):
            familie = slot.books
            break

    rijen = {
        row.book_id: row
        for row in session.scalars(
            select(Progress).where(
                Progress.user_id == user.id,
                Progress.book_id.in_([item.id for item in familie]),
            )
        )
    }

    if payload.finished:
        row = rijen.get(book.id)
        if row is None:
            row = Progress(user_id=user.id, book_id=book.id)
            session.add(row)
        row.position = {"page": max(0, (book.page_count or 1) - 1)}
        row.percent = 100.0
        row.finished = True
        row.device = "web"
        row.updated_at = utcnow()
    else:
        for row in rijen.values():
            session.delete(row)

    session.commit()
    return ReadStateOut(book_id=book.id, finished=payload.finished, affected=len(familie))
