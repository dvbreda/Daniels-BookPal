"""De drie vertaalstanden (M8).

De keuze is een echte afweging, geen voorkeur, en de gemeten verschillen staan
in `docs/architectuur.md` onder "De drie vertaalstanden". Kort:

* ``TEXT`` — het taalmodel leest de pagina en geeft tekst + coördinaten terug;
  wij tekenen die zelf met Comic Neue. Voorspelbaar correct, raakt de tekening
  nooit aan, en je kunt op een ballon tikken voor het origineel. Ongeveer
  $0,002 per pagina.
* ``IMAGE_FAST`` — een beeldmodel hertekent de hele pagina mét vertaling.
  Mooier ingepast, maar liet in onze tests op 3 van de 4 pagina's iets liggen
  (een onvertaalde ballon, een verzonnen regel, één keer een gewijzigd bedrag).
  Ongeveer $0,067 per pagina.
* ``IMAGE_PRO`` — hetzelfde, met het zware model. In alle vier de tests
  bruikbaar. Ongeveer $0,134 per pagina, dus ruim zestig keer de goedkope stand.

Een vierde, hybride stand is geprobeerd en weer verwijderd: het beeldmodel de
ballonnen laten leegvegen zodat onze eigen tekst er netjes in past. Zowel het
snelle als het zware model gaven de pagina ongewijzigd terug — met de tekst er
nog in — waardoor onze vertaling er dubbel overheen kwam te staan. Erasure is
kennelijk iets anders dan hertekenen. De tekststand doet feitelijk hetzelfde,
alleen met een wit vlakje in plaats van een ingevulde achtergrond.

De beeldstanden leveren een hele pagina op in plaats van losse tekstvlakken.
Daarom kan er in die standen niet op een ballon getikt worden voor het
origineel — het origineel is dan de onbewerkte pagina, die de lezer met dezelfde
schakelaar terugkrijgt.
"""

from __future__ import annotations

from enum import StrEnum

from bookpal.config import settings


class TranslateMode(StrEnum):
    TEXT = "text"
    IMAGE_FAST = "image_fast"
    IMAGE_PRO = "image_pro"

    @property
    def is_image(self) -> bool:
        """Levert deze stand een vervangende afbeelding op?"""
        return self is not TranslateMode.TEXT

    @property
    def needs_bubbles(self) -> bool:
        """Zet deze stand onze eigen tekst over het beeld heen?"""
        return self is TranslateMode.TEXT

    @property
    def provider(self) -> str:
        """De sleutel waaronder het resultaat wordt bewaard.

        Bewust het modelnaam-niveau en niet alleen "gemini": een pagina die met
        het goedkope beeldmodel is gedaan, mag niet doorgaan voor een pagina die
        met het dure model is gedaan, en andersom moet je van dezelfde pagina
        beide kunnen hebben zonder dat ze elkaar overschrijven.
        """
        return _PROVIDERS[self]

    @property
    def model(self) -> str:
        if self is TranslateMode.IMAGE_PRO:
            return settings.gemini_image_model_pro
        if self.is_image:
            return settings.gemini_image_model_fast
        return settings.gemini_model


_PROVIDERS = {
    TranslateMode.TEXT: "gemini",
    TranslateMode.IMAGE_FAST: "gemini-image-fast",
    TranslateMode.IMAGE_PRO: "gemini-image-pro",
}

# Wat er getoond wordt als een pagina in meerdere standen klaarstaat: het beste
# wat er ligt wint, want daar is al voor betaald.
BEST_FIRST = (TranslateMode.IMAGE_PRO, TranslateMode.IMAGE_FAST, TranslateMode.TEXT)


def from_provider(provider: str) -> TranslateMode | None:
    for mode, name in _PROVIDERS.items():
        if name == provider:
            return mode
    return None
