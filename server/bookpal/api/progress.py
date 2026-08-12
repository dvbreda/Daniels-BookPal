"""Leesvoortgang.

Eén endpoint voor alle clients — web, Lite, iOS en de Kobo-app — zodat er één
waarheid is en geen vertaallaag tussen apparaat-specifieke identifiers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.models import Book, Progress
from bookpal.schemas import ProgressIn, ProgressOut

from . import deps

router = APIRouter(prefix="/api/progress", tags=["progress"])


@router.get("", response_model=list[ProgressOut])
def list_progress(
    limit: int = Query(default=50, ge=1, le=500),
    unfinished_only: bool = True,
    session: Session = Depends(get_session),
) -> list[ProgressOut]:
    """Wat je aan het lezen bent, meest recent eerst."""
    user = current_user(session)
    statement = select(Progress).where(Progress.user_id == user.id)
    if unfinished_only:
        statement = statement.where(Progress.finished.is_(False))
    rows = session.scalars(statement.order_by(Progress.updated_at.desc()).limit(limit)).all()
    return [ProgressOut.model_validate(row) for row in rows]


@router.get("/{book_id}", response_model=ProgressOut)
def get_progress(book_id: int, session: Session = Depends(get_session)) -> ProgressOut:
    user = current_user(session)
    row = session.scalar(
        select(Progress).where(Progress.user_id == user.id, Progress.book_id == book_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="nog geen voortgang voor dit boek")
    return ProgressOut.model_validate(row)


@router.put("", response_model=ProgressOut)
def set_progress(payload: ProgressIn, session: Session = Depends(get_session)) -> ProgressOut:
    """Positie opslaan.

    Laatste schrijver wint. Dat is bewust simpel: bij één lezer op meerdere
    apparaten is de laatste actie vrijwel altijd de bedoelde, en de tijdstempel
    plus het apparaat blijven bewaard zodat een client een conflict alsnog kan
    laten zien.
    """
    user = current_user(session)
    book = session.get(Book, payload.book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="boek niet gevonden")

    row = deps.upsert_progress(
        session,
        user,
        payload.book_id,
        series_id=book.series_id,
        position=payload.position,
        percent=payload.percent,
        device=payload.device,
        finished=payload.finished or payload.percent >= 100.0,
    )
    return ProgressOut.model_validate(row)


@router.delete("/{book_id}", status_code=204)
def clear_progress(book_id: int, session: Session = Depends(get_session)) -> None:
    user = current_user(session)
    row = session.scalar(
        select(Progress).where(Progress.user_id == user.id, Progress.book_id == book_id)
    )
    if row is not None:
        session.delete(row)
        session.commit()
