"""De vertaling in het beeld bakken (M8).

Web en iOS tekenen hun eigen overlay met HTML respectievelijk SwiftUI, maar de
Kobo kan dat niet: die krijgt een kant-en-klare afbeelding. Dat is geen extra
werk maar juist de goedkope kant — die pagina's worden toch al server-side
klaargemaakt, dus er hoeft alleen tekst overheen.

Geen inpainting: een dekkend vlak met de vertaling erop. Dat is precies wat de
architectuur voor v1 voorschrijft, en het houdt het resultaat leesbaar op een
scherm dat maar zestien grijswaarden heeft.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from bookpal.translate.base import Bubble

# Kleine marge bovenop wat het model al zelf teruggeeft — de prompt vraagt
# het model inmiddels om ruim te meten, dus dit hoeft alleen de laatste paar
# pixels op te vangen, niet het hele werk te doen. Te veel hier stapelt op
# de marge die het model al toepast en maakt elk vlak nodeloos een sticker.
_PADDING = 0.006

_MIN_FONT = 9
_MAX_FONT = 40

# Gemini kan geen font namaken — glyphs tekenen kan het niet — maar het ziet
# wel of iets vet of cursief staat, en dat verdient een echt stripfont in
# plaats van een systeemlettertype. Comic Neue (SIL OFL 1.1) is een vrij te
# herdistribueren remake van Comic Sans; DejaVu is het vangnet als het pakket
# een keer ontbreekt (bijv. buiten de Docker-image).
_FONT_CANDIDATES: dict[tuple[bool, bool], tuple[str, ...]] = {
    (False, False): (
        "/usr/share/fonts/opentype/comic-neue/ComicNeue-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    (True, False): (
        "/usr/share/fonts/opentype/comic-neue/ComicNeue-Bold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    (False, True): (
        "/usr/share/fonts/opentype/comic-neue/ComicNeue-Italic.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    (True, True): (
        "/usr/share/fonts/opentype/comic-neue/ComicNeue-BoldItalic.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
}


def _load_font(
    size: int, *, bold: bool = False, italic: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES[(bold, italic)]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        # Let op de maat: ``load_default()`` zónder argument geeft een
        # bitmapfont van vaste grootte terug, en dan staat elke ballon in
        # hetzelfde priegelformaat. Mét maat is hij wel schaalbaar.
        return ImageFont.load_default(size)


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: float,
    *,
    hard_break: bool = False,
) -> list[str]:
    words: list[str] = []
    for word in text.split():
        words.extend(
            _break_long(draw, word, font, max_width) if hard_break else [word]
        )
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _break_long(
    draw: ImageDraw.ImageDraw,
    word: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: float,
) -> list[str]:
    """Hak een woord op dat zelfs alleen al te breed is.

    Zonder dit steekt "BEDRIJFSFILOSOFIE." dwars over de rand van zijn ballon:
    regelafbreking op spaties helpt niet als er geen spatie in zit.
    """
    if max_width <= 0 or draw.textlength(word, font=font) <= max_width:
        return [word]

    pieces: list[str] = []
    current = ""
    for char in word:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            pieces.append(current)
            current = char
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    box_w: float,
    box_h: float,
    *,
    bold: bool = False,
    italic: bool = False,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, list[str], float]:
    """Zoek de grootste lettergrootte waarop de tekst nog in het vlak past.

    Twee rondes, en die volgorde is het hele punt. Eerst met hele woorden:
    liever een maat kleiner dan "BESCHIKBA/AR." middenin een woord afbreken.
    Pas als de tekst dan nog nergens past — een lang woord in een smal vlak —
    mag er hard gehakt worden.

    Van groot naar klein in plaats van binair zoeken: het bereik is klein en zo
    blijft dit leesbaar.
    """
    for hard_break in (False, True):
        for size in range(_MAX_FONT, _MIN_FONT - 1, -1):
            font = _load_font(size, bold=bold, italic=italic)
            lines = _wrap(draw, text, font, box_w, hard_break=hard_break)
            if not lines:
                continue
            line_height = size * 1.2
            if len(lines) * line_height > box_h:
                continue
            # Ook de breedte controleren, en niet alleen erop vertrouwen dat
            # _wrap het wel regelt: zonder hard afbreken krijgt een woord dat
            # langer is dan het vlak een eigen regel en steekt het er dwars
            # overheen. Dat was zichtbaar op de eerste ingebakken pagina.
            if max(draw.textlength(line, font=font) for line in lines) > box_w:
                continue
            return font, lines, line_height

    font = _load_font(_MIN_FONT, bold=bold, italic=italic)
    return font, _wrap(draw, text, font, box_w, hard_break=True), _MIN_FONT * 1.2


def draw_bubbles(
    image: Image.Image, bubbles: list[Bubble], *, boxes: bool = True
) -> Image.Image:
    """Teken de vertalingen over een pagina heen.

    De modus blijft wat hij was. Dat is niet vrijblijvend: een Kobo-profiel
    levert geditherde grijswaarden op, en die naar RGB tillen gooit precies het
    werk weg waar dat profiel voor bestaat.
    """
    if not bubbles:
        return image

    canvas = image if image.mode in ("RGB", "L") else image.convert("RGB")
    white: int | tuple[int, ...] = 255 if canvas.mode == "L" else (255, 255, 255)
    black: int | tuple[int, ...] = 0 if canvas.mode == "L" else (0, 0, 0)
    _draw_onto(
        ImageDraw.Draw(canvas), canvas.size, bubbles, white=white, black=black, boxes=boxes
    )
    return canvas


def _draw_onto(
    draw: ImageDraw.ImageDraw,
    size: tuple[int, int],
    bubbles: list[Bubble],
    *,
    white: int | tuple[int, ...],
    black: int | tuple[int, ...],
    boxes: bool = True,
) -> None:
    """Het tekenwerk zelf, gedeeld door de ingebakken pagina en de losse laag —
    zodat de Kobo en de web-app niet uit elkaar kunnen gaan lopen.

    ``boxes=False`` laat het dekkende vlakje weg: dat is voor de hybride stand,
    waar het beeldmodel de ballon al heeft leeggeveegd en er dus niets meer
    afgedekt hoeft te worden.
    """
    width, height = size
    pad = _PADDING * width if boxes else 0.0

    for bubble in bubbles:
        if not bubble.translation.strip():
            continue
        x0 = max(0.0, bubble.x0 * width - pad)
        y0 = max(0.0, bubble.y0 * height - pad)
        x1 = min(float(width), bubble.x1 * width + pad)
        y1 = min(float(height), bubble.y1 * height + pad)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue

        if boxes:
            draw.rectangle((x0, y0, x1, y1), fill=white, outline=black, width=1)

        # Striplettering staat traditioneel in kapitalen; een vertaling in
        # onderkast daartussen valt meteen op als "ingeplakt". We vragen dit
        # niet aan het model — het staat al in de brontekst.
        text = bubble.translation.upper() if bubble.upper else bubble.translation
        font, lines, line_height = _fit(
            draw, text, x1 - x0 - 4, y1 - y0 - 4, bold=bubble.bold, italic=bubble.italic
        )
        text_height = len(lines) * line_height
        cursor = y0 + max(2.0, (y1 - y0 - text_height) / 2)
        for line in lines:
            line_width = draw.textlength(line, font=font)
            draw.text(
                (x0 + max(2.0, (x1 - x0 - line_width) / 2), cursor),
                line,
                fill=black,
                font=font,
            )
            cursor += line_height


def render_layer(size: tuple[int, int], bubbles: list[Bubble], *, boxes: bool = True) -> bytes:
    """Alleen de tekstvlakken, op een doorzichtige achtergrond (PNG).

    Waarom naast ``bake``: zo blijft de pagina zelf één gedeelde afbeelding.
    Inbakken maakt van elke pagina twee volledige plaatjes — één met en één
    zonder vertaling — die allebei apart door de cache en over de lijn moeten,
    en het hercodeert die pagina bij elke aanvraag opnieuw. Een losse laag is
    een fractie van die bytes, is één keer te renderen, en de client zet 'm er
    met gewone CSS overheen. Aan- en uitzetten is dan een kwestie van een laag
    tonen of verbergen in plaats van de pagina opnieuw ophalen.

    Ook zonder JavaScript te gebruiken: BookPal Lite stapelt twee ``img``'s met
    ``position: absolute``, en dat doet de Kobo-browser gewoon.
    """
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    if not bubbles:
        return _to_png(layer)

    draw = ImageDraw.Draw(layer)
    _draw_onto(
        draw, size, bubbles, white=(255, 255, 255, 255), black=(0, 0, 0, 255), boxes=boxes
    )
    return _to_png(layer)


def _to_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def bake(
    data: bytes, bubbles: list[Bubble], *, media_type: str, boxes: bool = True
) -> bytes:
    """Zelfde bytes in, bytes met vertaling eruit — in hetzelfde formaat."""
    with Image.open(BytesIO(data)) as source:
        source.load()
        baked = draw_bubbles(source, bubbles, boxes=boxes)

    buffer = BytesIO()
    baked.save(buffer, format=_format_for(media_type))
    return buffer.getvalue()


def _format_for(media_type: str) -> str:
    return {
        "image/webp": "WEBP",
        "image/jpeg": "JPEG",
        "image/png": "PNG",
    }.get(media_type, "WEBP")
