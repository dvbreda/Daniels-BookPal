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
from bookpal.models import (
    Book,
    Edition,
    Progress,
    Series,
    Source,
    Subscription,
    SubscriptionPolicy,
    utcnow,
)
from bookpal.schemas import (
    ChapterCountOut,
    DownloadIn,
    RunReportOut,
    SearchResultOut,
    SourceIn,
    SourceOut,
    SubscribeIn,
    SubscribeResultOut,
    SubscriptionOut,
    SubscriptionPatch,
)
from bookpal.sources import REGISTRY, SourceError, worker
from bookpal.sources import service as source_service

from . import deps

router = APIRouter(prefix="/api/sources", tags=["sources"])

# Gedeeld met api/series.py (omslag koppelen zonder te abonneren).
_get_source_row = deps.get_source_row
_implementation = deps.get_source_implementation


@router.get("/types", response_model=list[str])
def list_types() -> list[str]:
    """Welke bron-implementaties deze build kent."""
    return sorted(REGISTRY)


@router.get("", response_model=list[SourceOut])
def list_sources(session: Session = Depends(get_session)) -> list[SourceOut]:
    rows = session.scalars(select(Source).order_by(Source.name)).all()
    return [_hide_secrets(SourceOut.model_validate(row)) for row in rows]


def _hide_secrets(out: SourceOut) -> SourceOut:
    """Een wachtwoord dat binnenkwam hoeft er niet weer uit.

    Het staat in de database omdat de bron het nodig heeft; het teruggeven aan
    elke client die de bronnenlijst opvraagt voegt daar niets aan toe.
    """
    if "password" in out.config:
        out.config = {**out.config, "password": "••••••"}
    return out


@router.post("", response_model=SourceOut, status_code=201)
def create_source(payload: SourceIn, session: Session = Depends(get_session)) -> SourceOut:
    if payload.type not in REGISTRY:
        raise HTTPException(status_code=400, detail=f"onbekende bron: {payload.type}")
    source = Source(
        type=payload.type,
        name=payload.name,
        enabled=payload.enabled,
        config=payload.config,
    )
    session.add(source)
    session.flush()

    # Meteen proberen: een adres met een typefout hoort je nú te bereiken, niet
    # pas als je gaat zoeken en niet begrijpt waarom er niets komt.
    try:
        implementation = _implementation(source)
        implementation.search("", limit=1)
    except SourceError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=f"deze bron werkt niet: {exc}") from exc
    except HTTPException:
        session.rollback()
        raise

    session.commit()
    return _hide_secrets(SourceOut.model_validate(source))


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
    language: str | None = Query(
        default=None,
        max_length=8,
        description="Alleen reeksen die in deze taal vertaald zijn; leeg is alles.",
    ),
    session: Session = Depends(get_session),
) -> list[SearchResultOut]:
    source = _get_source_row(session, source_id)
    implementation = _implementation(source)
    try:
        results = implementation.search(q, limit=limit, language=language or None)
    except SourceError as exc:
        # 502: het verzoek klopt, de bron speelt niet mee.
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Wat je al volgt, op de reeks van het abonnement zelf: een serie kan er
    # meerdere hebben en Series.source_ref wijst er dan maar naar één.
    known = {
        row.source_ref: row.series_id
        for row in session.scalars(select(Subscription).where(Subscription.source_id == source.id))
        if row.source_ref
    }
    for series in session.scalars(select(Series).where(Series.source_id == source.id)):
        if series.source_ref:
            known.setdefault(series.source_ref, series.id)

    uitvoer: list[SearchResultOut] = []
    for result in results:
        # Alleen als je hem nog niet volgt: anders is "je volgt dit al" het
        # nuttigere bericht.
        bestaand = None if result.ref in known else source_service.find_existing(session, result)
        uitvoer.append(
            SearchResultOut(
                ref=result.ref,
                title=result.title,
                description=result.description,
                year=result.year,
                status=result.status,
                original_language=result.original_language,
                tracker_ids=result.tracker_ids,
                subscribed_series_id=known.get(result.ref),
                existing_series_id=bestaand.id if bestaand else None,
                existing_series_title=bestaand.title if bestaand else None,
                cover_url=result.cover_url,
                url=result.url,
                languages=result.languages,
            )
        )
    return uitvoer


def _subscription_out(session: Session, subscription: Subscription) -> SubscriptionOut:
    series = session.get(Series, subscription.series_id)

    # Tellen binnen de uitgave van dít abonnement. Een serie kan er meerdere
    # hebben — een Engelse vertaling naast het Japanse origineel — en dan zou
    # per serie tellen bij beide hetzelfde getal geven.
    edition = session.scalar(select(Edition).where(Edition.subscription_id == subscription.id))
    van_deze = select(Book).where(Book.series_id == subscription.series_id)
    if edition is not None:
        van_deze = van_deze.where(Book.edition_id == edition.id)

    total = int(session.scalar(select(func.count()).select_from(van_deze.subquery())) or 0)
    local = int(
        session.scalar(
            select(func.count()).select_from(van_deze.where(Book.file_id.isnot(None)).subquery())
        )
        or 0
    )
    out = SubscriptionOut.model_validate(subscription)
    out.series_title = series.title if series else ""
    out.source_title = edition.name if edition is not None else ""
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


