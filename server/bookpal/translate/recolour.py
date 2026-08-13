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

__all__ = ["recompose"]


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
