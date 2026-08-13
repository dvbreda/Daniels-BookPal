"""De kleur van het model over ons eigen lijnwerk leggen.

Een model dat een hele pagina inkleurt, tekent hem in feite opnieuw. Het volgt
de tekening goed genoeg om te zien wat wat is, maar de inkt komt er zachter uit
dan hij erin ging: op een gemeten pagina zakte het aandeel zwart van 12,9% naar
6,9%. Bij een strip is dat precies het verkeerde verlies — het lijnwerk ís de
tekening, en de letters in de ballonnen horen erbij.

Daarom nemen we van het ingekleurde beeld alleen de kleur over, en houden we de
helderheid van onze eigen pagina aan. Niet als vervanging maar als ondergrens:
waar de verf donkerder is dan het papier blijft die schaduw staan, zodat de
wassing en de papierstructuur behouden blijven. Waar wij zwart hebben, wint ons
zwart altijd.

Een losse kleurlaag opvragen (dus zonder lijnen, om er zelf overheen te
multiplyen) werkt niet: het model schildert die laag opnieuw in plaats van hem
uit te lijnen, en dan staat de kleur naast de tekening. De omweg via de hele
ingekleurde pagina is juist wél uitgelijnd, want daar kopieert het model zijn
eigen invoer.
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops

__all__ = ["colour_fraction", "is_colour", "recompose"]

#: Waarboven een pagina "heeft al kleur" heet. Zwart-witte binnenpagina's meten
#: over de hele bibliotheek 0,0%; alles met kleur van de tekenaar zelf zit op
#: 10% of hoger. De maat kijkt naar verzadiging en niet naar het verschil tussen
#: de kanalen, want vergeeld papier haalt dat verschil moeiteloos en dan zou
#: elke oude scan als kleur gelden.
#:
#: Het onderscheid tussen tweekleurendruk en volle kleur zit hier bewust niet
#: in: dat is niet betrouwbaar te meten (gemeten gaven beide drie tinten, en een
#: kleuromslag zelfs één), en het hoeft ook niet — dit is een waarschuwing en
#: geen verbod. Eén keer bevestigen en het gebeurt alsnog.
COLOUR_LIMIT = 5.0
_SATURATED = 60


def colour_fraction(image: bytes) -> float:
    """Hoeveel procent van de pagina echt kleur heeft."""
    page = Image.open(io.BytesIO(image)).convert("RGB")
    # Verkleinen scheelt bijna een seconde per pagina en verandert het aandeel
    # niet noemenswaardig.
    breed = 200
    page = page.resize((breed, max(1, round(breed * page.height / page.width))))
    # tobytes en niet getdata: dat laatste is in nieuwere Pillow afgeschaft, en
    # voor een band van één byte per pixel is dit precies hetzelfde.
    pixels = page.convert("HSV").split()[1].tobytes()
    if not pixels:
        return 0.0
    return 100.0 * sum(1 for value in pixels if value > _SATURATED) / len(pixels)


def is_colour(image: bytes) -> bool:
    """Heeft deze pagina al kleur van de tekenaar zelf?

    Inkleuren is dan geen inkleuren maar overschilderen: het model vervangt het
    palet door zijn eigen aquarel. Op een pagina uit Dirkjan werd het paarse
    jasje zwart en de knalgroene achtergrond een zachte wassing. Dat kost
    hetzelfde als een echte inkleuring, dus wordt er eerst gevraagd.
    """
    return colour_fraction(image) > COLOUR_LIMIT


def recompose(original: bytes, coloured: bytes) -> Image.Image:
    """Kleur uit ``coloured``, lijnwerk en letters uit ``original``.

    Verschilt het formaat, dan wordt de kleur naar de pagina geschaald: een
    model levert soms net een andere maat terug, en dan hoort de tekening te
    winnen.
    """
    pagina = Image.open(io.BytesIO(original)).convert("RGB")
    verf = Image.open(io.BytesIO(coloured)).convert("RGB")
    if verf.size != pagina.size:
        verf = verf.resize(pagina.size, Image.Resampling.LANCZOS)

    tint, verzadiging, verf_licht = verf.convert("HSV").split()
    _, _, pagina_licht = pagina.convert("HSV").split()
    # De donkerste van de twee: onze inkt blijft inkt, en een wassing die
    # donkerder is dan het papier blijft zichtbaar als schaduw.
    licht = ImageChops.darker(pagina_licht, verf_licht)
    return Image.merge("HSV", (tint, verzadiging, licht)).convert("RGB")
