"""Panelen op een stripbladzijde vinden, zonder model.

Een stripbladzijde is opgebouwd uit panelen met **goten** ertussen: stroken die
over de volle breedte of hoogte leeg zijn. Dat is precies genoeg structuur om ze
met rekenwerk te vinden — de klassieke *recursieve XY-cut*. Je maakt de pagina
binair, zoekt rijen die helemaal achtergrond zijn, snijdt daar, en herhaalt dat
per stuk in de andere richting.

Waarom geen model: dit kost milliseconden en nul megabytes, terwijl een
paneeldetector met gewichten in dezelfde orde zit als de YOLO-pipeline die we bij
M8 juist niet wilden. Dezelfde afweging, hetzelfde antwoord.

Wat het níét kan, en waarom er een terugval is:

* Een splash zonder paneelranden heeft geen goten. Dan is de hele pagina het
  antwoord, en dat is ook het juiste antwoord.
* Panelen die elkaar overlappen of schuin lopen laten zich niet met rechte
  sneden scheiden. Dan blijft er een groter blok staan waar er twee hadden
  moeten zijn — vervelend, maar niet fout: je ziet nog steeds tekening.
* Een vuile scanrand loopt over de volle hoogte en kan als paneel meekomen.
  Daar is de randmarge voor.
* **Een grote tekstballon die de paneelrand raakt splitst een paneel.** De
  ballon maakt een wit kanaal dwars door het paneel, en dat is met deze methode
  niet te onderscheiden van een goot. Gemeten op Oishinbo deel 3 hoofdstuk 23,
  pagina 22 en 24. Drie remmen geprobeerd en alle drie gemeten verworpen: een
  hogere ondergrens per paneel gooit de andere helft wég (die inhoud zie je dan
  nooit), een scheve snede weigeren kelderde pagina's naar één paneel (een rij
  met één smal paneel is normaal), en het kleine stuk aan zijn buur plakken gaf
  er juist méér (9 → 12), omdat het samengevoegde blok daarna in de andere
  richting opnieuw wordt gesneden. Dit vraagt een ander signaal — de paneelrand
  zelf herkennen als donkere lijn — en dat is geen drempel maar een tweede
  methode.

De uitvoer is genormaliseerd op 0..1, net als de tekstvlakken van een vertaling:
dezelfde panelen moeten over elk beeldprofiel passen.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

__all__ = ["Panel", "detect", "reading_order"]

#: Waarboven een pixel achtergrond heet (0 = zwart, 255 = wit). Ruim onder wit,
#: want papier is zelden 255 en een scan heeft ruis.
ACHTERGROND_VANAF = 236

#: Hoeveel van een rij gevuld mag zijn en toch als goot telt.
#:
#: Ruimer dan je zou denken, en dat is gemeten. Op 0,012 bleef Oishinbo deel 3
#: hoofdstuk 26 pagina 2 op één paneel steken: de goot tussen de bovenste strook
#: en de rij eronder draagt daar het bijschrift "TENPACHI" en de aanzet van twee
#: paneelranden, en dat is genoeg om hem als "gevuld" te laten gelden. Op 0,05
#: vindt hij daar de juiste 4 panelen, terwijl zes andere pagina's uit twee
#: hoofdstukken hun aantal houden (8, 5→6, 6→7, 4, 6, 8). Een goot mag dus wat
#: vuiler zijn dan een lege strook.
GOOT_VULLING = 0.05

#: Hoe breed een goot minstens is, als deel van de korte zijde van het stuk dat
#: gesneden wordt. Kleiner en je snijdt tussen twee tekstregels door.
#:
#: Samen met GOOT_VULLING gemeten: pas mét allebei (0,05 en 0,008) vindt hij op
#: Oishinbo deel 3 hoofdstuk 26 pagina 2 de juiste 4 panelen in plaats van 1.
#: Elk apart hielp niet — dat is precies waarom hier getallen staan en geen
#: onderbuik.
GOOT_MINIMUM = 0.008

#: Hoe klein een paneel mag zijn, als deel van de pagina-oppervlakte. Daaronder
#: is het een bijschrift of ruis, geen paneel.
PANEEL_MINIMUM = 0.012

#: Hoe diep we blijven snijden. Zes rondes is ruim: een pagina met 3x3 panelen
#: is na vier rondes klaar.
MAX_DIEPTE = 6

#: Waarop we rekenen. Groter maakt het niet nauwkeuriger — goten zijn tientallen
#: pixels breed — en wel trager.
REKENBREEDTE = 700

#: Hoeveel van de rand we negeren bij het snijden, als deel van de pagina.
#:
#: Een scan heeft vaak een donkere band langs een zijde: de rand van het boek of
#: de klep van de scanner. Die loopt over de volle hoogte en verbindt daarmee
#: alles wat er anders los van stond — één zwarte streep rechts en de hele
#: pagina is opeens één blok. Gemeten op Oishinbo deel 3 hoofdstuk 26 pagina 2:
#: mét rand 1 paneel, zonder rand 8. De panelen worden daarna wel op de hele
#: pagina teruggerekend, want die rand hoort niet in het antwoord thuis.
RANDMARGE = 0.02


@dataclass(frozen=True)
class Panel:
    """Eén paneel, genormaliseerd op 0..1 ten opzichte van de hele pagina."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def oppervlak(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]


