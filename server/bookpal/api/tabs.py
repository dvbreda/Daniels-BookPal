"""Tabs: opslaanbare regels (M3, ontwerp 2). Zelfde regel-engine als
slimme collecties — alleen tabs hebben er een volgorde en weergave bij."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.models import Series, Tab
from bookpal.schemas import Paginated, SeriesOut, TabIn, TabOut
from bookpal.tabs import RuleError, compile_rule

from . import deps

router = APIRouter(prefix="/api/tabs", tags=["tabs"])


def _get_tab(session: Session, tab_id: int) -> Tab:
    tab = session.get(Tab, tab_id)
    if tab is None:
        raise HTTPException(status_code=404, detail="tab niet gevonden")
    return tab


def _validate_rule(rule: dict[str, Any], session: Session) -> None:
    try:
        compile_rule(rule, user=current_user(session))
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[TabOut])
def list_tabs(session: Session = Depends(get_session)) -> list[TabOut]:
    rows = session.scalars(select(Tab).order_by(Tab.position, Tab.id)).all()
    return [TabOut.model_validate(row) for row in rows]


@router.post("", response_model=TabOut, status_code=201)
def create_tab(payload: TabIn, session: Session = Depends(get_session)) -> TabOut:
    _validate_rule(payload.rule, session)
    tab = Tab(**payload.model_dump())
    session.add(tab)
    session.commit()
    return TabOut.model_validate(tab)


@router.get("/{tab_id}", response_model=TabOut)
def get_tab(tab_id: int, session: Session = Depends(get_session)) -> TabOut:
    return TabOut.model_validate(_get_tab(session, tab_id))


@router.patch("/{tab_id}", response_model=TabOut)
def update_tab(tab_id: int, payload: TabIn, session: Session = Depends(get_session)) -> TabOut:
    _validate_rule(payload.rule, session)
    tab = _get_tab(session, tab_id)
    for key, value in payload.model_dump().items():
        setattr(tab, key, value)
    session.commit()
    return TabOut.model_validate(tab)


@router.delete("/{tab_id}", status_code=204)
def delete_tab(tab_id: int, session: Session = Depends(get_session)) -> None:
    tab = _get_tab(session, tab_id)
    session.delete(tab)
    session.commit()


@router.get("/{tab_id}/series", response_model=Paginated[SeriesOut])
def tab_series(
    tab_id: int,
    search: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=500),
    session: Session = Depends(get_session),
) -> Paginated[SeriesOut]:
    """De series die deze tab toont — dezelfde where-clausule die /api/series
    tot M3 met losse querystring-parameters bouwde, nu uit de regel."""
    tab = _get_tab(session, tab_id)
    user = current_user(session)
    try:
        condition = compile_rule(tab.rule, user=user)
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    statement = select(Series).where(condition)
    counter = select(func.count(Series.id)).where(condition)
    if search:
        statement = statement.where(Series.title.ilike(f"%{search}%"))
        counter = counter.where(Series.title.ilike(f"%{search}%"))

    total = int(session.scalar(counter) or 0)
    rows = session.scalars(statement.order_by(Series.sort_title).offset(offset).limit(limit)).all()
    items = deps.series_out_list(session, list(rows))
    return Paginated(items=items, total=total, offset=offset, limit=limit)
