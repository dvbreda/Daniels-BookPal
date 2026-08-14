"""Boeken naar de Kobo wegzetten.

Kopiëren en niet verplaatsen: wat op de NAS staat blijft daar. De Kobo krijgt
een werkkopie van wat je binnenkort gaat lezen, en die mag zonder gevolgen weg.

Hoeveel er meegaat is de kern van het ontwerp. Een Kobo heeft een paar GB, een
serie van 700 hoofdstukken past daar niet op en je leest ze ook niet vandaag.
Dus per serie een klein venster: waar je gebleven bent plus een handvol
vooruit. Wat je uit hebt en wat ver voor je ligt hoeft er niet te staan.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.api import deps
from bookpal.library import editions
from bookpal.models import Book, Edition, File, Progress, Series, Setting, User
from bookpal.sources.service import safe_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Planned:
    """Eén boek dat naar het apparaat zou gaan."""

    book_id: int
    series_title: str
    title: str
    source: Path
    # Waar het op het apparaat komt, gerekend vanaf de wortel ervan.
    relative: str


@dataclass
class ExportReport:
    copied: int = 0
    skipped: int = 0
    removed: int = 0
    bytes_copied: int = 0
    errors: list[str] = field(default_factory=list)
    # Wat er nu op het apparaat hoort te staan; de plankensync heeft dit nodig.
    present: list[str] = field(default_factory=list)


def plan(
    session: Session,
    user: User,
    series_ids: list[int],
    *,
    folder: str = "BookPal",
    ahead: int = 3,
) -> list[Planned]:
    """Wat er mee zou gaan: je huidige plek plus ``ahead`` vooruit, per serie.

    Uitgelezen delen vallen af — die heb je gehad. Ben je nog nergens begonnen,
    dan is het begin van de reeks het venster.
    """
    gepland: list[Planned] = []
    for series_id in series_ids:
        series = session.get(Series, series_id)
        if series is None:
            continue

        boeken = list(
            session.scalars(
                select(Book)
                .where(Book.series_id == series_id)
                .order_by(Book.sort_volume, Book.sort_number)
            )
        )
        uitgaven = list(session.scalars(select(Edition).where(Edition.series_id == series_id)))
        leesbaar = editions.readable(editions.slots(boeken, uitgaven))
        if not leesbaar:
            continue

        voortgang = deps.progress_for(
            session, user, [book.id for slot in leesbaar for book in slot.books]
        )
        openstaand = [
            slot
            for slot in leesbaar
            if not ((row := editions.best_progress(slot, voortgang)) and row.finished)
        ]

        for slot in openstaand[: max(1, ahead)]:
            book = slot.chosen
            bestand = session.get(File, book.file_id) if book.file_id else None
            if bestand is None:
                continue
            bron = Path(bestand.path)
            naam = f"{_prefix(book)}{safe_name(book.title)}{bron.suffix}"
            gepland.append(
                Planned(
                    book_id=book.id,
                    series_title=series.title,
                    title=book.title,
                    source=bron,
                    relative=f"{folder}/{safe_name(series.title)}/{naam}",
                )
            )
    return gepland


def _prefix(book: Book) -> str:
    """Deel en nummer vooraan, zodat Nickel op leesvolgorde sorteert.

    Nickel sorteert sideloaded boeken op titel en kent onze volgorde niet. Zonder
    dit staat hoofdstuk 10 tussen 1 en 2.
    """
    delen = []
    if book.volume:
        delen.append(f"v{book.sort_volume:03.0f}")
    if book.number:
        delen.append(f"{book.sort_number:07.2f}".replace(".", "_"))
    return f"{'-'.join(delen)} " if delen else ""


def export(
    device_root: Path,
    gepland: list[Planned],
    *,
    folder: str = "BookPal",
    prune: bool = True,
) -> ExportReport:
    """Zet dit op het apparaat en ruim op wat er niet meer bij hoort.

    Opruimen blijft binnen onze eigen map: alles wat je zelf op de Kobo hebt
    gezet staat daarbuiten en wordt nooit aangeraakt. Een bestand dat er al
    identiek staat wordt overgeslagen — over usb kopiëren is traag genoeg om
    dat te laten meetellen.
    """
    report = ExportReport()
    basis = device_root / folder
    verwacht = {item.relative for item in gepland}
    report.present = sorted(verwacht)

    for item in gepland:
        doel = device_root / item.relative
        try:
            if not item.source.is_file():
                report.errors.append(f"{item.title}: bestand staat er niet meer")
                continue
            if doel.is_file() and doel.stat().st_size == item.source.stat().st_size:
                report.skipped += 1
                continue
            doel.parent.mkdir(parents=True, exist_ok=True)
            # Eerst ernaast, dan omzetten: een afgebroken usb-kopie mag Nickel
            # nooit als geldig boek tegenkomen.
            tijdelijk = doel.with_name(f".{doel.name}.deel")
            shutil.copy2(item.source, tijdelijk)
            tijdelijk.replace(doel)
            report.copied += 1
            report.bytes_copied += doel.stat().st_size
        except OSError as exc:
            logger.warning("wegzetten van %s: %s", item.title, exc)
            report.errors.append(f"{item.title}: {exc}")

    if prune and basis.is_dir():
        for pad in sorted(basis.rglob("*"), reverse=True):
            try:
                if pad.is_file():
                    if str(pad.relative_to(device_root)).replace("\\", "/") not in verwacht:
                        pad.unlink()
                        report.removed += 1
                elif pad.is_dir() and not any(pad.iterdir()):
                    pad.rmdir()
            except OSError as exc:
                report.errors.append(f"{pad.name}: {exc}")

    return report


def progress_back(session: Session, user: User, gelezen: dict[str, tuple[int, int]]) -> int:
    """Neem over wat je in Nickel gelezen hebt.

    ``gelezen`` gaat van pad-op-het-apparaat naar (percentage, status). Alleen
    vooruit: heb je hier al verder gelezen, dan blijft dat staan. Anders zou een
    Kobo die een week in de la lag je stand terugzetten.
    """
    bijgewerkt = 0
    for relative, (percent, status) in gelezen.items():
        book_id = _book_from_path(session, relative)
        if book_id is None:
            continue
        book = session.get(Book, book_id)
        if book is None:
            continue
        row = session.scalar(
            select(Progress).where(Progress.user_id == user.id, Progress.book_id == book.id)
        )
        klaar = status == 2 or percent >= 100
        if row is not None and (row.finished or row.percent >= percent):
            continue
        deps.upsert_progress(
            session,
            user,
            book.id,
            series_id=book.series_id,
            position={"page": max(0, round((book.page_count or 1) * percent / 100) - 1)},
            percent=float(100 if klaar else percent),
            device="kobo",
            finished=klaar,
        )
        bijgewerkt += 1
    return bijgewerkt


# Nickel kent onze boek-id's niet; het enige wat een boek op het apparaat met
# een boek hier verbindt is het pad. Die koppeling hoort een herstart te
# overleven, anders is de voortgang van een Kobo die een week in de la lag niet
# meer thuis te brengen — dus in de database en niet in het geheugen.
PATHS_KEY = "kobo.paden"


def remember(session: Session, gepland: list[Planned]) -> None:
    """Onthoud welk pad op het apparaat bij welk boek hoort.

    Aanvullend: een boek dat uit het venster is gevallen staat mogelijk nog op
    het apparaat, en juist daarvan wil je de stand nog kunnen terugkrijgen.
    """
    row = session.get(Setting, PATHS_KEY)
    if row is None:
        row = Setting(key=PATHS_KEY, value={})
        session.add(row)
    bekend = dict(row.value or {})
    for item in gepland:
        bekend[item.relative] = item.book_id
    row.value = bekend
    session.commit()


def _book_from_path(session: Session, relative: str) -> int | None:
    row = session.get(Setting, PATHS_KEY)
    if row is None:
        return None
    waarde = (row.value or {}).get(relative)
    return int(waarde) if waarde is not None else None


__all__ = [
    "ExportReport",
    "Planned",
    "export",
    "plan",
    "progress_back",
    "remember",
]
