"""De Nickel-integratie bedienen (laag B uit ontwerp 3).

Bewust met een proefstand als standaard: dit schrijft bestanden naar je lezer en
regels in zijn database, en dan hoor je eerst te kunnen zien wat er zou gebeuren.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.kobosync import device as device_module
from bookpal.kobosync import files
from bookpal.kobosync import service as kobo_service
from bookpal.schemas import KoboPlanOut, KoboSettingsIn, KoboStatusOut, KoboSyncOut

router = APIRouter(prefix="/api/kobo", tags=["kobo"])


@router.get("/status", response_model=KoboStatusOut)
def status(session: Session = Depends(get_session)) -> KoboStatusOut:
    """Staat er een Kobo klaar, en wat staat er ingesteld?"""
    return KoboStatusOut(**kobo_service.status(session))  # type: ignore[arg-type]


@router.put("/settings", response_model=KoboStatusOut)
def save_settings(
    payload: KoboSettingsIn, session: Session = Depends(get_session)
) -> KoboStatusOut:
    instellingen = kobo_service.KoboSettings.load(session)
    for veld, waarde in payload.model_dump(exclude_unset=True).items():
        setattr(instellingen, veld, waarde)
    instellingen.save(session)
    return KoboStatusOut(**kobo_service.status(session))  # type: ignore[arg-type]


@router.get("/plan", response_model=list[KoboPlanOut])
def plan(session: Session = Depends(get_session)) -> list[KoboPlanOut]:
    """Wat er mee zou gaan, zonder iets aan te raken."""
    instellingen = kobo_service.KoboSettings.load(session)
    gepland = files.plan(
        session,
        current_user(session),
        instellingen.series_ids,
        folder=instellingen.folder,
        ahead=instellingen.ahead,
    )
    return [
        KoboPlanOut(
            book_id=item.book_id,
            series_title=item.series_title,
            title=item.title,
            path=item.relative,
        )
        for item in gepland
    ]


@router.post("/sync", response_model=KoboSyncOut)
def sync(session: Session = Depends(get_session)) -> KoboSyncOut:
    """Voer de ingeschakelde onderdelen uit."""
    try:
        report = kobo_service.run(session, current_user(session))
    except device_module.DeviceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return KoboSyncOut(
        dry_run=report.dry_run,
        planned=report.planned,
        copied=report.copied,
        skipped=report.skipped,
        removed=report.removed,
        shelves_created=report.shelves_created,
        shelf_entries=report.shelf_entries,
        not_imported=report.not_imported,
        progress_updated=report.progress_updated,
        backup=report.backup,
        errors=report.errors,
        notes=report.notes,
    )
