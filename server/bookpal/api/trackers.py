"""Trackers: MyAnimeList koppelen en pushen, Goodreads als CSV-export (M7).

Eenrichting — zie bookpal/trackers/base.py. Goodreads heeft geen eigen
``TrackerAccount``: de publieke API is dood, dus is er niets om te koppelen of
aan/uit te zetten. De export is gewoon altijd beschikbaar.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.models import TrackerAccount
from bookpal.schemas import (
    MalAuthorizeOut,
    MalCallbackIn,
    PushReportOut,
    PushResultOut,
    TrackerAccountIn,
    TrackerAccountOut,
    TrackerAccountPatch,
)
from bookpal.trackers import REGISTRY, TrackerError, export_csv, get_tracker
from bookpal.trackers import service as tracker_service
from bookpal.trackers.mal import MyAnimeListTracker, authorize_url, make_code_verifier

router = APIRouter(prefix="/api/trackers", tags=["trackers"])


def _get_account(session: Session, account_id: int) -> TrackerAccount:
    account = session.get(TrackerAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="tracker-account niet gevonden")
    return account


def _to_out(account: TrackerAccount) -> TrackerAccountOut:
    out = TrackerAccountOut.model_validate(account)
    out.connected = bool(account.credentials.get("access_token"))
    return out


@router.get("", response_model=list[TrackerAccountOut])
def list_trackers(session: Session = Depends(get_session)) -> list[TrackerAccountOut]:
    rows = session.scalars(select(TrackerAccount).order_by(TrackerAccount.provider)).all()
    return [_to_out(row) for row in rows]


@router.post("", response_model=TrackerAccountOut, status_code=201)
def create_tracker(
    payload: TrackerAccountIn, session: Session = Depends(get_session)
) -> TrackerAccountOut:
    if payload.provider not in REGISTRY:
        raise HTTPException(status_code=400, detail=f"onbekende tracker: {payload.provider}")
    if session.scalar(select(TrackerAccount).where(TrackerAccount.provider == payload.provider)):
        raise HTTPException(status_code=409, detail="deze tracker is al ingesteld")

    credentials = {}
    if payload.client_id:
        credentials["client_id"] = payload.client_id
    if payload.client_secret:
        credentials["client_secret"] = payload.client_secret

    account = TrackerAccount(provider=payload.provider, credentials=credentials)
    session.add(account)
    session.commit()
    return _to_out(account)


@router.patch("/{account_id}", response_model=TrackerAccountOut)
def update_tracker(
    account_id: int, payload: TrackerAccountPatch, session: Session = Depends(get_session)
) -> TrackerAccountOut:
    account = _get_account(session, account_id)
    if payload.enabled is not None:
        account.enabled = payload.enabled
    if payload.dry_run is not None:
        account.dry_run = payload.dry_run
    session.commit()
    return _to_out(account)


@router.delete("/{account_id}", status_code=204)
def delete_tracker(account_id: int, session: Session = Depends(get_session)) -> None:
    account = _get_account(session, account_id)
    session.delete(account)
    session.commit()


@router.get("/{account_id}/mal/authorize-url", response_model=MalAuthorizeOut)
def mal_authorize_url(account_id: int, session: Session = Depends(get_session)) -> MalAuthorizeOut:
    """De URL waar je je MyAnimeList-account koppelt.

    MyAnimeList stuurt na goedkeuring door naar het redirect-adres van je
    eigen app-registratie — wat dat precies is, bepaal je daar zelf. Plak de
    ``code`` die je daar terugziet in ``/mal/callback``.
    """
    account = _get_account(session, account_id)
    if account.provider != "mal":
        raise HTTPException(status_code=409, detail="alleen MyAnimeList gebruikt dit")
    client_id = account.credentials.get("client_id")
    if not client_id:
        raise HTTPException(status_code=409, detail="geen client_id ingesteld voor dit account")

    verifier = make_code_verifier()
    account.credentials = {**account.credentials, "_pending_verifier": verifier}
    session.commit()
    return MalAuthorizeOut(url=authorize_url(client_id, verifier))


@router.post("/{account_id}/mal/callback", response_model=TrackerAccountOut)
def mal_callback(
    account_id: int, payload: MalCallbackIn, session: Session = Depends(get_session)
) -> TrackerAccountOut:
    account = _get_account(session, account_id)
    if account.provider != "mal":
        raise HTTPException(status_code=409, detail="alleen MyAnimeList gebruikt dit")
    verifier = account.credentials.get("_pending_verifier")
    if not verifier:
        raise HTTPException(
            status_code=409, detail="vraag eerst een autorisatie-URL op via .../authorize-url"
        )

    tracker = MyAnimeListTracker(account.credentials)
    try:
        tracker.exchange_code(payload.code, verifier)
    except TrackerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        tracker.close()

    credentials = dict(tracker.credentials)
    credentials.pop("_pending_verifier", None)
    account.credentials = credentials
    session.commit()
    return _to_out(account)


@router.post("/{account_id}/run", response_model=PushReportOut)
def run_tracker(account_id: int, session: Session = Depends(get_session)) -> PushReportOut:
    """Nu pushen, in plaats van te wachten tot de gedebounced trigger het doet.

    Handig voor de eerste keer na het koppelen, of om te zien wat een
    dry-run zou doen zonder eerst een boek open te slaan.
    """
    account = _get_account(session, account_id)
    if not account.enabled:
        raise HTTPException(status_code=409, detail="dit account staat uit")
    user = current_user(session)
    tracker = get_tracker(account.provider, account.credentials)
    try:
        report = tracker_service.push_all(session, tracker, account, user)
    finally:
        tracker.close()

    return PushReportOut(
        provider=report.provider,
        pushed=report.pushed,
        results=[
            PushResultOut(
                series_id=result.entry.series_id,
                title=result.entry.title,
                pushed=result.pushed,
                dry_run=result.dry_run,
                detail=result.detail,
            )
            for result in report.results
        ],
        errors=report.errors,
    )


@router.get("/goodreads/export.csv")
def goodreads_export(session: Session = Depends(get_session)) -> Response:
    """De hele bibliotheek als CSV voor Goodreads' My Books → Import and Export.

    Geen live koppeling — de publieke API is dood sinds eind 2020 — dus dit
    is het vangnet: een gedocumenteerd, stabiel formaat dat vandaag nog werkt.
    """
    user = current_user(session)
    csv_text = export_csv(tracker_service.goodreads_rows(session, user))
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bookpal-goodreads.csv"},
    )
