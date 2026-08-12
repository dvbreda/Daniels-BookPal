"""Losse bestanden je bibliotheek in halen (downloads, Dropbox)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.db import get_session
from bookpal.library import intake
from bookpal.models import LibraryRoot
from bookpal.schemas import (
    IntakeCandidateOut,
    IntakeImportIn,
    IntakeImportOut,
    IntakeScanOut,
)
from bookpal.sources.base import SourceError

router = APIRouter(prefix="/api/intake", tags=["intake"])


@router.get("", response_model=IntakeScanOut)
def scan_intake() -> IntakeScanOut:
    """Wat er klaarstaat om geïmporteerd te worden."""
    folders = intake.check_sources(settings.intake_dirs)
    return IntakeScanOut(
        folders=folders,
        unwritable=intake.unwritable(folders),
        files=[
            IntakeCandidateOut(
                path=item.path,
                name=item.name,
                size=item.size,
                series=item.series,
                number=item.number,
            )
            for item in intake.scan(folders)
        ],
    )


@router.post("/import", response_model=IntakeImportOut)
def import_intake(
    payload: IntakeImportIn, session: Session = Depends(get_session)
) -> IntakeImportOut:
    """Verplaats gekozen bestanden naar een van je mappen.

    Alleen bestanden uit de ingestelde intake-mappen: zonder die grens zou dit
    een endpoint zijn waarmee elk bestand op de NAS te verplaatsen is.
    """
    root = session.get(LibraryRoot, payload.root_id)
    if root is None:
        raise HTTPException(status_code=404, detail="die map bestaat niet")

    try:
        report = intake.import_files(
            session,
            payload.paths,
            root,
            folder=payload.folder,
            allowed=settings.intake_dirs,
        )
    except SourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return IntakeImportOut(moved=report.moved, skipped=report.skipped, errors=report.errors)
