"""De grove indeling: boeken, strips, manga.

Bewust grover dan de tabs. Een tab is een regel die je zelf bouwt en die precies
kan worden; dit is de bijl waarmee je in één tik driekwart van je collectie
wegzet. Op de startpagina bestond die indeling al, en hij hoort in de
bibliotheek net zo goed thuis — dezelfde vier woorden, dezelfde uitkomst.

Waarom dit op de server moet en niet in de client: "strips" is *wel een strip,
maar niet uit Japan*, en dat is geen enkele losse parameter die de API had.
Clientkant naschiften zou werken tot de eerste pagina vol zit en er stilletjes
series buiten de limiet vallen. Eén where-clausule is eerlijker.
"""

from __future__ import annotations

import enum

from sqlalchemy import ColumnElement, and_

from bookpal.models import Book, BookKind, OriginRegion, Series


class SeriesGroup(enum.StrEnum):
    BOEKEN = "boeken"
    STRIPS = "strips"
    MANGA = "manga"


def condition(group: SeriesGroup) -> ColumnElement[bool]:
    """De where-clausule bij één groep.

    Manga en strips zijn allebei ``comic``; alleen de herkomst scheidt ze. Een
    serie zonder herkomst (``unknown``) valt daarmee bij de strips — dat is de
    goede kant om op te vallen, want een niet-herkende scan is vaker een strip
    dan manga, en hij blijft zo in elk geval ergens zichtbaar.
    """
    strip = Series.books.any(Book.kind == BookKind.COMIC)
    match group:
        case SeriesGroup.BOEKEN:
            return Series.books.any(Book.kind != BookKind.COMIC)
        case SeriesGroup.STRIPS:
            return and_(strip, Series.origin_region != OriginRegion.JAPAN)
        case SeriesGroup.MANGA:
            return and_(strip, Series.origin_region == OriginRegion.JAPAN)


__all__ = ["SeriesGroup", "condition"]
