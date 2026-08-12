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

from bookpal.models import Book, Series, Subscription

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

    # Abonnementen verhuizen mee, zodat nieuwe hoofdstukken binnen blijven
    # komen. Heeft de blijver er al een, dan houdt die de zijne: twee
    # abonnementen op één serie zou dubbel downloaden.
    keep_subscription = session.scalar(
        select(Subscription).where(Subscription.series_id == keep.id)
    )
    for subscription in session.scalars(
        select(Subscription).where(Subscription.series_id == absorb.id)
    ):
        if keep_subscription is None:
            subscription.series_id = keep.id
            keep_subscription = subscription
        else:
            session.delete(subscription)

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
    return "".join(character for character in title.lower() if character.isalnum())
