"""Pagina's en covers klaarmaken voor een specifiek apparaat, met schijfcache.

Het dure werk gebeurt één keer. Daarna is een pagina-aanvraag een bestandslezing,
ook als de bron een cbr is die uitgepakt moest worden of een pdf die gerenderd
moest worden.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from bookpal.config import settings
from bookpal.formats import BookFile, book_cache
from bookpal.formats.base import RawPage, UnsupportedOperation
from bookpal.images import adjust
from bookpal.images.adjust import Adjustments
from bookpal.images.profiles import ImageProfile

logger = logging.getLogger(__name__)

# Pillow weigert standaard extreem grote afbeeldingen als bescherming tegen
# decompressiebommen. Stripscans zijn soms legitiem groot, dus we zetten de
# grens hoger in plaats van uit.
Image.MAX_IMAGE_PIXELS = 300_000_000

_prune_lock = threading.Lock()
_writes_since_prune = 0
PRUNE_EVERY = 200


@dataclass(slots=True)
class RenderedImage:
    data: bytes
    media_type: str
    from_cache: bool


def _cache_key(
    source_id: str,
    index: int,
    profile: ImageProfile,
    adjustments: Adjustments | None = None,
) -> str:
    raw = (
        f"{source_id}|{index}|{profile.name}|{profile.max_width}x{profile.max_height}|"
        f"{profile.format}|{profile.quality}|{profile.grayscale}|{profile.dither_levels}"
        f"{(adjustments or Adjustments()).cache_key}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(key: str, profile: ImageProfile) -> Path:
    # Twee niveaus fanout: één map met tienduizenden bestanden wordt op een NAS
    # merkbaar traag.
    return settings.cache_dir / profile.name / key[:2] / key[2:4] / f"{key}{profile.extension}"


def to_eink_gray(image: Image.Image, levels: int) -> Image.Image:
    """Naar grijstinten met Floyd-Steinberg-dithering.

    E-ink toont maar 16 grijswaarden. Zonder dithering krijg je zichtbare banden
    in luchten en schaduwvlakken; mét dithering blijft een kleurenpagina op een
    zwart-wit paneel leesbaar.
    """
    gray = image.convert("L")
    if levels >= 256:
        return gray
    step = 255 // (levels - 1)
    palette: list[int] = []
    for i in range(levels):
        value = min(255, i * step)
        palette.extend([value, value, value])
    palette.extend([0] * (768 - len(palette)))

    palette_image = Image.new("P", (1, 1))
    palette_image.putpalette(palette)
    quantised = gray.convert("RGB").quantize(
        palette=palette_image, dither=Image.Dither.FLOYDSTEINBERG
    )
    return quantised.convert("L")


def process_image(
    data: bytes, profile: ImageProfile, adjustments: Adjustments | None = None
) -> bytes:
    with Image.open(BytesIO(data)) as source:
        # Sommige scans dragen een EXIF-rotatie; zonder dit staat de pagina scheef.
        image = ImageOps.exif_transpose(source) or source
        image.load()

        # Bijsnijden vóór het verkleinen: anders schaal je eerst een witrand
        # mee en gooi je daarna alsnog pixels weg die je net betaald hebt.
        if adjustments is not None and adjustments.active:
            image = adjust.apply(image, adjustments)

        if profile.max_width or profile.max_height:
            max_w = profile.max_width or image.width
            max_h = profile.max_height or image.height
            scale = min(max_w / image.width, max_h / image.height, 1.0)
            # Nooit opschalen: dat kost bytes zonder detail toe te voegen.
            if scale < 1.0:
                image = image.resize(
                    (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                    Image.Resampling.LANCZOS,
                )

        if profile.grayscale:
            image = (
                to_eink_gray(image, profile.dither_levels)
                if profile.dither_levels
                else image.convert("L")
            )
        elif image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        buffer = BytesIO()
        if profile.format == "webp":
            image.save(buffer, format="WEBP", quality=profile.quality, method=4)
        elif profile.format == "jpeg":
            image.save(buffer, format="JPEG", quality=profile.quality, optimize=True)
        else:
            image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def _store(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Via een tijdelijk bestand, zodat een gelijktijdige lezer nooit een half
    # geschreven pagina te pakken krijgt.
    temp = path.with_suffix(path.suffix + f".{threading.get_ident()}.tmp")
    temp.write_bytes(data)
    temp.replace(path)
    _maybe_prune()


def render_page(
    book: BookFile,
    index: int,
    profile: ImageProfile,
    *,
    source_id: str,
    adjustments: Adjustments | None = None,
) -> RenderedImage:
    """Lever pagina ``index`` in het gevraagde profiel."""
    key = _cache_key(source_id, index, profile, adjustments)
    path = _cache_path(key, profile)
    if path.exists():
        return RenderedImage(path.read_bytes(), profile.media_type, from_cache=True)

    # De breedte-hint laat een pdf meteen op maat renderen in plaats van groot
    # renderen en daarna verkleinen.
    raw = book.get_page(index, target_width=profile.max_width)
    data = process_image(raw.data, profile, adjustments)
    _store(path, data)
    return RenderedImage(data, profile.media_type, from_cache=False)


def render_cover(book: BookFile, profile: ImageProfile, *, source_id: str) -> RenderedImage | None:
    key = _cache_key(source_id, -1, profile)
    path = _cache_path(key, profile)
    if path.exists():
        return RenderedImage(path.read_bytes(), profile.media_type, from_cache=True)

    try:
        raw: RawPage | None = book.cover()
    except (UnsupportedOperation, IndexError, OSError) as exc:
        logger.warning("geen omslag voor %s: %s", source_id, exc)
        return None
    if raw is None:
        return None

    data = process_image(raw.data, profile)
    _store(path, data)
    return RenderedImage(data, profile.media_type, from_cache=False)


def render_remote_cover(url: str, profile: ImageProfile, *, source_id: str) -> RenderedImage:
    """De officiële omslag van een bron (M5/M7), door dezelfde pipeline als
    elke andere afbeelding — dus ook grijswaarden en dithering voor de Kobo.

    Eén keer ophalen: de cache-sleutel bevat de URL zelf, dus een gewijzigde
    omslag bij de bron krijgt vanzelf een nieuwe sleutel in plaats van dat hij
    de oude blijft tonen.
    """
    key = _cache_key(source_id, -1, profile)
    path = _cache_path(key, profile)
    if path.exists():
        return RenderedImage(path.read_bytes(), profile.media_type, from_cache=True)

    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UnsupportedOperation(f"omslag niet op te halen: {exc}") from exc

    data = process_image(response.content, profile)
    _store(path, data)
    return RenderedImage(data, profile.media_type, from_cache=False)


def open_source(path: Path) -> BookFile:
    return book_cache.get(path)


def source_id_for(path: Path) -> str:
    """Cachesleutel die vanzelf verandert als het bestand verandert."""
    stat = path.stat()
    return f"{path}:{stat.st_mtime}:{stat.st_size}"


def _maybe_prune() -> None:
    global _writes_since_prune
    with _prune_lock:
        _writes_since_prune += 1
        if _writes_since_prune < PRUNE_EVERY:
            return
        _writes_since_prune = 0
    prune_cache()


def cache_size_bytes() -> int:
    return sum(p.stat().st_size for p in settings.cache_dir.rglob("*") if p.is_file())


def prune_cache(max_bytes: int | None = None) -> int:
    """Gooi de oudst gebruikte bestanden weg tot de cache weer past.

    Geeft het aantal verwijderde bestanden terug.
    """
    limit = max_bytes if max_bytes is not None else settings.cache_max_mb * 1024 * 1024
    if limit <= 0:
        return 0

    files = [
        (p.stat().st_atime, p.stat().st_size, p)
        for p in settings.cache_dir.rglob("*")
        if p.is_file()
    ]
    total = sum(size for _, size, _ in files)
    if total <= limit:
        return 0

    removed = 0
    for _atime, size, path in sorted(files):
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
        if total <= limit:
            break
    return removed


def clear_cache() -> None:
    import shutil

    shutil.rmtree(settings.cache_dir, ignore_errors=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
