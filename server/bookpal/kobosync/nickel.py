"""Praten met ``KoboReader.sqlite`` — de database van Kobo's eigen lezer.

Dit is de enige plek in BookPal die op reverse-engineering leunt. Nickel is
gesloten software en de vorm van deze tabellen is nergens toegezegd; een
firmware-update kan hem veranderen. Daarom staat het apart, is het uit te
zetten, en gaat het uitermate voorzichtig te werk:

* **Nooit zonder kopie.** Voor elke schrijfronde gaat er een backup naast, met
  tijdstempel. Deze database bevat je hele bibliotheek, je aantekeningen en je
  leesvoortgang; die verliezen omdat wij een plank wilden aanmaken is geen
  aanvaardbare uitkomst.
* **Alleen wat we zelf gemaakt hebben.** We voegen planken toe en hangen er
  boeken in. Wat jij zelf hebt aangemaakt blijft ongemoeid, en er wordt nooit
  iets uit ``content`` verwijderd of aangepast.
* **Nooit tijdens het lezen.** Alleen schrijven als het apparaat via USB is
  aangesloten en Nickel dus niet zelf in de database zit.

Over de vorm zelf: ``content`` is Nickel's boekenlijst, met per sideloaded boek
een ``ContentID`` van de vorm ``file:///mnt/onboard/<pad>``. ``Shelf`` is een
plank en ``ShelfContent`` de koppeling. Dezelfde tabellen die Calibre's
KoboTouch-driver al jaren beschrijft.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class NickelError(RuntimeError):
    """De database was er niet, of zag er niet uit zoals we verwachtten."""


# Waar de Kobo zijn eigen opslag ziet. Sideloaded boeken krijgen een ContentID
# met dit voorvoegsel, ongeacht waar de map op jouw computer gekoppeld staat.
ONBOARD = "file:///mnt/onboard/"

# ReadStatus zoals Nickel hem gebruikt.
UNREAD = 0
READING = 1
FINISHED = 2

# De tabellen die we nodig hebben. Ontbreekt er één, dan is dit geen
# KoboReader.sqlite of een versie die we niet kennen — en dan raken we hem niet
# aan.
_REQUIRED_TABLES = ("content", "Shelf", "ShelfContent")


@dataclass(frozen=True, slots=True)
class NickelBook:
    """Eén boek zoals Nickel het kent."""

    content_id: str
    title: str | None
    percent: int
    status: int
    last_read: str | None

    @property
    def path(self) -> str | None:
        """Het pad binnen het apparaat, zonder het ``file://``-voorvoegsel."""
        if self.content_id.startswith(ONBOARD):
            return self.content_id[len(ONBOARD) :]
        return None


@dataclass
class ShelfReport:
    created: list[str] = field(default_factory=list)
    added: int = 0
    # Boeken die je wel hebt weggezet maar die Nickel nog niet kent. Dat is
    # geen fout: Nickel bouwt zijn lijst pas op ná het loskoppelen.
    not_imported: list[str] = field(default_factory=list)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open de database, met een controle dat het er ook één is."""
    if not db_path.is_file():
        raise NickelError(f"{db_path} bestaat niet")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    aanwezig = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    ontbreekt = [naam for naam in _REQUIRED_TABLES if naam not in aanwezig]
    if ontbreekt:
        connection.close()
        raise NickelError(
            "dit lijkt geen KoboReader.sqlite: " + ", ".join(ontbreekt) + " ontbreekt"
        )
    return connection


def backup(db_path: Path) -> Path:
    """Leg een kopie naast het origineel en geef het pad terug.

    Met tijdstempel, zodat een tweede ronde de vorige kopie niet overschrijft —
    juist als er iets misgaat wil je de oudste nog hebben.
    """
    stempel = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    doel = db_path.with_name(f"{db_path.name}.bookpal-{stempel}.bak")
    shutil.copy2(db_path, doel)
    logger.info("KoboReader.sqlite gekopieerd naar %s", doel.name)
    return doel


def books(connection: sqlite3.Connection) -> list[NickelBook]:
    """Wat Nickel aan sideloaded boeken kent, met je stand erbij.

    ``ContentType = 6`` is een boek; de andere types zijn hoofdstukken en
    interne rommel. Alleen wat op het apparaat zelf staat: de rest komt uit de
    Kobo-winkel en heeft met ons niets te maken.
    """
    rows = connection.execute(
        """
        SELECT ContentID, Title, ___PercentRead, ReadStatus, DateLastRead
        FROM content
        WHERE ContentType = 6 AND ContentID LIKE 'file:///mnt/onboard/%'
        """
    )
    gevonden: list[NickelBook] = []
    for row in rows:
        gevonden.append(
            NickelBook(
                content_id=row["ContentID"],
                title=row["Title"],
                percent=int(row["___PercentRead"] or 0),
                status=int(row["ReadStatus"] or 0),
                last_read=row["DateLastRead"],
            )
        )
    return gevonden


def content_id_for(relative_path: str) -> str:
    """Het ContentID dat Nickel aan een bestand op deze plek geeft."""
    return ONBOARD + relative_path.lstrip("/")


def write_shelves(
    connection: sqlite3.Connection,
    shelves: Mapping[str, Iterable[str]],
    *,
    known: set[str] | None = None,
) -> ShelfReport:
    """Zet je tabs als planken in Nickel.

    ``shelves`` gaat van planknaam naar ContentID's. Een boek dat Nickel nog
    niet kent slaan we over en melden we: Nickel bouwt zijn lijst pas op ná het
    loskoppelen, dus de eerste ronde na het wegzetten van nieuwe bestanden is
    het normaal dat er iets tussen zit.

    Bestaande planken blijven bestaan en worden alleen aangevuld — jouw eigen
    indeling verdwijnt niet omdat wij dezelfde naam gebruiken.
    """
    report = ShelfReport()
    nu = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if known is None:
        known = {book.content_id for book in books(connection)}

    for naam, content_ids in shelves.items():
        bestaat = connection.execute(
            "SELECT 1 FROM Shelf WHERE Name = ? AND (_IsDeleted IS NULL OR _IsDeleted = 'false')",
            (naam,),
        ).fetchone()
        if bestaat is None:
            connection.execute(
                """
                INSERT INTO Shelf
                    (CreationDate, Id, InternalName, LastModified, Name, Type,
                     _IsDeleted, _IsVisible, _IsSynced)
                VALUES (?, ?, ?, ?, ?, 'UserTag', 'false', 'true', 'false')
                """,
                (nu, naam, naam, nu, naam),
            )
            report.created.append(naam)

        for content_id in content_ids:
            if content_id not in known:
                report.not_imported.append(content_id)
                continue
            al_erin = connection.execute(
                """
                SELECT 1 FROM ShelfContent
                WHERE ShelfName = ? AND ContentId = ?
                  AND (_IsDeleted IS NULL OR _IsDeleted = 'false')
                """,
                (naam, content_id),
            ).fetchone()
            if al_erin is not None:
                continue
            connection.execute(
                """
                INSERT INTO ShelfContent
                    (ShelfName, ContentId, DateModified, _IsDeleted, _IsSynced)
                VALUES (?, ?, ?, 'false', 'false')
                """,
                (naam, content_id, nu),
            )
            report.added += 1

    connection.commit()
    return report


__all__ = [
    "FINISHED",
    "ONBOARD",
    "READING",
    "UNREAD",
    "NickelBook",
    "NickelError",
    "ShelfReport",
    "backup",
    "books",
    "connect",
    "content_id_for",
    "write_shelves",
]
