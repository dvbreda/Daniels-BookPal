"""Gedeelde dependencies en hulpfuncties voor de routers."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.db import get_session
from bookpal.images import ImageProfile, get_profile
from bookpal.models import Book, File, Progress, Series, User, utcnow
from bookpal.schemas import BookOut, ProgressOut, SeriesOut

SessionDep = Depends(get_session)


def profile_param(
    profile: str | None = Query(
        default=None,
        description="Beeldprofiel, bv. 'web', 'thumb' of 'kobo-clara'.",
    ),
) -> ImageProfile:
    try:
        return get_profile(profile)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"onbekend beeldprofiel: {profile}") from None


ProfileDep = Depends(profile_param)


def get_book(session: Session, book_id: int) -> Book:
    book = session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="boek niet gevonden")
    return book


def get_series(session: Session, series_id: int) -> Series:
    series = session.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="serie niet gevonden")
    return series


def book_file_path(session: Session, book: Book) -> Path:
    """Het pad op schijf, met nette fouten voor de twee dingen die echt misgaan:
    een boek dat alleen online bestaat, en een bestand dat weg is."""
    if book.file_id is None:
        raise HTTPException(
            status_code=409,
            detail="dit boek heeft nog geen lokaal bestand; download het eerst",
        )
    file_row = session.get(File, book.file_id)
    if file_row is None:
        raise HTTPException(status_code=404, detail="bestand niet gevonden")
    path = Path(file_row.path)
    if not path.is_file():
        raise HTTPException(
            status_code=410,
            detail="het bestand staat niet meer op deze plek; draai een scan",
        )
    return path


def upsert_progress(
    session: Session,
    user: User,
    book_id: int,
    *,
    position: dict[str, object],
    percent: float,
    device: str | None,
    finished: bool | None = None,
) -> Progress:
    """Positie opslaan. Laatste schrijver wint — gedeeld door de REST-endpoint
    en Lite, zodat een paginaomslag in de Kobo-browser dezelfde waarheid
    bijwerkt als een tap in de web-app."""
    row = session.scalar(
        select(Progress).where(Progress.user_id == user.id, Progress.book_id == book_id)
    )
    if row is None:
        row = Progress(user_id=user.id, book_id=book_id)
        session.add(row)

    row.position = position
    row.percent = percent
    row.finished = finished if finished is not None else percent >= 100.0
    row.device = device
    row.updated_at = utcnow()
    session.commit()
    return row


def progress_for(session: Session, user: User, book_ids: list[int]) -> dict[int, Progress]:
    if not book_ids:
        return {}
    rows = session.scalars(
        select(Progress).where(Progress.user_id == user.id, Progress.book_id.in_(book_ids))
    )
    return {row.book_id: row for row in rows}


def to_book_out(book: Book, progress: Progress | None, extension: str | None) -> BookOut:
    return BookOut(
        id=book.id,
        series_id=book.series_id,
        kind=book.kind,
        title=book.title,
        number=book.number,
        volume=book.volume,
        page_count=book.page_count,
        right_to_left=book.right_to_left,
        has_file=book.file_id is not None,
        extension=extension,
        added_at=book.added_at,
        progress=ProgressOut.model_validate(progress) if progress is not None else None,
    )


def to_series_out(series: Series, book_count: int, kinds: list[str]) -> SeriesOut:
    return SeriesOut(
        id=series.id,
        title=series.title,
        sort_title=series.sort_title,
        library_root_id=series.library_root_id,
        folder_path=series.folder_path,
        origin_language=series.origin_language,
        origin_country=series.origin_country,
        origin_region=series.origin_region,
        origin_source=series.origin_source,
        publisher=series.publisher,
        tags=series.tags,
        summary=series.summary,
        book_count=book_count,
        kinds=kinds,  # type: ignore[arg-type]
    )


def series_out_list(session: Session, rows: list[Series]) -> list[SeriesOut]:
    """Series met hun boekentelling en soorten — gedeeld door /api/series,
    tabs en collecties, want ze tonen allemaal dezelfde serie-kaart."""
    items: list[SeriesOut] = []
    for series in rows:
        counts = session.execute(
            select(Book.kind, func.count(Book.id))
            .where(Book.series_id == series.id)
            .group_by(Book.kind)
        ).all()
        book_count = sum(int(count) for _, count in counts)
        kinds = [str(k.value if hasattr(k, "value") else k) for k, _ in counts]
        items.append(to_series_out(series, book_count, kinds))
    return items
