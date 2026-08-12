"""Trackers: MyAnimeList koppelen en pushen, Goodreads als CSV-export (M7).

Eenrichting — zie bookpal/trackers/base.py. Goodreads heeft geen eigen
``TrackerAccount``: de publieke API is dood, dus is er niets om te koppelen of
aan/uit te zetten. De export is gewoon altijd beschikbaar.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
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
def mal_authorize_url(
    account_id: int, request: Request, session: Session = Depends(get_session)
) -> MalAuthorizeOut:
    """De URL waar je je MyAnimeList-account koppelt.

    Het terugkeeradres wordt afgeleid uit het adres waarop je BookPal nu
    gebruikt, zodat MyAnimeList je hierheen terugstuurt en de code vanzelf
    wordt ingewisseld. Datzelfde adres moet in je MAL-app-registratie staan;
    de client krijgt het daarom mee om te tonen.
    """
    account = _get_account(session, account_id)
    if account.provider != "mal":
        raise HTTPException(status_code=409, detail="alleen MyAnimeList gebruikt dit")
    client_id = account.credentials.get("client_id")
    if not client_id:
        raise HTTPException(status_code=409, detail="geen client_id ingesteld voor dit account")

    verifier = make_code_verifier()
    # De state koppelt de terugkeer aan dit account: het redirect-endpoint
    # krijgt verder niets mee waaraan het kan zien wie er terugkomt.
    state = secrets.token_urlsafe(16)
    redirect_uri = _redirect_uri(request)
    account.credentials = {
        **account.credentials,
        "_pending_verifier": verifier,
        "_pending_state": state,
        "_pending_redirect": redirect_uri,
    }
    session.commit()
    return MalAuthorizeOut(
        url=authorize_url(client_id, verifier, state=state, redirect_uri=redirect_uri),
        redirect_uri=redirect_uri,
    )


def _redirect_uri(request: Request) -> str:
    """Waar MyAnimeList je heen terugstuurt.

    Afgeleid uit het huidige adres in plaats van uit een instelling: je bereikt
    de NAS thuis anders dan via ZeroTier, en een vast adres zou dan bij een van
    de twee niet kloppen.
    """
    return str(request.url_for("mal_redirect"))


@router.get("/mal/redirect", name="mal_redirect", include_in_schema=False)
def mal_redirect(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Waar MyAnimeList je na het inloggen heen stuurt.

    Wisselt de code meteen in en stuurt je door naar de trackerspagina, zodat
    je nooit iets hoeft over te typen.
    """
    if error or not code or not state:
        return RedirectResponse(url="/trackers?mal=mislukt", status_code=303)

    rows = session.scalars(select(TrackerAccount).where(TrackerAccount.provider == "mal"))
    account = next(
        (row for row in rows if row.credentials.get("_pending_state") == state), None
    )
    if account is None:
        return RedirectResponse(url="/trackers?mal=onbekend", status_code=303)

    verifier = account.credentials.get("_pending_verifier")
    redirect_uri = account.credentials.get("_pending_redirect")
    tracker = MyAnimeListTracker(account.credentials)
    try:
        tracker.exchange_code(code, str(verifier), redirect_uri=redirect_uri)
    except TrackerError:
        return RedirectResponse(url="/trackers?mal=mislukt", status_code=303)
    finally:
        tracker.close()

    credentials = dict(tracker.credentials)
    for key in ("_pending_verifier", "_pending_state", "_pending_redirect"):
        credentials.pop(key, None)
    account.credentials = credentials
    session.commit()
    return RedirectResponse(url="/trackers?mal=gekoppeld", status_code=303)


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
