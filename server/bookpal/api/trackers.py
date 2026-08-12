"""Trackers: MyAnimeList koppelen en pushen, Goodreads als CSV-export (M7).

Eenrichting — zie bookpal/trackers/base.py. Goodreads heeft geen eigen
``TrackerAccount``: de publieke API is dood, dus is er niets om te koppelen of
aan/uit te zetten. De export is gewoon altijd beschikbaar.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.metadata.titles import normalise as normalise_title
from bookpal.models import Series, TrackerAccount, utcnow
from bookpal.schemas import (
    GoodreadsLoginIn,
    GoodreadsStatusOut,
    GoodreadsSyncOut,
    MalAuthorizeOut,
    MalCallbackIn,
    MalImportProgressIn,
    MalImportProgressOut,
    MalLinkIn,
    MalListItemOut,
    PushReportOut,
    PushResultOut,
    ShelfRowOut,
    ShelvesOut,
    TrackerAccountIn,
    TrackerAccountOut,
    TrackerAccountPatch,
)
from bookpal.trackers import REGISTRY, TrackerError, export_csv, get_tracker, goodreads_browser
from bookpal.trackers import service as tracker_service
from bookpal.trackers.base import ReadingStatus
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


# --- Goodreads via de browser -------------------------------------------------
#
# Goodreads heeft geen API meer en logt in via Amazon; er bestaat ook geen
# derde-partij-API die kán schrijven. Dit is dus de enige weg, en tegelijk de
# breekbaarste koppeling in de app — vandaar dat alles hier zacht faalt en een
# controle van Amazon nooit omzeild wordt maar aan jou wordt voorgelegd.

GOODREADS = "goodreads"

# De plank waar een leesstatus op uitkomt, en onder welke sleutel hij in het
# overzicht valt. "on hold" en "gestopt" gaan bij Goodreads ook naar to-read:
# die kent geen aparte planken daarvoor.
_SHELF_NAMES = {
    ReadingStatus.READING: "currently-reading",
    ReadingStatus.COMPLETED: "read",
    ReadingStatus.PLAN_TO_READ: "to-read",
    ReadingStatus.ON_HOLD: "to-read",
    ReadingStatus.DROPPED: "to-read",
}
_SHELF_KEYS = {
    ReadingStatus.READING: "reading",
    ReadingStatus.COMPLETED: "read",
    ReadingStatus.PLAN_TO_READ: "to_read",
    ReadingStatus.ON_HOLD: "to_read",
    ReadingStatus.DROPPED: "to_read",
}


def _goodreads_account(session: Session) -> TrackerAccount | None:
    return session.scalar(select(TrackerAccount).where(TrackerAccount.provider == GOODREADS))


@router.get("/goodreads/status", response_model=GoodreadsStatusOut)
def goodreads_status(session: Session = Depends(get_session)) -> GoodreadsStatusOut:
    ready, note = goodreads_browser.available()
    account = _goodreads_account(session)
    return GoodreadsStatusOut(
        browser_ready=ready,
        browser_note=note,
        connected=bool(account and account.credentials.get("session")),
        last_sync_at=account.last_sync_at if account else None,
    )


@router.post("/goodreads/install-browser", response_model=GoodreadsStatusOut)
def goodreads_install_browser(session: Session = Depends(get_session)) -> GoodreadsStatusOut:
    """Haal Chromium op. Duurt een minuut en gebeurt één keer."""
    try:
        goodreads_browser.install_browser()
    except TrackerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return goodreads_status(session)


@router.post("/goodreads/login", response_model=GoodreadsStatusOut)
def goodreads_login(
    payload: GoodreadsLoginIn, session: Session = Depends(get_session)
) -> GoodreadsStatusOut:
    """Log in bij Goodreads en bewaar de sessie.

    Het wachtwoord gaat niet de database in: alleen de sessie wordt bewaard,
    zodat er niet elke ronde opnieuw ingelogd hoeft te worden — herhaald
    inloggen is precies wat Amazon als verdacht ziet.
    """
    try:
        state = goodreads_browser.log_in(payload.email, payload.password)
    except goodreads_browser.GoodreadsChallenge as exc:
        # Amazon wil een mens zien. Dat is terecht, en niets om omheen te
        # werken: de vraag hoort bij jou terecht te komen.
        raise HTTPException(
            status_code=409,
            detail=str(exc),
            headers={"X-Goodreads-Challenge": exc.kind},
        ) from exc
    except TrackerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    account = _goodreads_account(session)
    if account is None:
        account = TrackerAccount(provider=GOODREADS)
        session.add(account)
    account.credentials = {"session": state, "email": payload.email}
    account.enabled = True
    session.commit()
    return goodreads_status(session)


@router.delete("/goodreads/login", status_code=204)
def goodreads_logout(session: Session = Depends(get_session)) -> None:
    account = _goodreads_account(session)
    if account is not None:
        session.delete(account)
        session.commit()


@router.post("/goodreads/sync", response_model=GoodreadsSyncOut)
def goodreads_sync(session: Session = Depends(get_session)) -> GoodreadsSyncOut:
    """Zet je planken bij Goodreads bij."""
    account = _goodreads_account(session)
    state = account.credentials.get("session") if account is not None else None
    if account is None or not state:
        raise HTTPException(status_code=409, detail="nog niet ingelogd bij Goodreads")

    user = current_user(session)
    entries = [
        (row.title, row.author or "", row.status)
        for row in tracker_service.goodreads_rows(session, user)
    ]
    try:
        report = goodreads_browser.push(state, entries)
    except goodreads_browser.GoodreadsChallenge as exc:
        raise HTTPException(
            status_code=409, detail=str(exc), headers={"X-Goodreads-Challenge": exc.kind}
        ) from exc
    except TrackerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    account.last_sync_at = utcnow()
    session.commit()
    return GoodreadsSyncOut(updated=report.updated, errors=report.errors)


@router.get("/shelves", response_model=ShelvesOut)
def shelves(
    provider: str = Query(default="goodreads", max_length=20),
    session: Session = Depends(get_session),
) -> ShelvesOut:
    """Wat er op je leeslijsten zou staan, per plank.

    Precies dezelfde afleiding als de export en de push gebruiken, zodat wat je
    hier ziet is wat er de deur uit gaat — en je kunt controleren of de
    leesstatus klopt voordat je iets pusht. Bij MyAnimeList staat erbij wat er
    géén id heeft, want dat is precies wat overgeslagen wordt.
    """
    user = current_user(session)
    per_shelf: dict[str, list[ShelfRowOut]] = {"reading": [], "to_read": [], "read": []}
    without_id = 0

    for series, entry, total, percent in tracker_service.shelf_rows(session, user, provider):
        # Goodreads zoekt op titel en heeft geen id nodig; MyAnimeList wel.
        pushable = provider != "mal" or entry.remote_id is not None
        if not pushable:
            without_id += 1
        per_shelf[_SHELF_KEYS[entry.status]].append(
            ShelfRowOut(
                series_id=series.id,
                title=series.title,
                author=series.authors[0] if series.authors else None,
                status=str(entry.status),
                shelf=_SHELF_NAMES[entry.status],
                chapters_read=entry.chapters_read,
                chapters_total=total,
                percent=round(percent, 1),
                remote_id=entry.remote_id,
                pushable=pushable,
            )
        )

    # Bezig bovenaan op voortgang, de rest op naam: bij "aan het lezen" wil je
    # zien waar je het verst bent, bij de andere twee zoek je op titel.
    per_shelf["reading"].sort(key=lambda row: -row.percent)
    for key in ("to_read", "read"):
        per_shelf[key].sort(key=lambda row: row.title.lower())

    return ShelvesOut(provider=provider, without_id=without_id, **per_shelf)


@router.get("/{account_id}/mal/list", response_model=list[MalListItemOut])
def mal_list(
    account_id: int,
    status: str | None = Query(default=None, max_length=20),
    session: Session = Depends(get_session),
) -> list[MalListItemOut]:
    """Je eigen MyAnimeList-lijst, om er abonnementen bij te zoeken.

    De enige plek waar BookPal van een tracker leest. Dat botst niet met het
    eenrichtingsverkeer: dat gaat over voortgang, en die blijft hier de
    waarheid. Dit haalt alleen op wát je wilt gaan lezen.
    """
    account = _get_account(session, account_id)
    if account.provider != "mal":
        raise HTTPException(status_code=409, detail="alleen MyAnimeList gebruikt dit")

    tracker = MyAnimeListTracker(account.credentials)
    try:
        items = tracker.read_list(status)
    except TrackerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        tracker.close()

    # Wat je al hebt hoeft niet opnieuw; dat scheelt zoeken bij de bron.
    alle_series = list(session.scalars(select(Series)))
    op_id = {
        str(series.tracker_ids.get("mal")): series
        for series in alle_series
        if series.tracker_ids.get("mal")
    }
    # En op titel, voor series die er wel staan maar nog geen id dragen.
    # MyAnimeList schrijft "Shinya Shokudou" waar je map "Shinya Shokudo" zegt.
    op_titel: dict[str, Series] = {}
    for series in alle_series:
        op_titel.setdefault(normalise_title(series.title), series)

    out: list[MalListItemOut] = []
    for item in items:
        gekoppeld = op_id.get(item["mal_id"])
        voorstel = None if gekoppeld else op_titel.get(normalise_title(item["title"]))
        out.append(
            MalListItemOut(
                **item,
                series_id=gekoppeld.id if gekoppeld else None,
                match_series_id=voorstel.id if voorstel else None,
                match_title=voorstel.title if voorstel else None,
            )
        )
    return out


@router.post("/{account_id}/mal/link", response_model=MalListItemOut)
def mal_link(
    account_id: int,
    payload: MalLinkIn,
    session: Session = Depends(get_session),
) -> MalListItemOut:
    """Koppel een serie uit je bibliotheek aan een reeks op MyAnimeList.

    Nodig omdat alleen series mét een id gepusht kunnen worden, en een lokale
    map dat id nergens vandaan haalt. Na het koppelen loopt je voortgang mee.
    """
    account = _get_account(session, account_id)
    if account.provider != "mal":
        raise HTTPException(status_code=409, detail="alleen MyAnimeList gebruikt dit")

    series = session.get(Series, payload.series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="die serie bestaat niet")

    series.tracker_ids = {**(series.tracker_ids or {}), "mal": payload.mal_id}
    session.commit()

    return MalListItemOut(
        mal_id=payload.mal_id,
        title=series.title,
        status="",
        series_id=series.id,
    )


@router.post("/{account_id}/mal/import-progress", response_model=MalImportProgressOut)
def mal_import_progress(
    account_id: int,
    payload: MalImportProgressIn,
    session: Session = Depends(get_session),
) -> MalImportProgressOut:
    """Neem over wat je bij MyAnimeList al gelezen had.

    Handig bij een serie die je elders begonnen bent: One Piece op 124 hoeft
    niet opnieuw doorgeklikt te worden. Vult alleen aan — wat je hier al hebt
    uitgelezen blijft staan, en er gaat nooit iets terug op 'ongelezen'.
    """
    account = _get_account(session, account_id)
    if account.provider != "mal":
        raise HTTPException(status_code=409, detail="alleen MyAnimeList gebruikt dit")

    tracker = MyAnimeListTracker(account.credentials)
    try:
        items = tracker.read_list()
    except TrackerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        tracker.close()

    gelezen = {item["mal_id"]: int(item["chapters_read"] or 0) for item in items}
    user = current_user(session)

    doelen = []
    for series in session.scalars(select(Series)):
        mal_id = series.tracker_ids.get("mal")
        if not mal_id or str(mal_id) not in gelezen:
            continue
        if payload.series_id is not None and series.id != payload.series_id:
            continue
        doelen.append((series, gelezen[str(mal_id)]))

    if not doelen:
        raise HTTPException(
            status_code=409,
            detail="geen gekoppelde series met leesvoortgang bij MyAnimeList",
        )

    totaal = 0
    namen: list[str] = []
    for series, chapters_read in doelen:
        gemarkeerd, _bekeken = tracker_service.import_progress(
            session, user, series, chapters_read
        )
        if gemarkeerd:
            totaal += gemarkeerd
            namen.append(f"{series.title} ({gemarkeerd})")

    return MalImportProgressOut(marked=totaal, series=namen)
