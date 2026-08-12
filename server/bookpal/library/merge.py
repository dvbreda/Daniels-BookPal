"""Twee series samenvoegen tot één.

Komt vaker voor dan je zou willen: dezelfde reeks staat als lokale map én als
abonnement, of een scan heeft door een spelling- of hoofdletterverschil twee
series gemaakt ("Crayon Shin-Chan" naast "Crayon Shin-chan").

Het uitgangspunt is dat er niets verloren mag gaan. Boeken verhuizen, en van de
serie-gegevens wint per veld wat er ís boven wat er niet is — een lege waarde
overschrijft nooit een gevulde. De bron-koppeling en tracker-ids gaan mee, zodat
een samengevoegde serie zowel je eigen bestanden als het lopende abonnement
houdt.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.metadata.titles import normalise as normalise_title
from bookpal.models import Book, Edition, Series, Subscription

logger = logging.getLogger(__name__)


class MergeError(RuntimeError):
    """Samenvoegen kan niet; de reden staat in het bericht."""


def merge(session: Session, keep: Series, absorb: Series) -> Series:
    """Voeg ``absorb`` samen in ``keep`` en geef ``keep`` terug.

    ``absorb`` verdwijnt daarna. De boeken zelf blijven ongemoeid op schijf —
    alleen hun serie-koppeling verandert.
    """
    if keep.id == absorb.id:
        raise MergeError("een serie kan niet met zichzelf samengevoegd worden")

    books = list(session.scalars(select(Book).where(Book.series_id == absorb.id)))
    for book in books:
        book.series_id = keep.id

    # Abonnementen verhuizen allemaal mee. Ze blijven naast elkaar bestaan,
    # want dat is juist de bedoeling: de gekleurde uitgave loopt achter op de
    # zwart-witte, en die twee samen maken pas een complete serie. Welke van de
    # twee je te zien krijgt bepaalt de volgorde van de uitgaven, niet welk
    # abonnement de merge heeft overleefd.
    # Ook die van de blijver: zodra er twee naast elkaar staan is "de reeks van
    # de serie" niet meer eenduidig, dus leggen we hier voor allebei vast welke
    # het is.
    for subscription in session.scalars(
        select(Subscription).where(Subscription.series_id == keep.id)
    ):
        subscription.source_ref = subscription.source_ref or keep.source_ref

    for subscription in session.scalars(
        select(Subscription).where(Subscription.series_id == absorb.id)
    ):
        # De bron-reeks vastleggen vóórdat ``absorb`` verdwijnt: daarna is niet
        # meer te achterhalen welke reeks dit abonnement volgde, en zou het bij
        # de volgende ronde de hoofdstukken van de blijver gaan ophalen.
        subscription.source_ref = subscription.source_ref or absorb.source_ref
        subscription.series_id = keep.id

    # De uitgaven schuiven achter die van de blijver aan: wat je al las blijft
    # eerste keus, het nieuwe vult aan.
    volgende = max(
        (edition.rank for edition in session.scalars(
            select(Edition).where(Edition.series_id == keep.id)
        )),
        default=-1,
    ) + 1
    bezet = {
        edition.name
        for edition in session.scalars(select(Edition).where(Edition.series_id == keep.id))
    }
    for edition in session.scalars(
        select(Edition).where(Edition.series_id == absorb.id).order_by(Edition.rank)
    ):
        edition.series_id = keep.id
        edition.rank = volgende
        # Twee keer "Eigen bestanden" onder elkaar zegt niets. Pas hier wordt
        # de naam dubbelzinnig, dus pas hier hoort hij te veranderen.
        if edition.name in bezet:
            edition.name = f"{edition.name} — {absorb.title}"
        bezet.add(edition.name)
        volgende += 1

    _merge_fields(keep, absorb)

    session.delete(absorb)
    session.commit()
    logger.info("serie %s samengevoegd in %s (%s boeken)", absorb.title, keep.title, len(books))
    return keep


def _merge_fields(keep: Series, absorb: Series) -> None:
    """Per veld: wat er ís wint van wat er niet is.

    Bewust niet "de blijver wint altijd": dan zou je bij het samenvoegen van
    een lokale map met een abonnement de bron-koppeling en de omslag kwijt zijn,
    precies de gegevens waar het abonnement zijn waarde aan ontleent.
    """
    for field in ("summary", "publisher", "cover_url", "source_ref", "folder_path"):
        if not getattr(keep, field) and getattr(absorb, field):
            setattr(keep, field, getattr(absorb, field))

    if keep.source_id is None and absorb.source_id is not None:
        keep.source_id = absorb.source_id
    if keep.cover_page_index is None and absorb.cover_page_index is not None:
        keep.cover_page_index = absorb.cover_page_index

    # Lijsten en woordenboeken samenvoegen in plaats van kiezen.
    keep.authors = list(dict.fromkeys([*(keep.authors or []), *(absorb.authors or [])]))
    keep.tags = list(dict.fromkeys([*(keep.tags or []), *(absorb.tags or [])]))
    keep.tracker_ids = {**(absorb.tracker_ids or {}), **(keep.tracker_ids or {})}


def suggest(session: Session) -> list[tuple[Series, Series]]:
    """Series die waarschijnlijk hetzelfde zijn.

    Alleen op genormaliseerde titel: dat vangt het gangbare geval (hoofdletters
    en leestekens) zonder te gaan raden. Iets als "Shin-chan" naast "Crayon
    Shin-chan" blijft aan jou om te beoordelen.
    """
    per_sleutel: dict[str, list[Series]] = {}
    for series in session.scalars(select(Series)).all():
        sleutel = _normalise(series.title)
        per_sleutel.setdefault(sleutel, []).append(series)

    paren: list[tuple[Series, Series]] = []
    for groep in per_sleutel.values():
        if len(groep) < 2:
            continue
        # De serie met een bron als blijver: die houdt het abonnement, en de
        # ander levert meestal alleen bestanden aan.
        groep.sort(key=lambda s: (s.source_id is None, s.id))
        for andere in groep[1:]:
            paren.append((groep[0], andere))
    return paren


def _normalise(title: str) -> str:
    # Gedeeld met het koppelen aan MyAnimeList: daar heet dezelfde reeks
    # "Shinya Shokudou" waar je map "Shinya Shokudo" zegt.
    return normalise_title(title)


# Korter dan dit is te weinig om iets op te baseren: "Ai" zit in van alles.
_MINIMUM_OVERLAP = 6


def similar(session: Session, series: Series) -> list[Series]:
    """Series die op deze lijken, meest waarschijnlijke eerst.

    Twee soorten treffer. Gelijk na normaliseren is de sterkste — "Shinya
    Shokudou" naast "Shinya Shokudo". Daarnaast de titel die met de andere
    begint: "One Piece" en "One Piece (Official Colored)" zijn dezelfde reeks
    met een editie erachter geplakt, en dat is precies het geval waarin je ze
    als uitgaven naast elkaar wilt.

    Een voorstel en geen automatisme: "Dragon Ball" en "Dragon Ball Super"
    voldoen ook aan die regel en zijn wél verschillende reeksen.
    """
    mij = _normalise(series.title)
    if not mij:
        return []

    gelijk: list[Series] = []
    begint_met: list[Series] = []
    for andere in session.scalars(select(Series).where(Series.id != series.id)):
        hun = _normalise(andere.title)
        if not hun:
            continue
        if hun == mij:
            gelijk.append(andere)
        elif (
            len(mij) >= _MINIMUM_OVERLAP
            and len(hun) >= _MINIMUM_OVERLAP
            and (hun.startswith(mij) or mij.startswith(hun))
        ):
            begint_met.append(andere)

    return gelijk + begint_met