def detect(image: bytes, *, right_to_left: bool = False) -> list[Panel]:
    """De panelen op deze pagina, in leesvolgorde.

    Vindt hij er minder dan twee, dan is de hele pagina het antwoord. Dat is
    geen mislukking maar het eerlijke resultaat: een splash ís één paneel.
    """
    masker, breedte, hoogte = _masker(image)
    if breedte == 0 or hoogte == 0:
        return [Panel(0.0, 0.0, 1.0, 1.0)]

    # De rand eraf vóór het snijden; zie RANDMARGE.
    marge_x = int(RANDMARGE * breedte)
    marge_y = int(RANDMARGE * hoogte)
    stukken = _snij(
        masker,
        marge_x,
        marge_y,
        max(marge_x + 1, breedte - marge_x),
        max(marge_y + 1, hoogte - marge_y),
        diepte=0,
        horizontaal=True,
    )
    panelen = [
        Panel(x0 / breedte, y0 / hoogte, x1 / breedte, y1 / hoogte)
        for x0, y0, x1, y1 in stukken
    ]
    panelen = [p for p in panelen if p.oppervlak >= PANEEL_MINIMUM]

    if len(panelen) < 2:
        return [Panel(0.0, 0.0, 1.0, 1.0)]
    return reading_order(panelen, right_to_left=right_to_left)


def reading_order(panelen: list[Panel], *, right_to_left: bool) -> list[Panel]:
    """Van boven naar beneden, en binnen een rij mee met de leesrichting.

    Panelen die elkaar verticaal grotendeels overlappen horen bij dezelfde rij;
    zonder dat zou een paneel dat een paar pixels hoger begint de hele volgorde
    omgooien.
    """
    if not panelen:
        return []
    op_hoogte = sorted(panelen, key=lambda p: p.y0)
    rijen: list[list[Panel]] = []
    for paneel in op_hoogte:
        for rij in rijen:
            # Zelfde rij als ze elkaar verticaal voor meer dan de helft raken.
            hoogte = min(p.y1 for p in rij) - max(p.y0 for p in rij)
            overlap = min(paneel.y1, min(p.y1 for p in rij)) - max(
                paneel.y0, max(p.y0 for p in rij)
            )
            if overlap > 0 and overlap >= 0.5 * min(hoogte, paneel.y1 - paneel.y0):
                rij.append(paneel)
                break
        else:
            rijen.append([paneel])

    uit: list[Panel] = []
    for rij in rijen:
        uit.extend(sorted(rij, key=lambda p: p.x0, reverse=right_to_left))
    return uit


# MARK: - Onderwater


