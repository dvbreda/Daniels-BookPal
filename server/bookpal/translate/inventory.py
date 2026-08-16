"""Wat er aan betaald werk op schijf ligt, als lijst.

De sidecars zijn de waarheid en de database is de index — dat werkt zolang er
één machine is. Zodra de telefoon zelf ook vertalingen kan maken zijn er twee
plekken waar werk ontstaat, en dan heb je een lijst nodig waarin allebei kunnen
kijken wat de ander heeft.

Vandaar dit: geen nieuwe opslag, alleen een inventaris van de map. Hij leest wat
er staat en zegt per bestand hoe groot het is en wanneer het gemaakt is. Wie hem
opvraagt kan zelf bepalen wat hij mist.

Waarom geen hash: die zou over honderden bestanden van een paar honderd kilobyte
elke keer opnieuw uitgerekend moeten worden, en het levert niets op wat maat en
tijdstip niet ook zeggen. Een sidecar wordt geschreven en daarna nooit meer
aangeraakt; verandert hij toch, dan verandert de maat vrijwel zeker mee.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.models import Book, Series
from bookpal.translate import sidecar

#: Wat een sidecarnaam mag zijn. Streng, want deze naam wordt straks door een
#: client aangeleverd en wij maken er een pad van: alles wat hier niet
#: doorheen komt, komt de schijf niet op.
#:
#: * ``p0007-nl.json``               de tekstvlakken
#: * ``p0007-nl-image_fast.webp``    hele pagina, hertekend
#: * ``p0007-kleur.webp``            ingekleurd
#: * ``p0007-kleur-ruw.webp``        de ruwe plaat van het model
#: * ``p0007-kleur-nl.webp``         ingekleurd én vertaald
_NAAM = re.compile(
    r"^p(?P<pagina>\d{4})-"
    r"(?P<rest>[a-z]{2}|[a-z]{2}-image_(?:fast|pro)|kleur|kleur-ruw|kleur-[a-z]{2})"
    r"\.(?P<ext>json|webp)$"
)


@dataclass(frozen=True, slots=True)
class Regel:
    """Eén sidecar, zoals hij op schijf staat."""

    book_id: int
    page_index: int
    name: str
    soort: str
    bytes: int
    changed_at: datetime

    @property
    def key(self) -> str:
        """Waar client en server elkaar op vinden."""
        return f"{self.book_id}/{self.name}"


def soort_van(naam: str) -> str | None:
    """Welke soort werk dit bestand is, of niets als de naam niet klopt.

    De soorten heten hetzelfde als bij de batches (tekst, hertekend, kleuren),
    zodat er niet halverwege een tweede woordenlijst ontstaat. ``kleur-ruw``
    valt er apart uit: dat is de onbewerkte plaat van het model en geen versie
    die je zou willen lezen.
    """
    treffer = _NAAM.match(naam)
    if treffer is None:
        return None
    rest = treffer.group("rest")
    if rest == "kleur-ruw":
        return "kleur-ruw"
    if rest.startswith("kleur"):
        return "kleuren"
    if "image_" in rest:
        return "hertekend"
    return "tekst"


def pagina_van(naam: str) -> int | None:
    treffer = _NAAM.match(naam)
    return int(treffer.group("pagina")) if treffer else None


def pad_voor(session: Session, book: Book, naam: str) -> Path | None:
    """Het volledige pad van deze sidecar, of niets als de naam niet deugt.

    Alleen via ``sidecar.chapter_dir``, en de naam is al door ``_NAAM``
    gekomen: zo kan een client geen pad naar buiten de hoofdstukmap opgeven.
    """
    if soort_van(naam) is None:
        return None
    series = session.get(Series, book.series_id) if book.series_id else None
    return sidecar.chapter_dir(series, book) / naam


def inventaris(session: Session, *, book_id: int | None = None) -> list[Regel]:
    """Alles wat er ligt, eventueel voor één boek.

    Loopt over de boeken en niet over de schijf: zo staat er nooit een regel in
    die naar een boek verwijst dat niet meer bestaat, en blijft de uitkomst
    hetzelfde als de mappen verhuizen.
    """
    statement = select(Book)
    if book_id is not None:
        statement = statement.where(Book.id == book_id)
    regels: list[Regel] = []
    for book in session.scalars(statement):
        series = session.get(Series, book.series_id) if book.series_id else None
        map_ = sidecar.chapter_dir(series, book)
        if not map_.is_dir():
            continue
        for pad in sorted(map_.iterdir()):
            if not pad.is_file():
                continue
            soort = soort_van(pad.name)
            if soort is None:
                continue
            info = pad.stat()
            regels.append(
                Regel(
                    book_id=book.id,
                    page_index=pagina_van(pad.name) or 0,
                    name=pad.name,
                    soort=soort,
                    bytes=info.st_size,
                    changed_at=datetime.fromtimestamp(info.st_mtime, tz=UTC),
                )
            )
    return regels


__all__ = ["Regel", "inventaris", "pad_voor", "pagina_van", "soort_van"]
