"""Een metadata-bestandje naast elk boek.

Wat BookPal over een boek weet staat in de database, en die is weg zodra je
opnieuw begint. Een sidecar zet het náást het bestand, waar het thuishoort:
verhuis je map naar een andere machine, dan verhuist wat je erover wist mee, en
een verse installatie vindt het bij de eerste scan gewoon terug.

Het formaat is bewust saai: json, één bestand per boek, ``<bestandsnaam>.bookpal.json``.
Te openen in een teksteditor, met de hand te corrigeren, en te negeren door elk
ander programma dat je map inleest.

Wat erin gaat is precies wat niet uit het bestand zelf te halen is:

* **Meerdere titels.** Dezelfde aflevering heet anders in het Engels, het
  Japans en op de omslag. Eén veld dwingt je te kiezen; een kaartje per taal
  niet.
* **Een omslag.** Als "pagina 1" niet de juiste is, staat hier welke wel — of
  het plaatje zelf, als het ergens anders vandaan komt.
* **Waar het vandaan komt.** Een titel die jij hebt ingetypt hoort zwaarder te
  wegen dan een die we bij een bron ophaalden, en die weer zwaarder dan wat de
  bestandsnaam suggereerde.

Wat er níét in gaat is je leesvoortgang. Die hoort bij jou en niet bij het
bestand, staat op meerdere apparaten tegelijk en verandert de hele tijd — dat is
werk voor de database.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Achter de bestandsnaam geplakt, niet in plaats van de extensie: zo blijft
#: zichtbaar bij welk bestand het hoort, ook als er een cbz en een pdf van
#: hetzelfde deel naast elkaar staan.
SUFFIX = ".bookpal.json"

#: Meegeschreven zodat een latere versie weet wat hij voor zich heeft.
VERSION = 1

#: Waar een waarde vandaan komt, van zwaar naar licht. Een handmatige titel
#: hoort niet overschreven te worden door de eerstvolgende bron-ronde.
ORDER = ("manual", "source", "embedded", "filename")

# Een omslag als data-URI is handig maar niet gratis: 763 hoofdstukken met elk
# een plaatje van een halve MB is een halve GB aan json. Dit is ruim genoeg voor
# een miniatuur en krap genoeg om dat te voorkomen.
MAX_COVER_BYTES = 256 * 1024


@dataclass
class Sidecar:
    """Wat er over één boek naast het bestand staat."""

    # Titels per taalcode: {"en": "Herring Roe", "ja": "数の子"}. De sleutel
    # "" is de titel zonder taal — wat er op het bestand stond.
    titles: dict[str, str] = field(default_factory=dict)
    series: str | None = None
    number: str | None = None
    volume: str | None = None
    authors: list[str] = field(default_factory=list)
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    # Welke pagina de omslag is, als het niet de eerste is.
    cover_page: int | None = None
    # Of het plaatje zelf, als het ergens anders vandaan komt dan uit het boek.
    cover_data: str | None = None
    # Per veld waar het vandaan komt: {"titles": "source", "cover_page": "manual"}.
    origin: dict[str, str] = field(default_factory=dict)
    updated_at: str | None = None

    def title(self, prefer: str | None = None) -> str | None:
        """De titel om te tonen.

        Eerst de taal die je vroeg, dan de titel zonder taal, dan wat er is.
        Bewust geen "eerste alfabetisch": dat zou per boek een andere taal
        kunnen kiezen en dat leest als een fout.
        """
        for sleutel in (prefer, "", "en"):
            if sleutel is not None and self.titles.get(sleutel):
                return self.titles[sleutel]
        return next(iter(self.titles.values()), None)

    def wins_over(self, veld: str, herkomst: str) -> bool:
        """Mag ``herkomst`` schrijven wat er nu in ``veld`` staat?

        Gelijke herkomst mag: een tweede ronde bij dezelfde bron is een
        actualisering, geen conflict.
        """
        huidig = self.origin.get(veld)
        if huidig is None:
            return True
        try:
            return ORDER.index(herkomst) <= ORDER.index(huidig)
        except ValueError:
            return True

    def set_title(self, titel: str, *, lang: str = "", herkomst: str = "filename") -> bool:
        """Zet een titel, als de herkomst dat mag. Geeft terug of er iets veranderde."""
        if not titel or not self.wins_over("titles", herkomst):
            return False
        if self.titles.get(lang) == titel:
            return False
        self.titles[lang] = titel
        self.origin["titles"] = herkomst
        return True

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"version": VERSION}
        for sleutel, waarde in (
            ("titles", self.titles),
            ("series", self.series),
            ("number", self.number),
            ("volume", self.volume),
            ("authors", self.authors),
            ("summary", self.summary),
            ("tags", self.tags),
            ("cover_page", self.cover_page),
            ("cover_data", self.cover_data),
            ("origin", self.origin),
        ):
            # Lege velden weglaten: een sidecar hoort leesbaar te blijven, niet
            # een muur van nulls te zijn.
            if waarde not in (None, {}, []):
                data[sleutel] = waarde
        data["updated_at"] = self.updated_at or datetime.now(UTC).isoformat(timespec="seconds")
        return data


def path_for(book_path: Path) -> Path:
    """Waar de sidecar van dit bestand staat."""
    return book_path.with_name(book_path.name + SUFFIX)


def read(book_path: Path) -> Sidecar | None:
    """Lees de sidecar naast dit bestand, als hij er is.

    Een stukgelopen of half geschreven bestand is geen reden om een scan te
    laten mislukken: dan doen we alsof hij er niet is en melden het in het log.
    """
    pad = path_for(book_path)
    if not pad.is_file():
        return None
    try:
        ruw = json.loads(pad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("sidecar %s is onleesbaar: %s", pad.name, exc)
        return None
    if not isinstance(ruw, dict):
        return None

    titels = ruw.get("titles")
    if isinstance(titels, str):
        # Toegeeflijk bij het lezen: iemand die dit met de hand invult schrijft
        # eerder "titles": "Iets" dan een kaartje met taalcodes.
        titels = {"": titels}
    return Sidecar(
        titles={str(k): str(v) for k, v in (titels or {}).items() if v},
        series=ruw.get("series"),
        number=ruw.get("number"),
        volume=ruw.get("volume"),
        authors=[str(item) for item in ruw.get("authors") or []],
        summary=ruw.get("summary"),
        tags=[str(item) for item in ruw.get("tags") or []],
        cover_page=ruw.get("cover_page") if isinstance(ruw.get("cover_page"), int) else None,
        cover_data=ruw.get("cover_data"),
        origin={str(k): str(v) for k, v in (ruw.get("origin") or {}).items()},
        updated_at=ruw.get("updated_at"),
    )


def write(book_path: Path, sidecar: Sidecar) -> Path | None:
    """Schrijf de sidecar naast het bestand.

    Eerst ernaast en dan omzetten, zodat een afgebroken schrijfronde nooit een
    half json-bestand achterlaat dat de volgende scan niet kan lezen.

    Faalt zacht: een map waar niet in geschreven mag worden is een reden om het
    over te slaan, niet om de scan te laten klappen.
    """
    pad = path_for(book_path)
    sidecar.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
    tijdelijk = pad.with_name(pad.name + ".deel")
    try:
        tijdelijk.write_text(
            json.dumps(sidecar.to_json(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tijdelijk.replace(pad)
    except OSError as exc:
        logger.warning("sidecar %s schrijven mislukt: %s", pad.name, exc)
        tijdelijk.unlink(missing_ok=True)
        return None
    return pad


def cover_bytes(sidecar: Sidecar) -> bytes | None:
    """De omslag uit de sidecar, als er een plaatje in zit."""
    waarde = sidecar.cover_data
    if not waarde:
        return None
    if waarde.startswith("data:"):
        _kop, _scheiding, rest = waarde.partition(",")
        waarde = rest
    try:
        return base64.b64decode(waarde, validate=True)
    except (ValueError, TypeError) as exc:
        logger.warning("omslag in sidecar is geen geldige base64: %s", exc)
        return None


def encode_cover(data: bytes, media_type: str = "image/webp") -> str | None:
    """Maak van een plaatje een data-URI voor in de sidecar."""
    if len(data) > MAX_COVER_BYTES:
        logger.info(
            "omslag van %s bytes gaat niet in een sidecar (grens is %s)",
            len(data),
            MAX_COVER_BYTES,
        )
        return None
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


__all__ = [
    "MAX_COVER_BYTES",
    "ORDER",
    "SUFFIX",
    "VERSION",
    "Sidecar",
    "cover_bytes",
    "encode_cover",
    "path_for",
    "read",
    "write",
]
