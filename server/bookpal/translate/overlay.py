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

# Marge rondom een tekstvlak, als fractie van de paginabreedte. Het model komt
# soms een paar pixels tekort aan de onderkant; zonder deze marge piept er een
# streepje van de oorspronkelijke tekst onderuit.
_PADDING = 0.004

_MIN_FONT = 9
_MAX_FONT = 40

# DejaVu zit in Pillow's wheel, dus dit werkt zonder extra systeempakket.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
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
    draw: ImageDraw.ImageDraw, text: str, box_w: float, box_h: float
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
            font = _load_font(size)
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

    font = _load_font(_MIN_FONT)
    return font, _wrap(draw, text, font, box_w, hard_break=True), _MIN_FONT * 1.2


def draw_bubbles(image: Image.Image, bubbles: list[Bubble]) -> Image.Image:
    """Teken de vertalingen over een pagina heen.

    De modus blijft wat hij was. Dat is niet vrijblijvend: een Kobo-profiel
    levert geditherde grijswaarden op, en die naar RGB tillen gooit precies het
    werk weg waar dat profiel voor bestaat.
    """
    if not bubbles:
        return image

    canvas = image if image.mode in ("RGB", "L") else image.convert("RGB")
    white: int | tuple[int, int, int] = 255 if canvas.mode == "L" else (255, 255, 255)
    black: int | tuple[int, int, int] = 0 if canvas.mode == "L" else (0, 0, 0)
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size
    pad = _PADDING * width

    for bubble in bubbles:
        if not bubble.translation.strip():
            continue
        x0 = max(0.0, bubble.x0 * width - pad)
        y0 = max(0.0, bubble.y0 * height - pad)
        x1 = min(float(width), bubble.x1 * width + pad)
        y1 = min(float(height), bubble.y1 * height + pad)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue

        draw.rectangle((x0, y0, x1, y1), fill=white, outline=black, width=1)

        font, lines, line_height = _fit(draw, bubble.translation, x1 - x0 - 4, y1 - y0 - 4)
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

    return canvas


def bake(data: bytes, bubbles: list[Bubble], *, media_type: str) -> bytes:
    """Zelfde bytes in, bytes met vertaling eruit — in hetzelfde formaat."""
    with Image.open(BytesIO(data)) as source:
        source.load()
        baked = draw_bubbles(source, bubbles)

    buffer = BytesIO()
    baked.save(buffer, format=_format_for(media_type))
    return buffer.getvalue()


def _format_for(media_type: str) -> str:
    return {
        "image/webp": "WEBP",
        "image/jpeg": "JPEG",
        "image/png": "PNG",
    }.get(media_type, "WEBP")
