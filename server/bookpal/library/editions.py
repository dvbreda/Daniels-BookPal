"""Eén leeslijst uit meerdere uitgaven.

Van dezelfde reeks bestaan vaak meerdere versies naast elkaar: de gekleurde
uitgave die achterloopt, het zwart-witte origineel dat compleet is, je eigen
bestanden op de NAS, en van een boek soms simpelweg drie drukken. Die horen in
één lijst, niet in drie series.

Het model is dat van een vak met vakjes. Elke aflevering is een *slot*, en elke
uitgave kan dat slot vullen. Wat je te zien krijgt is per slot de best
gerangschikte uitgave die hem heeft — dus de gekleurde versie zolang die
meekomt, en daarna vanzelf de zwart-witte, zonder dat je iets hoeft om te
zetten. Je voortgang hangt aan het slot en niet aan de uitgave: hoofdstuk 5
gelezen is hoofdstuk 5 gelezen, in welke versie dan ook.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.metadata.titles import normalise
from bookpal.models import Book, Edition, Progress, Series, Subscription

# Waar een boek zonder uitgave in valt. Alles van vóór dit model staat zo, en
# dat hoort de eerste keus te zijn en niet de laatste.
_NO_EDITION_RANK = -1


def slot_of(book: Book) -> str:
    """Welke aflevering dit is, los van de uitgave.

    Het nummer is het sterkste signaal: hoofdstuk 5 is hoofdstuk 5, ook als de
    ene uitgave hem "Chapter 5" noemt en de andere "005 - Vertrek". Zonder
    nummer valt er alleen op titel te groeperen, en dat gaat mis zodra twee
    drukken anders heten — daarom kun je het slot ook met de hand zetten.
    """
    if book.slot:
        return book.slot
    if book.number:
        return f"nr:{book.sort_volume:g}/{book.sort_number:g}"
    return f"titel:{normalise(book.title)}"


@dataclass(frozen=True, slots=True)
class Slot:
    """Eén aflevering, met de uitgave die wint en wat er verder ligt."""

    key: str
    chosen: Book
    alternatives: list[Book]

    @property
    def books(self) -> list[Book]:
        return [self.chosen, *self.alternatives]


def _rank_map(editions: list[Edition]) -> dict[int, int]:
    return {edition.id: edition.rank for edition in editions}


def slots(books: list[Book], editions: list[Edition]) -> list[Slot]:
    """De leeslijst: per aflevering één deel, in leesvolgorde.

    Bij gelijke rang wint het deel dat je al hebt staan — dat scheelt een
    download voor iets wat er al is.
    """
    ranks = _rank_map(editions)
    groepen: dict[str, list[Book]] = defaultdict(list)
    for book in books:
        groepen[slot_of(book)].append(book)

    gevonden: list[Slot] = []
    for key, items in groepen.items():
        items.sort(
            key=lambda book: (
                ranks.get(book.edition_id or -1, _NO_EDITION_RANK),
                book.file_id is None,
                book.id,
            )
        )
        gevonden.append(Slot(key=key, chosen=items[0], alternatives=items[1:]))

    gevonden.sort(
        key=lambda slot: (slot.chosen.sort_volume, slot.chosen.sort_number, slot.chosen.title)
    )
    return gevonden


def readable(found: list[Slot]) -> list[Slot]:
    """Alleen wat je nu kunt openen, met per aflevering de beste die er staat.

    Je voorkeursuitgave heeft een hoofdstuk soms wel in de lijst maar nog niet
    op schijf. Dan is de zwart-witte die je al hebt beter dan een foutmelding;
    zodra de download binnen is wint de voorkeur vanzelf weer.
    """
    klaar: list[Slot] = []
    for slot in found:
        beschikbaar = [book for book in slot.books if book.file_id is not None]
        if not beschikbaar:
            continue
        klaar.append(
            Slot(
                key=slot.key,
                chosen=beschikbaar[0],
                alternatives=[book for book in slot.books if book is not beschikbaar[0]],
            )
        )
    return klaar


def best_progress(slot: Slot, progress: dict[int, Progress]) -> Progress | None:
    """Hoe ver je in deze aflevering bent, in welke uitgave dan ook.

    Lees je hoofdstuk 5 in kleur uit en zakt die uitgave later, dan hoort 5
    gelezen te blijven. Uitgelezen wint van halverwege; daarna telt wie het
    verst is gekomen.
    """
    kandidaten = [row for book in slot.books if (row := progress.get(book.id)) is not None]
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda row: (row.finished, row.percent))




def for_subscription(
    session: Session, series: Series, subscription: Subscription, *, name: str
) -> Edition:
    """De uitgave die bij dit abonnement hoort, aangemaakt als hij nog niet bestaat.

    Nieuw komt achteraan in de voorkeur. Dat is de veilige kant: een bron die
    je er net bij zet hoort niet ongevraagd te bepalen wat je leest.
    """
    bestaand = session.scalar(
        select(Edition).where(Edition.subscription_id == subscription.id)
    )
    if bestaand is not None:
        return bestaand
    return _new(session, series, name=name, subscription_id=subscription.id)


def for_local_files(session: Session, series: Series) -> Edition:
    """De uitgave voor je eigen bestanden op de NAS.

    Die is eerste keus zolang er niets anders is, en blijft dat ook als er later
    een bron bij komt — wat je zelf hebt staan is meestal wat je wilt lezen.
    """
    bestaand = session.scalar(
        select(Edition).where(
            Edition.series_id == series.id,
            Edition.subscription_id.is_(None),
            Edition.folder_path.is_(None),
        )
    )
    if bestaand is not None:
        return bestaand
    return _new(session, series, name="Eigen bestanden")


def _new(
    session: Session, series: Series, *, name: str, subscription_id: int | None = None
) -> Edition:
    volgende = session.scalar(
        select(func.max(Edition.rank)).where(Edition.series_id == series.id)
    )
    edition = Edition(
        series_id=series.id,
        name=name,
        rank=0 if volgende is None else volgende + 1,
        subscription_id=subscription_id,
    )
    session.add(edition)
    session.flush()
    return edition

__all__ = [
    "Slot",
    "best_progress",
    "for_local_files",
    "for_subscription",
    "readable",
    "slot_of",
    "slots",
]
