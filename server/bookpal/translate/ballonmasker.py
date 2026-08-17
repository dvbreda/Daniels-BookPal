"""Alleen de ballonnen van het model, de tekening van de tekenaar.

De beeldstand hertekent de héle plaat. Dat leest prima, maar het is niet meer
dezelfde tekening: gemeten op Oishinbo p24 werd de wenkbrauw zwaarder en de
oogvorm anders, en op Crayon Shin-Chan p4 verdween de rastertoon volledig — van
9,4% helwit in het origineel naar 67,0% in de hertekende plaat. Alle
middentonen weg.

Hier gebeurt het omgekeerde: het model levert alleen zijn ballonnen aan, en de
tekening blijft pixel voor pixel het origineel. Hetzelfde idee als
``recolour.recompose``, dat ook alleen de kleur overneemt en het lijnwerk
vasthoudt.

Er wordt niets nieuws besteld. Dit stelt samen wat er al ligt: de hertekende
plaat (``image_path``) en de tekstvlakken uit de goedkope stand
(``json_path``). Beide zijn al betaald.

**Drie dingen die eerst misgingen**, want ze zitten alle drie in de vorm van
de code hieronder:

*Het Japans bleef door de vertaling heen staan.* Het masker was het lichte
deel binnen een vak, en de oorspronkelijke lettertekens zijn donker — die
vielen er dus buiten. Een morfologische sluiting vult ze op.

*De vertaling werd afgekapt* — ``ER MAND UIS?`` waar ``IS ER IEMAND THUIS?``
hoort te staan. Het vak bakent de *oorspronkelijke* tekst af, en Nederlands is
langer dan Engels: het model schrijft er per definitie buiten. Daarom wordt er
eerst ruimer om het vak heen gekeken; de vormherkenning stopt daarna vanzelf
op de ballonrand, dus er wordt geen tekening meegepakt.

*Er verschenen crème rechthoeken op wit papier.* Het model zet een plaat soms
op een beige veld. De lichtste pixel is dan nog steeds wit — vandaar dat een
percentiel dat niet zag — maar het veld eromheen niet. De papiertoon wordt nu
per vak gelijkgetrokken op de mediaan van het papier, niet op de piek.

**Wat er bewust blijft staan.** Op Crayon Shin-Chan p6 houdt de bovenmarge een
vage tint: gemeten +5 tot +10 scheefstand in rood-min-blauw over de band
y=5-30, weg bij y=60. Twee vakken beginnen daar op y=1 en y=4 en lopen door tot
in de panelen, en de crème van het model is niet gelijkmatig — de marge is
créme-er dan het wit binnen een paneel. De mediaan wordt door dat panelwit
gedomineerd, dus één factor per vak corrigeert de marge te weinig. Eén factor
kan geen verloop rechttrekken.

Dieper ligt het hieraan: die marge is geen ballon. Hij komt in het masker omdat
blanco papier overal licht is en dus door `BALLON_DREMPEL` valt. De nette
oplossing is lichte gebieden uitsluiten die aan de rand van de uitsnede vast
zitten — een ballon is een lichte plek ómsloten door een donkere rand, een
marge loopt door tot de rand.

Niet gedaan, en met opzet: een ballon die tegen de paginarand staat raakt die
uitsnederand óók (op p6 loopt een vak tot x=728, de volle breedte). Zo'n filter
zou daar een echte ballon wegsnijden, en dan is de tekst weer afgekapt — de
fout die hierboven drie pogingen kostte. Een vage tint in een marge weegt niet
op tegen dat risico. Wie het alsnog aandurft heeft hiermee de meting.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter

from bookpal.translate.base import Bubble

#: Waarboven een pixel bij het ballonvlak hoort. Papier ligt rond de 245, inkt
#: onder de 100; 200 zit daar ruim tussen en pakt vergeeld papier nog mee.
BALLON_DREMPEL = 200

#: Hoe dik een letterstreek maximaal is, als deel van de paginabreedte. Op de
#: gemeten scans (695-796px breed) kwam dat neer op 11 pixels; relatief zodat
#: een grotere scan niet met gaten in het masker blijft zitten.
LETTERDIKTE_DEEL = 11 / 750

#: Hoeveel het masker over de ballonrand heen mag. Genoeg om de naad op de
#: rand van het model te laten vallen in plaats van op die van ons.
OPREK_DEEL = 0.006

#: Hoeveel ruimer we om het vak heen kijken vóór we vormen zoeken. Zonder dit
#: kan geen enkele gevonden vorm buiten het vak komen, en dan wordt een langere
#: vertaling afgekapt.
VAKLUCHT = 0.04

#: Vult de gevonden vorm minder dan dit deel van het vak, dan is er geen ballon
#: herkend — een bijschrift zonder getekende rand. Dan is het vak zelf beter
#: dan een masker vol gaten.
MINIMALE_VULLING = 0.25


@dataclass(frozen=True, slots=True)
class Meting:
    """Wat er bij het samenstellen gemeten is, voor de logregel."""

    vakken: int
    inktvloer: int


def _oneven(waarde: int, *, minimaal: int = 3) -> int:
    """MaxFilter en MinFilter eisen een oneven venster."""
    return max(minimaal, waarde | 1)


def _papiermediaan(beeld: Image.Image) -> list[int] | None:
    """De mediaan van alles wat licht genoeg is om papier te zijn, per kanaal.

    Bewust de mediaan en niet de lichtste pixel: op een crème plaat is de
    lichtste pixel nog steeds wit, en juist daarom zag een percentiel het
    toonverschil drie keer niet.
    """
    rgb = beeld.convert("RGB")
    grijs = beeld.convert("L").getdata()
    banden = list(
        zip(
            *[p for p, g in zip(rgb.getdata(), grijs, strict=False) if g > BALLON_DREMPEL],
            strict=False,
        )
    )
    if not banden:
        return None
    return [sorted(band)[len(band) // 2] for band in banden]


def _naar_toon(model: Image.Image, doel: list[int] | None) -> Image.Image:
    """Het model naar deze papiertoon schalen."""
    bron = _papiermediaan(model)
    if bron is None or doel is None:
        return model
    tabellen: list[int] = []
    for van, naar in zip(bron, doel, strict=False):
        winst = (naar / van) if van else 1.0
        tabellen.extend(min(255, round(waarde * winst)) for waarde in range(256))
    return model.point(tabellen)


def _vorm(laag: Image.Image, dikte: int) -> Image.Image:
    """Het ballonvlak in deze uitsnede, met de letters opgevuld."""
    vorm = laag.convert("L").point(lambda p: 255 if p > BALLON_DREMPEL else 0)
    return vorm.filter(ImageFilter.MaxFilter(dikte)).filter(ImageFilter.MinFilter(dikte))


def _masker(origineel: Image.Image, model: Image.Image, *, breedte: int) -> Image.Image:
    """Waar het model mag schrijven, binnen één uitsnede.

    De vereniging van twee vormen. Alleen die van het origineel volstaat niet —
    het model schrijft buiten de oude ballon. Alleen die van het model ook
    niet: het oude tekstvlak moet juist bedekt worden.
    """
    dikte = _oneven(round(breedte * LETTERDIKTE_DEEL))
    samen = ImageChops.lighter(_vorm(origineel, dikte), _vorm(model, dikte))

    oppervlak = samen.width * samen.height
    vulling = (sum(samen.getdata()) / (255 * oppervlak)) if oppervlak else 0.0
    if vulling < MINIMALE_VULLING:
        samen = Image.new("L", samen.size, 255)
    else:
        samen = samen.filter(ImageFilter.MaxFilter(_oneven(round(breedte * OPREK_DEEL))))
    return samen.filter(ImageFilter.GaussianBlur(0.8))


def inktvloer(beeld: Image.Image) -> int:
    """Waar de inkt van deze scan ligt: het 2e percentiel."""
    waarden = sorted(beeld.convert("L").getdata())
    return waarden[int(len(waarden) * 0.02)] if waarden else 0


def zwartpunt(beeld: Image.Image, vanaf: int) -> Image.Image:
    """Het zwartpunt aantrekken; papier blijft wit, middentonen bijna.

    Een verwassen scan (Oishinbo meet 35, Shin-Chan 2) heeft lichtere inkt dan
    de plaat van het model, en dan valt een ingezette ballon op als een vlak
    met te veel contrast. Alleen het zwartpunt en niet de middentonen, want
    daar zit de rastertoon.

    Zelfkalibrerend: bij een scan die al zwart genoeg is gebeurt er niets.
    """
    if vanaf <= 2:
        return beeld
    tabel = [
        min(255, round((waarde - vanaf) * 255 / (255 - vanaf))) if waarde > vanaf else 0
        for waarde in range(256)
    ]
    return beeld.point(tabel * len(beeld.getbands()))


def stel_samen(
    origineel: Image.Image, hertekend: Image.Image, bubbles: list[Bubble]
) -> tuple[Image.Image, Meting]:
    """De tekening van het origineel met de ballonnen van het model erin.

    Per vak samengesteld en niet in één keer over de hele plaat: de papiertoon
    van het model kan lokaal afwijken, en één correctie voor de hele pagina
    liet een los tekstvak in de marge alsnog zichtbaar staan.
    """
    breed, hoog = origineel.size
    if hertekend.size != origineel.size:
        hertekend = hertekend.resize(origineel.size, Image.Resampling.LANCZOS)

    vloer = inktvloer(origineel)
    resultaat = zwartpunt(origineel.convert("RGB"), vloer)
    model_rgb = hertekend.convert("RGB")

    lucht_x, lucht_y = int(breed * VAKLUCHT), int(hoog * VAKLUCHT)
    gebruikt = 0
    for bubble in bubbles:
        kader = (
            max(0, int(bubble.x0 * breed) - lucht_x),
            max(0, int(bubble.y0 * hoog) - lucht_y),
            min(breed, int(bubble.x1 * breed) + lucht_x),
            min(hoog, int(bubble.y1 * hoog) + lucht_y),
        )
        if kader[2] <= kader[0] or kader[3] <= kader[1]:
            continue
        onder = resultaat.crop(kader)
        boven = _naar_toon(model_rgb.crop(kader), _papiermediaan(origineel.crop(kader)))
        masker = _masker(origineel.crop(kader), boven, breedte=breed)
        resultaat.paste(Image.composite(boven, onder, masker), kader)
        gebruikt += 1

    return resultaat, Meting(vakken=gebruikt, inktvloer=vloer)


def naar_webp(beeld: Image.Image, *, kwaliteit: int = 88) -> bytes:
    buffer = io.BytesIO()
    beeld.save(buffer, format="WEBP", quality=kwaliteit)
    return buffer.getvalue()


__all__ = ["Meting", "inktvloer", "naar_webp", "stel_samen", "zwartpunt"]