def _masker(image: bytes) -> tuple[list[list[bool]], int, int]:
    """Per pixel: staat hier inkt? Verkleind, want goten zijn grof."""
    with Image.open(io.BytesIO(image)) as bron:
        bron.load()
        grijs = bron.convert("L")
        if grijs.width > REKENBREEDTE:
            hoogte = max(1, round(REKENBREEDTE * grijs.height / grijs.width))
            grijs = grijs.resize((REKENBREEDTE, hoogte), Image.Resampling.BILINEAR)
        breedte, hoogte = grijs.size
        ruw = grijs.tobytes()

    masker = [
        [ruw[rij * breedte + kolom] < ACHTERGROND_VANAF for kolom in range(breedte)]
        for rij in range(hoogte)
    ]
    return masker, breedte, hoogte


def _snij(
    masker: list[list[bool]],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    diepte: int,
    horizontaal: bool,
) -> list[tuple[int, int, int, int]]:
    """Snijd dit stuk op zijn goten, afwisselend horizontaal en verticaal."""
    if diepte >= MAX_DIEPTE or x1 - x0 < 2 or y1 - y0 < 2:
        return [_krimp(masker, x0, y0, x1, y1)]

    grenzen = _goten(masker, x0, y0, x1, y1, horizontaal=horizontaal)
    if not grenzen:
        # In deze richting valt niets te snijden; probeer de andere. Lukt dat
        # ook niet, dan is dit stuk zo klein als het wordt.
        andere = _goten(masker, x0, y0, x1, y1, horizontaal=not horizontaal)
        if not andere:
            return [_krimp(masker, x0, y0, x1, y1)]
        grenzen = andere
        horizontaal = not horizontaal

    stukken: list[tuple[int, int, int, int]] = []
    for van, tot in grenzen:
        if horizontaal:
            stukken.extend(
                _snij(masker, x0, van, x1, tot, diepte=diepte + 1, horizontaal=False)
            )
        else:
            stukken.extend(
                _snij(masker, van, y0, tot, y1, diepte=diepte + 1, horizontaal=True)
            )
    return stukken


def _goten(
    masker: list[list[bool]], x0: int, y0: int, x1: int, y1: int, *, horizontaal: bool
) -> list[tuple[int, int]]:
    """De stukken tussen de goten, of leeg als er niets te snijden valt."""
    lengte = (y1 - y0) if horizontaal else (x1 - x0)
    dwars = (x1 - x0) if horizontaal else (y1 - y0)
    if lengte < 4 or dwars < 4:
        return []

    gevuld: list[bool] = []
    for index in range(lengte):
        inkt = 0
        if horizontaal:
            rij = masker[y0 + index]
            inkt = sum(1 for kolom in range(x0, x1) if rij[kolom])
        else:
            kolom = x0 + index
            inkt = sum(1 for rij in range(y0, y1) if masker[rij][kolom])
        gevuld.append(inkt / dwars > GOOT_VULLING)

    minimum = max(2, int(GOOT_MINIMUM * dwars))
    stukken: list[tuple[int, int]] = []
    begin: int | None = None
    leeg = 0
    for index, vol in enumerate(gevuld):
        if vol:
            if begin is None:
                begin = index
            leeg = 0
        else:
            leeg += 1
            if begin is not None and leeg >= minimum:
                stukken.append((begin, index - leeg + 1))
                begin = None
    if begin is not None:
        stukken.append((begin, lengte))

    # Eén stuk betekent: geen goot gevonden die iets scheidt.
    if len(stukken) < 2:
        return []


    verschuiving = y0 if horizontaal else x0
    return [(verschuiving + van, verschuiving + tot) for van, tot in stukken]


def _krimp(
    masker: list[list[bool]], x0: int, y0: int, x1: int, y1: int
) -> tuple[int, int, int, int]:
    """De lege rand rond een stuk weghalen, zodat het paneel strak zit."""
    top, onder, links, rechts = y0, y1, x0, x1
    while top < onder and not any(masker[top][x0:x1]):
        top += 1
    while onder > top and not any(masker[onder - 1][x0:x1]):
        onder -= 1
    while links < rechts and not any(masker[rij][links] for rij in range(top, onder)):
        links += 1
    while rechts > links and not any(
        masker[rij][rechts - 1] for rij in range(top, onder)
    ):
        rechts -= 1
    if top >= onder or links >= rechts:
        return (x0, y0, x1, y1)
    return (links, top, rechts, onder)
