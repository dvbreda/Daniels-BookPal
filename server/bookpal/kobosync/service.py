"""De Nickel-integratie als geheel (laag B uit ontwerp 3).

Drie onderdelen die los aan en uit kunnen, omdat ze los van elkaar nut hebben
en los van elkaar kunnen breken:

1. **Boeken wegzetten** — een venster van wat je binnenkort leest naar de Kobo.
2. **Tabs als planken** — jouw indeling terug in Nickel's eigen menu.
3. **Voortgang teruglezen** — wat je in Nickel las telt hier ook mee.

Alleen de laatste twee raken ``KoboReader.sqlite`` aan, en alleen die twee
kunnen dus stuklopen op een firmware-update. Het wegzetten van bestanden is
gewoon kopiëren en blijft altijd werken.

De volgorde is niet vrij, en dat is geen ongemak maar hoe Nickel werkt: nieuwe
bestanden bestaan pas voor hem nadat je het apparaat hebt losgekoppeld en hij ze
heeft ingelezen. Planken kunnen dus pas naar boeken wijzen ná die ronde. De
statusmelding zegt dat met zoveel woorden in plaats van het stil te laten
mislukken.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from bookpal.kobosync import device as device_module
from bookpal.kobosync import files, nickel
from bookpal.models import Setting, User

logger = logging.getLogger(__name__)

SETTING_KEY = "kobo"

# Bewust klein: een Kobo heeft een paar GB en je leest er niet twintig
# hoofdstukken per serie op vooruit.
DEFAULT_AHEAD = 3
DEFAULT_FOLDER = "BookPal"


@dataclass
class KoboSettings:
    """Wat je van de Nickel-integratie aan wilt hebben."""

    mount: str | None = None
    folder: str = DEFAULT_FOLDER
    ahead: int = DEFAULT_AHEAD
    series_ids: list[int] = field(default_factory=list)
    export_books: bool = True
    write_shelves: bool = True
    read_progress: bool = True
    # Standaard aan: dit schrijft in de database van je lezer, en dan hoor je
    # eerst te zien wat er zou gebeuren.
    dry_run: bool = True

    @classmethod
    def load(cls, session: Session) -> KoboSettings:
        row = session.get(Setting, SETTING_KEY)
        waarde = dict(row.value or {}) if row is not None else {}
        return cls(
            mount=waarde.get("mount"),
            folder=str(waarde.get("folder", DEFAULT_FOLDER)),
            ahead=int(waarde.get("ahead", DEFAULT_AHEAD)),
            series_ids=[int(item) for item in waarde.get("series_ids", [])],
            export_books=bool(waarde.get("export_books", True)),
            write_shelves=bool(waarde.get("write_shelves", True)),
            read_progress=bool(waarde.get("read_progress", True)),
            dry_run=bool(waarde.get("dry_run", True)),
        )

    def save(self, session: Session) -> None:
        row = session.get(Setting, SETTING_KEY)
        if row is None:
            row = Setting(key=SETTING_KEY, value={})
            session.add(row)
        row.value = {
            "mount": self.mount,
            "folder": self.folder,
            "ahead": self.ahead,
            "series_ids": self.series_ids,
            "export_books": self.export_books,
            "write_shelves": self.write_shelves,
            "read_progress": self.read_progress,
            "dry_run": self.dry_run,
        }
        session.commit()


@dataclass
class SyncReport:
    """Wat er is gebeurd, per onderdeel."""

    dry_run: bool = True
    planned: int = 0
    copied: int = 0
    skipped: int = 0
    removed: int = 0
    shelves_created: list[str] = field(default_factory=list)
    shelf_entries: int = 0
    not_imported: int = 0
    progress_updated: int = 0
    backup: str | None = None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def status(session: Session) -> dict[str, object]:
    """Staat er een Kobo klaar, en wat zou er gebeuren?"""
    instellingen = KoboSettings.load(session)
    gevonden: device_module.KoboDevice | None = None
    fout: str | None = None
    if instellingen.mount:
        try:
            gevonden = device_module.open_device(instellingen.mount)
        except device_module.DeviceError as exc:
            fout = str(exc)

    return {
        "mount": instellingen.mount,
        "connected": gevonden is not None,
        "writable": gevonden.writable if gevonden else False,
        "error": fout,
        "folder": instellingen.folder,
        "ahead": instellingen.ahead,
        "series_ids": instellingen.series_ids,
        "export_books": instellingen.export_books,
        "write_shelves": instellingen.write_shelves,
        "read_progress": instellingen.read_progress,
        "dry_run": instellingen.dry_run,
    }


def run(session: Session, user: User, *, shelf_names: dict[int, str] | None = None) -> SyncReport:
    """Voer de ingeschakelde onderdelen uit.

    ``shelf_names`` gaat van serie-id naar planknaam; wie dat bepaalt (een tab,
    een collectie, gewoon de serietitel) is niet aan deze laag.
    """
    instellingen = KoboSettings.load(session)
    report = SyncReport(dry_run=instellingen.dry_run)

    if not instellingen.mount:
        raise device_module.DeviceError("er is nog geen Kobo-map ingesteld")
    apparaat = device_module.open_device(instellingen.mount)

    gepland = files.plan(
        session,
        user,
        instellingen.series_ids,
        folder=instellingen.folder,
        ahead=instellingen.ahead,
    )
    report.planned = len(gepland)

    if instellingen.dry_run:
        report.notes.append(
            "Proefronde: er is niets gekopieerd of geschreven. "
            "Zet de proefstand uit om het echt te doen."
        )
        return report

    if not apparaat.writable:
        raise device_module.DeviceError(f"{apparaat.mount} is niet beschrijfbaar")

    if instellingen.export_books:
        resultaat = files.export(
            apparaat.mount, gepland, folder=instellingen.folder, prune=True
        )
        report.copied = resultaat.copied
        report.skipped = resultaat.skipped
        report.removed = resultaat.removed
        report.errors.extend(resultaat.errors)
        files.remember(session, gepland)

    if not (instellingen.write_shelves or instellingen.read_progress):
        return report

    # Vanaf hier raken we Nickel's eigen database aan.
    try:
        report.backup = str(nickel.backup(apparaat.database).name)
        connection = nickel.connect(apparaat.database)
    except (OSError, nickel.NickelError) as exc:
        report.errors.append(str(exc))
        return report

    try:
        bekend = {book.content_id: book for book in nickel.books(connection)}

        if instellingen.write_shelves:
            planken: dict[str, list[str]] = {}
            for item in gepland:
                naam = (shelf_names or {}).get(item.book_id) or item.series_title
                planken.setdefault(naam, []).append(nickel.content_id_for(item.relative))
            plank_resultaat = nickel.write_shelves(
                connection, planken, known=set(bekend)
            )
            report.shelves_created = plank_resultaat.created
            report.shelf_entries = plank_resultaat.added
            report.not_imported = len(plank_resultaat.not_imported)
            if plank_resultaat.not_imported:
                report.notes.append(
                    f"{report.not_imported} boeken kent de Kobo nog niet. Koppel hem los zodat hij "
                    "ze inleest, en draai dit daarna nog een keer."
                )

        if instellingen.read_progress:
            gelezen = {
                pad: (boek.percent, boek.status)
                for boek in bekend.values()
                if (pad := boek.path) is not None
            }
            report.progress_updated = files.progress_back(session, user, gelezen)
    finally:
        connection.close()

    return report


__all__ = ["DEFAULT_AHEAD", "DEFAULT_FOLDER", "KoboSettings", "SyncReport", "run", "status"]
