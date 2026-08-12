"""Leesinstellingen die het beeld zelf raken: bijsnijden en contrast.

Overgenomen uit wat rakuyomi (de manga-plugin voor KOReader) als aanbevolen
instellingen geeft: "page crop: auto" en "fit: full". Bijsnijden is daar niet
voor de sier — een scan heeft vaak een centimeter wit of grijs rondom, en op
een Kobo van zes inch is dat zo een vijfde van je scherm dat je aan niets
kwijt bent. Contrast staat er niet in hun lijst maar hoort er wel bij: veel
scanlations zijn grijzig, en op e-ink zonder achtergrondverlichting leest dat
slecht.

Bewust server-side en niet met CSS in de lezer. Twee redenen: de Kobo en Lite
kunnen geen CSS-filters op een afbeelding toepassen zonder het hele beeld eerst
in de browser te trekken, en het resultaat is cachebaar — één keer bijsnijden
per pagina en profiel, in plaats van bij elke weergave opnieuw.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageOps

# Hoe ver een pixel van de hoekkleur mag afwijken en nog steeds "rand" heet.
# Ruim genomen: een gescande witrand is zelden zuiver wit, en jpeg-artefacten
# rond de bladspiegel maken het nog rommeliger.
_BORDER_TOLERANCE = 22

# Nooit meer dan dit deel van een zijde wegsnijden. Zonder die rem eet een
# pagina die grotendeels wit is (een titelblad, een slotpagina) zichzelf op.
_MAX_TRIM = 0.25


@dataclass(frozen=True, slots=True)
class Adjustments:
    """Wat er met het beeld moet gebeuren, los van het apparaatprofiel."""

    crop: bool = False
    # 100 = onveranderd. Onder de 100 vlakker, erboven meer contrast.
    contrast: int = 100

    @property
    def active(self) -> bool:
        return self.crop or self.contrast != 100

    @property
    def cache_key(self) -> str:
        """Gaat mee in de cachesleutel; anders zou een bijgesneden pagina de
        onbewerkte overschrijven en andersom."""
        return "" if not self.active else f"|crop={int(self.crop)}|con={self.contrast}"


def apply(image: Image.Image, adjustments: Adjustments) -> Image.Image:
    result = image
    if adjustments.crop:
        result = autocrop(result)
    if adjustments.contrast != 100:
        result = boost_contrast(result, adjustments.contrast)
    return result


def autocrop(image: Image.Image) -> Image.Image:
    """Snijd een egale rand weg.

    Werkt op een grijswaardenkopie: bij een gekleurde pagina gaat het nog
    steeds om "hoe licht is dit", en één kanaal is drie keer zo snel als drie.
    """
    gray = image.convert("L")
    corner = _border_value(gray)

    # Alles wat dicht bij de hoekkleur ligt naar zwart, de rest naar wit; dan
    # geeft getbbox() precies het gebied dat níet rand is.
    mask = gray.point(lambda value: 0 if abs(value - corner) <= _BORDER_TOLERANCE else 255)
    box = mask.getbbox()
    if box is None:
        # Volledig egaal (een lege pagina); dan valt er niets te winnen.
        return image

    width, height = image.size
    left, upper, right, lower = box
    # De rem: liever een randje laten staan dan een pagina halveren.
    left = min(left, int(width * _MAX_TRIM))
    upper = min(upper, int(height * _MAX_TRIM))
    right = max(right, width - int(width * _MAX_TRIM))
    lower = max(lower, height - int(height * _MAX_TRIM))

    if (left, upper, right, lower) == (0, 0, width, height):
        return image
    return image.crop((left, upper, right, lower))


def _border_value(gray: Image.Image) -> int:
    """De kleur van de rand, geschat uit de vier hoeken.

    Niet één hoek: daar kan net een paneel of een paginanummer staan. De
    mediaan van vier is bestand tegen zo'n uitschieter.
    """
    width, height = gray.size
    values: list[int] = []
    for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        pixel = gray.getpixel(point)
        if isinstance(pixel, tuple):  # pragma: no cover - "L" geeft een int
            pixel = pixel[0]
        values.append(int(pixel or 0))
    values.sort()
    return (values[1] + values[2]) // 2


def boost_contrast(image: Image.Image, contrast: int) -> Image.Image:
    """Rek het grijsbereik op.

    ``autocontrast`` in plaats van een vaste curve: bij een grijzige scan wil
    je dat het lichtste punt wit wordt en het donkerste zwart, en hoevéél
    ruimte daarvoor nodig is verschilt per pagina. De instelling bepaalt hoe
    agressief dat mag: hoe hoger, hoe meer uiteinden er afgekapt worden.
    """
    cutoff = max(0.0, min(20.0, (contrast - 100) / 5))
    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")
    return ImageOps.autocontrast(image, cutoff=cutoff)
