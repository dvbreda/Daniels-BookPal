"""Losse bestanden je bibliotheek in halen (downloads, Dropbox)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi import File as FastAPIFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from bookpal.config import settings
from bookpal.db import get_session
from bookpal.library import fetchjob, intake
from bookpal.models import LibraryRoot
from bookpal.schemas import (
    IntakeCandidateOut,
    IntakeFetchIn,
    IntakeFetchOut,
    IntakeImportIn,
    IntakeImportOut,
    IntakeScanOut,
    IntakeUploadOut,
)
from bookpal.sources.base import SourceError
from bookpal.sources.service import safe_name

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


def _first_intake_dir() -> Path:
    """Waar binnenkomend spul landt.

    Bewust de intake-map en niet meteen een bibliotheekmap: zo zie je eerst wat
    er binnenkwam en bepaal je daarna zelf waar het hoort. Dat is ook de enige
    map waar het importeren daarna uit mag lezen.
    """
    folders = intake.check_sources(settings.intake_dirs)
    if not folders:
        raise HTTPException(
            status_code=409,
            detail="er is geen intake-map ingesteld of bereikbaar (BOOKPAL_INTAKE)",
        )
    return Path(folders[0])


@router.post("/upload", response_model=IntakeUploadOut)
async def upload_file(file: UploadFile = FastAPIFile(...)) -> IntakeUploadOut:
    """Zet een bestand van je telefoon of laptop op de NAS.

    Het landt in je intake-map; daarna kies je met dezelfde knop als bij je
    downloads in welke bibliotheekmap het hoort.
    """
    folder = _first_intake_dir()
    if intake.unwritable([str(folder)]):
        raise HTTPException(
            status_code=409,
            detail=f"{folder} is niet beschrijfbaar; maak hem aan met je eigen gebruiker",
        )

    try:
        doel = await run_in_threadpool(
            intake.receive_upload, file.file, file.filename or "", folder
        )
    except SourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return IntakeUploadOut(path=str(doel), name=doel.name, size=doel.stat().st_size)


@router.post("/fetch", response_model=IntakeFetchOut)
def fetch_link(payload: IntakeFetchIn) -> IntakeFetchOut:
    """Haal een deellink op — een Dropbox-map, een los bestand.

    Begint meteen en geeft direct antwoord: een gedeelde map is zomaar een
    gigabyte, en daar minutenlang op wachten in het verzoek zelf is niet te
    onderscheiden van "er gebeurt niets". Kijk met ``GET /fetch`` hoe ver het is.

    Een gedeelde map komt binnen als zip; daar wordt uitgepakt wat BookPal kan
    lezen. De rest blijft waar het is.
    """
    folder = _first_intake_dir()
    if payload.folder:
        folder = folder / safe_name(payload.folder)
    if intake.unwritable([str(folder.parent if payload.folder else folder)]):
        raise HTTPException(status_code=409, detail=f"{folder} is niet beschrijfbaar")

    try:
        job = fetchjob.start(payload.url.strip(), folder)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _fetch_out(job)


@router.get("/fetch", response_model=IntakeFetchOut)
def fetch_status() -> IntakeFetchOut:
    """Hoe ver het ophalen is, of hoe het is afgelopen."""
    job = fetchjob.status()
    if job is None:
        return IntakeFetchOut(state="niets")
    return _fetch_out(job)


def _fetch_out(job: fetchjob.FetchJob) -> IntakeFetchOut:
    return IntakeFetchOut(
        state=job.state,
        url=job.url,
        folder=job.folder,
        bytes_done=job.bytes_done,
        bytes_total=job.bytes_total,
        saved=job.saved,
        skipped=job.skipped,
        errors=[job.error] if job.error else [],
    )
