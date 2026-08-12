"""Library-roots beheren en scannen."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.db import get_session
from bookpal.library import ScanAborted, scan_all, scan_root, sidecars
from bookpal.models import Book, File, LibraryRoot, Series
from bookpal.schemas import (
    LibraryRootIn,
    LibraryRootOut,
    ScanResultOut,
    SidecarSyncOut,
)

router = APIRouter(prefix="/api/libraries", tags=["libraries"])


def _counts(session: Session, root: LibraryRoot) -> tuple[int, int]:
    series_count = session.scalar(
        select(func.count(Series.id)).where(Series.library_root_id == root.id)
    )
    book_count = session.scalar(
        select(func.count(Book.id))
        .join(Series, Book.series_id == Series.id)
        .where(Series.library_root_id == root.id)
    )
    return int(series_count or 0), int(book_count or 0)


def _to_out(session: Session, root: LibraryRoot) -> LibraryRootOut:
    series_count, book_count = _counts(session, root)
    out = LibraryRootOut.model_validate(root)
    out.series_count = series_count
    out.book_count = book_count
    return out


@router.get("", response_model=list[LibraryRootOut])
def list_roots(session: Session = Depends(get_session)) -> list[LibraryRootOut]:
    roots = session.scalars(select(LibraryRoot).order_by(LibraryRoot.name)).all()
    return [_to_out(session, root) for root in roots]


@router.post("", response_model=LibraryRootOut, status_code=201)
def create_root(payload: LibraryRootIn, session: Session = Depends(get_session)) -> LibraryRootOut:
    path = Path(payload.path).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"map bestaat niet: {payload.path}")
    resolved = str(path.resolve())
    if session.scalar(select(LibraryRoot).where(LibraryRoot.path == resolved)):
        raise HTTPException(status_code=409, detail="deze map is al toegevoegd")

    root = LibraryRoot(
        name=payload.name,
        path=resolved,
        default_origin_language=payload.default_origin_language,
        default_origin_region=payload.default_origin_region,
        folder_as_collection=payload.folder_as_collection,
        enabled=payload.enabled,
    )
    session.add(root)
    session.commit()
    return _to_out(session, root)


@router.get("/{root_id}", response_model=LibraryRootOut)
def get_root(root_id: int, session: Session = Depends(get_session)) -> LibraryRootOut:
    root = session.get(LibraryRoot, root_id)
    if root is None:
        raise HTTPException(status_code=404, detail="library-root niet gevonden")
    return _to_out(session, root)


@router.delete("/{root_id}", status_code=204)
def delete_root(root_id: int, session: Session = Depends(get_session)) -> None:
    root = session.get(LibraryRoot, root_id)
    if root is None:
        raise HTTPException(status_code=404, detail="library-root niet gevonden")
    session.delete(root)
    session.commit()


@router.post("/{root_id}/scan", response_model=ScanResultOut)
def scan_one(
    root_id: int, force: bool = False, session: Session = Depends(get_session)
) -> ScanResultOut:
    root = session.get(LibraryRoot, root_id)
    if root is None:
        raise HTTPException(status_code=404, detail="library-root niet gevonden")
    try:
        result = scan_root(session, root, force=force)
    except ScanAborted as exc:
        # 409: er is niets mis met het verzoek, de opslag is even niet in orde.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return ScanResultOut(
        root=root.name,
        added=result.added,
        updated=result.updated,
        unchanged=result.unchanged,
        removed=result.removed,
        errors=result.errors,
    )


@router.post("/scan", response_model=list[ScanResultOut])
def scan_everything(
    force: bool = False, session: Session = Depends(get_session)
) -> list[ScanResultOut]:
    results = scan_all(session, force=force)
    session.commit()
    return [
        ScanResultOut(
            root=name,
            added=result.added,
            updated=result.updated,
            unchanged=result.unchanged,
            removed=result.removed,
            errors=result.errors,
        )
        for name, result in results.items()
    ]


@router.post("/sidecars", response_model=SidecarSyncOut)
def write_sidecars(session: Session = Depends(get_session)) -> SidecarSyncOut:
    """Schrijf naast elk boek vast wat we ervan weten.

    Voor een bibliotheek die er al stond voordat dit bestond. Daarna houdt de
    scanner ze vanzelf bij: hij leest ze bij elke ronde en vult aan wat er nog
    niet in staat.

    Alleen aanvullen, nooit weggooien: een sidecar die jij hebt aangepast blijft
    zoals hij is.
    """
    resultaat = SidecarSyncOut()
    boeken = session.scalars(select(Book).where(Book.file_id.isnot(None)))
    for book in boeken:
        bestand = session.get(File, book.file_id) if book.file_id else None
        if bestand is None:
            continue
        pad = Path(bestand.path)
        if not pad.is_file():
            resultaat.skipped += 1
            continue

        series = session.get(Series, book.series_id)
        zijkant = sidecars.read(pad) or sidecars.Sidecar()
        herkomst = "source" if book.title_locked else "filename"
        veranderd = zijkant.set_title(book.title, herkomst=herkomst)
        if series is not None and zijkant.series != series.title:
            zijkant.series = series.title
            veranderd = True
        if zijkant.number != book.number or zijkant.volume != book.volume:
            zijkant.number, zijkant.volume = book.number, book.volume
            veranderd = True
        if series is not None and series.authors and not zijkant.authors:
            zijkant.authors = list(series.authors)
            veranderd = True

        if not veranderd and sidecars.path_for(pad).is_file():
            resultaat.skipped += 1
            continue
        if sidecars.write(pad, zijkant) is None:
            resultaat.errors.append(f"{pad.name}: niet te schrijven")
        else:
            resultaat.written += 1

    return resultaat