@router.get("/subscriptions/by-series/{series_id}", response_model=list[SubscriptionOut])
def subscriptions_for_series(
    series_id: int, session: Session = Depends(get_session)
) -> list[SubscriptionOut]:
    """De abonnementen van deze serie.

    Een lijst en niet één, want een serie kan er meerdere hebben: een Engelse
    vertaling naast het Japanse origineel, of een gekleurde uitgave naast de
    zwart-witte. De seriepagina toont per abonnement de keuze van vertaalgroep,
    want die keuze geldt per bron en niet per serie.
    """
    rows = session.scalars(
        select(Subscription).where(Subscription.series_id == series_id).order_by(Subscription.id)
    ).all()
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

    added, _ = source_service.sync_chapters(session, series, chapters, subscription=subscription)
    subscription.last_checked_at = utcnow()
    session.commit()
    return SubscribeResultOut(
        subscription=_subscription_out(session, subscription),
        series_id=series.id,
        chapters_added=added,
    )


@router.patch("/subscriptions/{subscription_id}", response_model=SubscribeResultOut)
def update_subscription(
    subscription_id: int,
    payload: SubscriptionPatch,
    language: str = Query(default="en", max_length=8),
    session: Session = Depends(get_session),
) -> SubscribeResultOut:
    """Instellingen van een abonnement bijstellen.

    Bij een andere voorkeursgroep wordt meteen opnieuw gesynchroniseerd: de
    hoofdstukken van die groep bestaan nog niet als boek, want die vielen bij
    het ontdubbelen af. Al opgehaalde afleveringen blijven staan.
    """
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="abonnement niet gevonden")

    group_changed = (
        "preferred_group_id" in payload.model_fields_set
        and payload.preferred_group_id != subscription.preferred_group_id
    )
    if "preferred_group_id" in payload.model_fields_set:
        subscription.preferred_group_id = payload.preferred_group_id
    if payload.policy is not None:
        subscription.policy = SubscriptionPolicy(payload.policy)
    if payload.readahead_n is not None:
        subscription.readahead_n = payload.readahead_n
    if payload.ttl_days is not None:
        subscription.ttl_days = payload.ttl_days

    added = 0
    series = session.get(Series, subscription.series_id)
    ref = subscription.source_ref or (series.source_ref if series else None)
    if group_changed and series is not None and ref:
        source = _get_source_row(session, subscription.source_id)
        implementation = _implementation(source)
        try:
            # De taal van het abonnement, niet die van het verzoek: anders
            # klapt een Japans abonnement om zodra je er iets anders aan
            # bijstelt.
            chapters = implementation.chapters(ref, language=subscription.language)
        except SourceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        added, _ = source_service.sync_chapters(
            session, series, chapters, subscription=subscription
        )
        subscription.last_checked_at = utcnow()

    session.commit()
    return SubscribeResultOut(
        subscription=_subscription_out(session, subscription),
        series_id=subscription.series_id,
        chapters_added=added,
    )


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def unsubscribe(subscription_id: int, session: Session = Depends(get_session)) -> None:
    """Stop met volgen.

    Wat je hebt binnengehaald blijft staan — dat is van jou. Wat alleen een
    verwijzing naar de bron was verdwijnt: zonder abonnement kun je het niet
    meer ophalen, dus het zou een hoofdstuk zijn dat je alleen maar kunt
    aankijken. Blijft er daarna niets over, dan gaat ook de serie weg; anders
    houd je een lege huls in je bibliotheek.

    Alles waarin je gelezen hebt blijft óók staan, ook zonder bestand: dat is
    een spoor van jou en geen restje van de bron.
    """
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="abonnement niet gevonden")

    series_id = subscription.series_id
    session.delete(subscription)
    session.flush()

    # Alleen opruimen als er geen ánder abonnement op deze serie meer is.
    resterend = session.scalar(
        select(func.count(Subscription.id)).where(Subscription.series_id == series_id)
    )
    if not resterend:
        gelezen = set(
            session.scalars(
                select(Progress.book_id)
                .join(Book, Book.id == Progress.book_id)
                .where(Book.series_id == series_id)
            )
        )
        for book in session.scalars(select(Book).where(Book.series_id == series_id)):
            if book.file_id is None and book.id not in gelezen:
                session.delete(book)
        session.flush()

        over = session.scalar(select(func.count(Book.id)).where(Book.series_id == series_id))
        if not over:
            series = session.get(Series, series_id)
            if series is not None:
                session.delete(series)

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


@router.post("/run", response_model=RunReportOut)
def run_now(
    refresh: bool = Query(default=True, description="Nieuwe hoofdstukken ophalen"),
    download: bool = Query(default=True, description="Vooruitlezen ophalen"),
    session: Session = Depends(get_session),
) -> RunReportOut:
    """Doe nu wat de achtergrond-worker anders op zijn interval doet.

    Handig om niet op de klok te hoeven wachten, en om te zien wat er zou
    gebeuren voordat je de worker aanzet.
    """
    report = worker.run_once(session, refresh=refresh, download=download)
    return RunReportOut(
        subscriptions=report.subscriptions,
        chapters_added=report.chapters_added,
        downloaded=report.downloaded,
        expired=report.expired,
        errors=report.errors,
    )


@router.get("/{source_id}/chapter-count", response_model=ChapterCountOut)
def chapter_count(
    source_id: int,
    ref: str = Query(max_length=200),
    language: str = Query(default="en", max_length=8),
    session: Session = Depends(get_session),
) -> ChapterCountOut:
    """Hoeveel hoofdstukken deze reeks in deze taal heeft.

    Apart en niet in de zoekresultaten: het kost een verzoek per treffer, en dat
    hoort het zoeken zelf niet trager te maken. De client vraagt het per kaartje
    op zodra die in beeld is.
    """
    source = _get_source_row(session, source_id)
    implementation = _implementation(source)
    teller = getattr(implementation, "chapter_count", None)
    if teller is None:
        raise HTTPException(status_code=501, detail="deze bron telt geen hoofdstukken")
    try:
        aantal = int(teller(ref, language=language))
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChapterCountOut(ref=ref, language=language, count=aantal)
