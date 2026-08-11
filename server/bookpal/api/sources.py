"""Bronnen, zoeken, abonnementen en downloads (M5).

De bron-implementaties zelf staan in ``bookpal/sources/``; deze router doet
alleen het koppelen aan de database en het vertalen van bronfouten naar nette
HTTP-antwoorden.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.db import get_session
from bookpal.models import Book, Series, Source, Subscription, SubscriptionPolicy, utcnow
from bookpal.schemas import (
    DownloadIn,
    SearchResultOut,
    SourceIn,
    SourceOut,
    SubscribeIn,
    SubscribeResultOut,
    SubscriptionOut,
)
from bookpal.sources import REGISTRY, SourceError, get_source
from bookpal.sources import service as source_service

from . import deps

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _get_source_row(session: Session, source_id: int) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="bron niet gevonden")
    if not source.enabled:
        raise HTTPException(status_code=409, detail="deze bron staat uit")
    return source


def _implementation(source: Source):  # type: ignore[no-untyped-def]
    try:
        return get_source(source.type)
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/types", response_model=list[str])
def list_types() -> list[str]:
    """Welke bron-implementaties deze build kent."""
    return sorted(REGISTRY)


@router.get("", response_model=list[SourceOut])
def list_sources(session: Session = Depends(get_session)) -> list[SourceOut]:
    rows = session.scalars(select(Source).order_by(Source.name)).all()
    return [SourceOut.model_validate(row) for row in rows]


@router.post("", response_model=SourceOut, status_code=201)
def create_source(payload: SourceIn, session: Session = Depends(get_session)) -> SourceOut:
    if payload.type not in REGISTRY:
        raise HTTPException(status_code=400, detail=f"onbekende bron: {payload.type}")
    source = Source(type=payload.type, name=payload.name, enabled=payload.enabled)
    session.add(source)
    session.commit()
    return SourceOut.model_validate(source)


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: int, session: Session = Depends(get_session)) -> None:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="bron niet gevonden")
    session.delete(source)
    session.commit()


@router.get("/{source_id}/search", response_model=list[SearchResultOut])
def search(
    source_id: int,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[SearchResultOut]:
    source = _get_source_row(session, source_id)
    implementation = _implementation(source)
    try:
        results = implementation.search(q, limit=limit)
    except SourceError as exc:
        # 502: het verzoek klopt, de bron speelt niet mee.
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    known = {
        series.source_ref: series.id
        for series in session.scalars(select(Series).where(Series.source_id == source.id))
        if series.source_ref
    }
    return [
        SearchResultOut(
            ref=result.ref,
            title=result.title,
            description=result.description,
            year=result.year,
            status=result.status,
            original_language=result.original_language,
            tracker_ids=result.tracker_ids,
            subscribed_series_id=known.get(result.ref),
        )
        for result in results
    ]


def _subscription_out(session: Session, subscription: Subscription) -> SubscriptionOut:
    series = session.get(Series, subscription.series_id)
    total = int(
        session.scalar(
            select(func.count(Book.id)).where(Book.series_id == subscription.series_id)
        )
        or 0
    )
    local = int(
        session.scalar(
            select(func.count(Book.id)).where(
                Book.series_id == subscription.series_id, Book.file_id.isnot(None)
            )
        )
        or 0
    )
    out = SubscriptionOut.model_validate(subscription)
    out.series_title = series.title if series else ""
    out.chapters_total = total
    out.chapters_local = local
    return out


@router.post("/{source_id}/subscribe", response_model=SubscribeResultOut, status_code=201)
def subscribe(
    source_id: int, payload: SubscribeIn, session: Session = Depends(get_session)
) -> SubscribeResultOut:
    """Volg een serie: hoofdstukken komen binnen als boeken zonder bestand."""
    source = _get_source_row(session, source_id)
    implementation = _implementation(source)
    try:
        series, subscription, added = source_service.subscribe(
            session,
            source,
            implementation,
            payload.ref,
            policy=SubscriptionPolicy(payload.policy),
            readahead_n=payload.readahead_n,
            ttl_days=payload.ttl_days,
            language=payload.language,
        )
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.commit()
    return SubscribeResultOut(
        subscription=_subscription_out(session, subscription),
        series_id=series.id,
        chapters_added=added,
    )


@router.get("/subscriptions/all", response_model=list[SubscriptionOut])
def list_subscriptions(session: Session = Depends(get_session)) -> list[SubscriptionOut]:
    rows = session.scalars(select(Subscription).order_by(Subscription.id)).all()
    return [_subscription_out(session, row) for row in rows]


@router.post("/subscriptions/{subscription_id}/refresh", response_model=SubscribeResultOut)
def refresh_subscription(
    subscription_id: int,
    language: str = Query(default="en", max_length=8),
    session: Session = Depends(get_session),
) -> SubscribeResultOut:
    """Kijk of er nieuwe hoofdstukken zijn."""
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="abonnement niet gevonden")
    source = _get_source_row(session, subscription.source_id)
    series = session.get(Series, subscription.series_id)
    if series is None or series.source_ref is None:
        raise HTTPException(status_code=409, detail="deze serie heeft geen bron-referentie")

    implementation = _implementation(source)
    try:
        chapters = implementation.chapters(series.source_ref, language=language)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    added, _ = source_service.sync_chapters(session, series, chapters)
    subscription.last_checked_at = utcnow()
    session.commit()
    return SubscribeResultOut(
        subscription=_subscription_out(session, subscription),
        series_id=series.id,
        chapters_added=added,
    )


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def unsubscribe(subscription_id: int, session: Session = Depends(get_session)) -> None:
    """Stop met volgen. De al binnengehaalde hoofdstukken blijven staan."""
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="abonnement niet gevonden")
    session.delete(subscription)
    session.commit()


@router.post("/books/{book_id}/download", status_code=200)
def download_chapter(
    book_id: int, payload: DownloadIn, session: Session = Depends(get_session)
) -> dict[str, object]:
    """Haal één hoofdstuk lokaal binnen."""
    book = deps.get_book(session, book_id)
    if book.source_id is None:
        raise HTTPException(status_code=409, detail="dit boek komt niet van een bron")
    source = _get_source_row(session, book.source_id)
    implementation = _implementation(source)
    try:
        source_service.download_book(
            session,
            implementation,
            book,
            data_saver=payload.data_saver,
            temporary=payload.temporary,
            ttl_days=payload.ttl_days,
        )
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.commit()
    return {"book_id": book.id, "has_file": book.file_id is not None, "expires_at": book.expires_at}


@router.post("/downloads/expire", status_code=200)
def expire_downloads(session: Session = Depends(get_session)) -> dict[str, int]:
    """Ruim verlopen tijdelijke downloads op."""
    removed = source_service.expire_downloads(session)
    session.commit()
    return {"removed": removed}
