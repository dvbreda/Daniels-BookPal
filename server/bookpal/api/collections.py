"""Slimme collecties (M3, ontwerp 2). Dezelfde regel-engine als tabs; het
verschil is groepering (``group_by``) in plaats van volgorde en weergave."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.models import Collection, Series
from bookpal.schemas import CollectionIn, CollectionOut, Paginated, SeriesOut
from bookpal.tabs import RuleError, compile_rule

from . import deps

router = APIRouter(prefix="/api/collections", tags=["collections"])


def _get_collection(session: Session, collection_id: int) -> Collection:
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collectie niet gevonden")
    return collection


def _validate_rule(rule: dict[str, Any], session: Session) -> None:
    try:
        compile_rule(rule, user=current_user(session))
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[CollectionOut])
def list_collections(session: Session = Depends(get_session)) -> list[CollectionOut]:
    rows = session.scalars(select(Collection).order_by(Collection.name)).all()
    return [CollectionOut.model_validate(row) for row in rows]


@router.post("", response_model=CollectionOut, status_code=201)
def create_collection(
    payload: CollectionIn, session: Session = Depends(get_session)
) -> CollectionOut:
    _validate_rule(payload.rule, session)
    collection = Collection(**payload.model_dump())
    session.add(collection)
    session.commit()
    return CollectionOut.model_validate(collection)


@router.get("/{collection_id}", response_model=CollectionOut)
def get_collection(collection_id: int, session: Session = Depends(get_session)) -> CollectionOut:
    return CollectionOut.model_validate(_get_collection(session, collection_id))


@router.patch("/{collection_id}", response_model=CollectionOut)
def update_collection(
    collection_id: int, payload: CollectionIn, session: Session = Depends(get_session)
) -> CollectionOut:
    _validate_rule(payload.rule, session)
    collection = _get_collection(session, collection_id)
    for key, value in payload.model_dump().items():
        setattr(collection, key, value)
    session.commit()
    return CollectionOut.model_validate(collection)


@router.delete("/{collection_id}", status_code=204)
def delete_collection(collection_id: int, session: Session = Depends(get_session)) -> None:
    collection = _get_collection(session, collection_id)
    session.delete(collection)
    session.commit()


@router.get("/{collection_id}/series", response_model=Paginated[SeriesOut])
def collection_series(
    collection_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=500),
    session: Session = Depends(get_session),
) -> Paginated[SeriesOut]:
    collection = _get_collection(session, collection_id)
    user = current_user(session)
    try:
        condition = compile_rule(collection.rule, user=user)
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    total = int(session.scalar(select(func.count(Series.id)).where(condition)) or 0)
    rows = session.scalars(
        select(Series).where(condition).order_by(Series.sort_title).offset(offset).limit(limit)
    ).all()
    items = deps.series_out_list(session, list(rows))
    return Paginated(items=items, total=total, offset=offset, limit=limit)
