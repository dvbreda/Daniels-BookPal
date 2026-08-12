"""Vertalingen blijvend bewaren naast de collectie (M8).

Een vertaling kost geld — bij de beeldstanden tientallen centen per pagina. Die
mag daarom niet alleen in de database staan: een database opnieuw opbouwen (of
een scan die misgaat) zou betekenen dat je opnieuw betaalt voor werk dat al
gedaan is. Alles wat een vertaler oplevert komt hier op schijf te staan, in een
mappenstructuur die je zelf kunt lezen en kopiëren:

    <sidecar>/<serie>/<hoofdstuk>/p0007.json          tekstvlakken
    <sidecar>/<serie>/<hoofdstuk>/p0007-image_pro.webp  hele pagina, duur model

De collectie zelf is read-only aangekoppeld (`:ro` in compose — BookPal hoort
niet in je eigen mappen te schrijven), dus dit staat bewust in een eigen map en
niet naast de cbz. De structuur is wél op naam, zodat je aan de map kunt zien
waar iets bij hoort in plaats van aan een database-id.

De database blijft de snelle index; de schijf is de waarheid. Bij het vertalen
wordt eerst hier gekeken, dus een bestaand bestand bespaart een aanroep.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from bookpal.config import settings
from bookpal.models import Book, Series
from bookpal.translate.modes import TranslateMode

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text: str, *, fallback: str, limit: int = 120) -> str:
    cleaned = _UNSAFE.sub("", text).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:limit].strip() or fallback


def chapter_dir(series: Series | None, book: Book) -> Path:
    series_name = safe_name(series.title if series else "", fallback=f"serie-{book.series_id}")
    # Het nummer erbij: twee hoofdstukken van dezelfde serie heten bij
    # scanlations regelmatig allebei gewoon naar de auteur.
    label = " ".join(part for part in (book.number, book.title) if part).strip()
    chapter = safe_name(label, fallback=f"boek-{book.id}")
    return settings.sidecar_dir / series_name / chapter


def page_stem(page_index: int) -> str:
    # Nullen ervoor zodat een `ls` in leesvolgorde staat.
    return f"p{page_index:04d}"


def json_path(series: Series | None, book: Book, page_index: int, lang: str) -> Path:
    return chapter_dir(series, book) / f"{page_stem(page_index)}-{lang}.json"


def image_path(
    series: Series | None, book: Book, page_index: int, lang: str, mode: TranslateMode
) -> Path:
    return chapter_dir(series, book) / f"{page_stem(page_index)}-{lang}-{mode.value}.webp"


def _write(path: Path, data: bytes) -> None:
    """Via een tijdelijk bestand: een half geschreven vertaling die als
    'bestaat al' wordt gezien, is erger dan geen vertaling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{threading.get_ident()}.tmp")
    temp.write_bytes(data)
    temp.replace(path)


def is_writable() -> bool:
    """Kan er daadwerkelijk bewaard worden?

    Niet vanzelfsprekend: de map komt uit een volume, en als die verkeerd
    aangekoppeld staat is hij van root terwijl de server als een gewone
    gebruiker draait. Het schrijven zelf faalt zacht — een mislukte sidecar mag
    een gelukte vertaling niet ongedaan maken — en juist daarom moet dit ergens
    zichtbaar zijn in plaats van alleen in een logregel.
    """
    probe = settings.sidecar_dir / ".schrijftest"
    try:
        settings.sidecar_dir.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return False
    return True


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Een kapot bestand mag het lezen niet blokkeren; we maken 'm gewoon
        # opnieuw aan.
        logger.warning("sidecar %s is onleesbaar; wordt genegeerd", path)
        return None
    return loaded if isinstance(loaded, dict) else None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        _write(path, json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError as exc:
        # Niet kunnen bewaren is vervelend maar niet fataal: de vertaling zelf
        # is al gelukt en staat in de database.
        logger.warning("sidecar %s niet kunnen schrijven: %s", path, exc)


def read_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        logger.warning("sidecar %s niet kunnen lezen: %s", path, exc)
        return None


def write_bytes(path: Path, data: bytes) -> None:
    try:
        _write(path, data)
    except OSError as exc:
        logger.warning("sidecar %s niet kunnen schrijven: %s", path, exc)
