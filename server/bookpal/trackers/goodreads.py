"""Goodreads (M7).

De publieke API is dood — sinds eind 2020 geen nieuwe keys, geen
ondersteuning. Wat hier staat is het vangnet dat de architectuur ervoor in de
plaats zet: een CSV in het formaat dat Goodreads zelf importeert
(My Books → Import and Export → Import books).

De cookie-gebaseerde automatisering (eenmalig inloggen met een headless
browser, daarna form-posts) staat nog niet in deze build. Reden: dat pad leunt
op de huidige HTML van Goodreads' eigen site, en code die daartegen post kan
ik hier niet verantwoord schrijven zonder een echt account om tegen te
verifiëren — geraden veldnamen die "waarschijnlijk werken" zijn erger dan geen
automatisering, want ze falen onopgemerkt. De CSV-export hieronder heeft dat
probleem niet: het is een gedocumenteerd, stabiel formaat, en werkt vandaag al
zonder dat er ooit iets misgaat op Goodreads' eigen pagina's.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass

from bookpal.trackers.base import ReadingStatus

#: Onze statussen naar Goodreads' vaste shelves.
_SHELF = {
    ReadingStatus.READING: "currently-reading",
    ReadingStatus.COMPLETED: "read",
    ReadingStatus.ON_HOLD: "on-hold",
    ReadingStatus.DROPPED: "abandoned",
    ReadingStatus.PLAN_TO_READ: "to-read",
}

# De kolommen die Goodreads' import daadwerkelijk leest; alles wat je erbij
# zet negeert het, maar deze moeten kloppen qua naam en volgorde is vrij.
_FIELDNAMES = [
    "Title",
    "Author",
    "ISBN",
    "My Rating",
    "Exclusive Shelf",
    "Bookshelves",
    "Date Read",
    "Date Added",
]


@dataclass(frozen=True, slots=True)
class GoodreadsRow:
    """Eén serie, klaar voor de CSV. ``date_read`` alleen bij ``COMPLETED``."""

    title: str
    author: str | None
    status: ReadingStatus
    rating: int | None = None
    isbn: str | None = None
    date_read: str | None = None  # YYYY/MM/DD, zoals Goodreads het wil
    date_added: str | None = None


def export_csv(rows: Iterable[GoodreadsRow]) -> str:
    """Bouwt de CSV-tekst voor Goodreads' "Import books".

    Geen bestand, geen streaming — dit is een persoonlijke bibliotheek, geen
    duizenden titels, dus is er niets te winnen met complexiteit hier.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "Title": row.title,
                "Author": row.author or "",
                "ISBN": f'="{row.isbn}"' if row.isbn else "",
                "My Rating": row.rating or "",
                "Exclusive Shelf": _SHELF[row.status],
                "Bookshelves": _SHELF[row.status],
                "Date Read": row.date_read or "" if row.status is ReadingStatus.COMPLETED else "",
                "Date Added": row.date_added or "",
            }
        )
    return buffer.getvalue()
