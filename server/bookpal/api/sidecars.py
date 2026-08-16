"""Betaald werk uitwisselen met een client die zelf ook mag vertalen.

Tot nu toe was de NAS de enige plek waar een vertaling ontstond, en dan volstaat
"de sidecar is de waarheid". Zodra de telefoon onderweg zelf een pagina laat
hertekenen — wél internet, geen NAS — zijn er twee plekken waar werk ontstaat en
moeten ze elkaar kunnen inhalen.

Drie routes, meer is er niet nodig:

* de inventaris: wat ligt hier, hoe groot, van wanneer
* ophalen: geef me dit ene bestand
* terugzetten: hier heb je er een die je nog niet had

Er zit bewust geen slimmigheid in over wie wint bij een botsing. Een sidecar
wordt één keer geschreven en daarna niet meer aangeraakt, dus twee kanten die
dezelfde pagina hebben, hebben allebei iets bruikbaars — en dan is wat er al
staat laten staan het goedkoopste antwoord. Alleen met ``force`` overschrijf je,
en dat is een bewuste handeling.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from bookpal.db import get_session
from bookpal.library import export
from bookpal.models import Book
from bookpal.schemas import SidecarManifestOut, SidecarOut
from bookpal.translate import inventory, sidecar
from bookpal.translate import service as translation_service
from bookpal.translate.modes import TranslateMode

from . import deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sidecars", tags=["sidecars"])

#: Ruim boven een hertekende pagina (die weegt 200-300 kB), en ruim onder wat
#: een verzoek is dat je per ongeluk stuurt.
MAX_BYTES = 12 * 1024 * 1024


def _out(regel: inventory.Regel) -> SidecarOut:
    return SidecarOut(
        book_id=regel.book_id,
        page_index=regel.page_index,
        name=regel.name,
        kind=regel.soort,
        bytes=regel.bytes,
        changed_at=regel.changed_at,
    )


@router.get("", response_model=SidecarManifestOut)
def manifest(
    book_id: int | None = Query(default=None, description="Alleen dit boek."),
    session: Session = Depends(get_session),
) -> SidecarManifestOut:
    """Alles wat er aan betaald werk ligt.

    De client vergelijkt deze lijst met wat hij zelf heeft; wat hij mist haalt
    hij op, wat hij extra heeft duwt hij terug.
    """
    regels = inventory.inventaris(session, book_id=book_id)
    return SidecarManifestOut(
        items=[_out(regel) for regel in regels],
        total=len(regels),
        total_bytes=sum(regel.bytes for regel in regels),
    )


@router.get("/{book_id}/{name}")
def download(book_id: int, name: str, session: Session = Depends(get_session)) -> Response:
    book = deps.get_book(session, book_id)
    pad = inventory.pad_voor(session, book, name)
    if pad is None:
        raise HTTPException(status_code=400, detail=f"geen geldige sidecarnaam: {name!r}")
    data = sidecar.read_bytes(pad)
    if data is None:
        raise HTTPException(status_code=404, detail="die sidecar ligt hier niet")
    media = "application/json" if name.endswith(".json") else "image/webp"
    return Response(content=data, media_type=media)


@router.put("/{book_id}/{name}", response_model=SidecarOut, status_code=201)
async def upload(
    book_id: int,
    name: str,
    request: Request,
    force: bool = Query(default=False, description="Overschrijf wat er al ligt."),
    session: Session = Depends(get_session),
) -> SidecarOut:
    """Een sidecar aannemen die elders gemaakt is.

    Dit is de kant waar het misgaat als je niet oplet, want de naam komt van
    buiten en wordt een pad. Daarom loopt hij eerst langs ``inventory.pad_voor``,
    die alleen namen doorlaat die aan het vaste patroon voldoen en het pad zelf
    onder de hoofdstukmap opbouwt.
    """
    book = deps.get_book(session, book_id)
    pad = inventory.pad_voor(session, book, name)
    if pad is None:
        raise HTTPException(status_code=400, detail=f"geen geldige sidecarnaam: {name!r}")

    if pad.exists() and not force:
        # Niet als fout: de client die dit stuurt heeft gelijk gedaan wat hij
        # moest doen, en overslaan is precies de bedoeling.
        info = pad.stat()
        return SidecarOut(
            book_id=book.id,
            page_index=inventory.pagina_van(name) or 0,
            name=name,
            kind=inventory.soort_van(name) or "",
            bytes=info.st_size,
            changed_at=_tijd(pad),
        )

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="lege sidecar")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"groter dan {MAX_BYTES // 1024 // 1024} MB")

    sidecar.write_bytes(pad, data)
    _index(session, book, name)
    # Dit is precies het geval waar M9 voor bedoeld is: de telefoon vult
    # onderweg de laatste ontbrekende pagina aan, en dan mag het hoofdstuk
    # hier — zonder dat iemand erom vraagt — een leesbare editie worden.
    export.probeer_alle(session, book)
    logger.info("sidecar aangenomen: boek %s, %s (%s bytes)", book.id, name, len(data))
    return SidecarOut(
        book_id=book.id,
        page_index=inventory.pagina_van(name) or 0,
        name=name,
        kind=inventory.soort_van(name) or "",
        bytes=len(data),
        changed_at=_tijd(pad),
    )


def _tijd(pad: Path) -> datetime:
    return datetime.fromtimestamp(pad.stat().st_mtime, tz=UTC)


def _index(session: Session, book: Book, name: str) -> None:
    """De database bijwerken zodat de server weet dat deze pagina klaar is.

    Zonder dit ligt het bestand er wel maar telt de planner de pagina nog als
    werk — en dan betaal je er een tweede keer voor. De schijf is de waarheid,
    maar de index moet die waarheid wel kennen.
    """
    pagina = inventory.pagina_van(name)
    soort = inventory.soort_van(name)
    if pagina is None or soort is None:
        return
    if soort == "hertekend":
        stand = TranslateMode.IMAGE_PRO if "image_pro" in name else TranslateMode.IMAGE_FAST
        translation_service.record_external(
            session, book, pagina, target_lang=_taal(name), provider=stand.provider
        )
    elif soort == "tekst":
        translation_service.record_external(
            session, book, pagina, target_lang=_taal(name), provider=TranslateMode.TEXT.provider
        )
    # kleuren en kleur-ruw hebben geen rij in `translation`: die worden op
    # schijf geteld (zie `_colour_todo`), en daar staat het bestand nu.


def _taal(name: str) -> str:
    """De taalcode uit `p0007-nl-image_fast.webp` of `p0007-nl.json`."""
    deel = name.split("-")
    return deel[1] if len(deel) > 1 and len(deel[1]) == 2 else "nl"
