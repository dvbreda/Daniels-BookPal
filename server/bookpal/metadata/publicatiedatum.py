"""Wanneer een uitgave verscheen, uit de bestandsnaam.

Voor tijdschriften is de datum wat een nummer *is* — er is geen deel of
hoofdstuk, alleen "september 2026". Zonder die datum staat een jaargang in
willekeurige volgorde en is er niets om op te sorteren.

Gebouwd op twee echte bestanden uit `_tijdschriften` (`..._09.2026_clean.pdf`
en `...-June2026.pdf`) en daarna verbreed naar de vormen die je in dezelfde
hoek tegenkomt. Twee voorbeelden is een smalle basis, dus de vuistregel
hieronder is streng: liever niets teruggeven dan een verzonnen datum, want een
verkeerde datum sorteert stilletjes verkeerd en dat zie je niet.

Alleen maand en jaar. Een tijdschrift heeft zelden een dag, en een verzonnen
"1e van de maand" zou suggereren dat we het weten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Ruim genoeg voor een archief met oude jaargangen, krap genoeg dat een
#: resolutie (1080) of een nummer nooit als jaartal doorgaat.
_VROEGSTE_JAAR = 1900
_LAATSTE_JAAR = 2099

_MAANDEN = {
    "januari": 1,
    "january": 1,
    "jan": 1,
    "februari": 2,
    "february": 2,
    "feb": 2,
    "maart": 3,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "mei": 5,
    "may": 5,
    "juni": 6,
    "june": 6,
    "jun": 6,
    "juli": 7,
    "july": 7,
    "jul": 7,
    "augustus": 8,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "oktober": 10,
    "october": 10,
    "okt": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_MAANDNAMEN = "|".join(sorted(_MAANDEN, key=len, reverse=True))

#: `June2026`, `June 2026`, `sep-2026`. Zonder scheidingsteken moet ook: zo
#: staat het in `BBCGardeners'World-June2026.pdf`.
_NAAM_JAAR = re.compile(rf"(?<![a-z])({_MAANDNAMEN})[\s._-]*((?:19|20)\d{{2}})", re.I)

#: `2026-09`, `2026_09`. Jaar eerst is nooit dubbelzinnig.
_JAAR_MAAND = re.compile(r"(?<!\d)((?:19|20)\d{2})[._-](0?[1-9]|1[0-2])(?!\d)")

#: `09.2026`, `09-2026`. Maand eerst; alleen met een scheidingsteken, anders
#: zou `092026` meetellen en dat is geen datum maar een nummer.
_MAAND_JAAR = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])[._-]((?:19|20)\d{2})(?!\d)")

#: Alleen een jaartal, als laatste redmiddel.
_JAAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


@dataclass(frozen=True, slots=True)
class Publicatie:
    """Wanneer dit verscheen. ``maand`` mag ontbreken."""

    jaar: int
    maand: int | None = None

    @property
    def sorteersleutel(self) -> float:
        """Voor één volgorde over alles heen; zonder maand net vóór januari."""
        return self.jaar + (self.maand or 0) / 100

    def __str__(self) -> str:
        return f"{self.jaar}-{self.maand:02d}" if self.maand else str(self.jaar)


def _geldig(jaar: int) -> bool:
    return _VROEGSTE_JAAR <= jaar <= _LAATSTE_JAAR


def uit_naam(naam: str) -> Publicatie | None:
    """De publicatiedatum uit een bestands- of mapnaam, of niets.

    De volgorde is die van afnemende zekerheid. Een maandnaam is het sterkste
    signaal — die kan niets anders betekenen — en een los jaartal het zwakste,
    want dat kan ook een titel zijn ("Blade Runner 2049"). Daarom komt dat
    laatst en alleen als er verder niets staat.
    """
    if treffer := _NAAM_JAAR.search(naam):
        jaar = int(treffer.group(2))
        if _geldig(jaar):
            return Publicatie(jaar=jaar, maand=_MAANDEN[treffer.group(1).lower()])

    if treffer := _JAAR_MAAND.search(naam):
        jaar = int(treffer.group(1))
        if _geldig(jaar):
            return Publicatie(jaar=jaar, maand=int(treffer.group(2)))

    if treffer := _MAAND_JAAR.search(naam):
        jaar = int(treffer.group(2))
        if _geldig(jaar):
            return Publicatie(jaar=jaar, maand=int(treffer.group(1)))

    if treffer := _JAAR.search(naam):
        jaar = int(treffer.group(1))
        if _geldig(jaar):
            return Publicatie(jaar=jaar)

    return None


__all__ = ["Publicatie", "uit_naam"]
