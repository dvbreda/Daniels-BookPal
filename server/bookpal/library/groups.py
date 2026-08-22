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

from sqlalchemy import ColumnElement, and_, select

from bookpal.models import Book, BookKind, LibraryRoot, OriginRegion, Series


class SeriesGroup(enum.StrEnum):
    BOEKEN = "boeken"
    STRIPS = "strips"
    MANGA = "manga"
    TIJDSCHRIFTEN = "tijdschriften"
    PRINT = "print"


#: Welke bibliotheekmap bij welke groep hoort. Drukwerk valt niet uit de
#: inhoud af te leiden — een tijdschrift is net zo goed een pdf als een boek,
#: en de herkomst zegt er niets over. De map is het enige eerlijke signaal, en
#: die heb jij zelf ingericht.
_MAP_GROEPEN = {
    SeriesGroup.TIJDSCHRIFTEN: "/library/tijdschriften",
    SeriesGroup.PRINT: "/library/print",
}


def condition(group: SeriesGroup) -> ColumnElement[bool]:
    """De where-clausule bij één groep.

    Manga en strips zijn allebei ``comic``; alleen de herkomst scheidt ze. Een
    serie zonder herkomst (``unknown``) valt daarmee bij de strips — dat is de
    goede kant om op te vallen, want een niet-herkende scan is vaker een strip
    dan manga, en hij blijft zo in elk geval ergens zichtbaar.
    """
    # Drukwerk eerst: die mappen zijn hun eigen groep, en hun pdf's zouden
    # anders ook onder "boeken" vallen — dan stond een Lego-catalogus tussen
    # je romans.
    if pad := _MAP_GROEPEN.get(group):
        return Series.library_root_id.in_(select(LibraryRoot.id).where(LibraryRoot.path == pad))

    # En andersom: wat in een drukwerkmap staat hoort nergens anders bij.
    buiten_drukwerk = Series.library_root_id.not_in(
        select(LibraryRoot.id).where(LibraryRoot.path.in_(list(_MAP_GROEPEN.values())))
    )
    strip = and_(Series.books.any(Book.kind == BookKind.COMIC), buiten_drukwerk)
    match group:
        case SeriesGroup.BOEKEN:
            return and_(Series.books.any(Book.kind != BookKind.COMIC), buiten_drukwerk)
        case SeriesGroup.STRIPS:
            return and_(strip, Series.origin_region != OriginRegion.JAPAN)
        case SeriesGroup.MANGA:
            return and_(strip, Series.origin_region == OriginRegion.JAPAN)
        case _:  # pragma: no cover — alle leden staan hierboven
            raise ValueError(group)


__all__ = ["SeriesGroup", "condition"]
