"""Gemini als bubbel-vertaler (M8).

Eén multimodale aanroep per pagina doet detectie, uitlezen én vertalen. Dat
wijkt af van de oorspronkelijke opzet (YOLOv8 → crop → manga-ocr/PaddleOCR →
Gemini) en dat is met opzet:

* Het model ziet de **hele pagina**, niet losse uitgeknipte strings. Precies
  wat de architectuur wilde bereiken met "vertaling mét paginacontext" — een
  keten die strings doorgeeft, gooit die context juist weg.
* Geen ~700 MB aan modelgewichten (torch, manga-ocr, YOLO) in een image die op
  een N100 moet draaien.
* Empirisch nagemeten op een echte pagina uit de bibliotheek: alle acht
  tekstvlakken gevonden, tekst correct uitgelezen, vakken sluitend om de tekst.

De prijs is een netwerkverzoek per pagina en een API-sleutel. ``BubbleTranslator``
staat daarom los van deze implementatie: een lokale pipeline kan er later naast
zonder dat de rest van de app iets merkt.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from bookpal.ratelimit import RateLimiter
from bookpal.translate.base import (
    Bubble,
    BubbleKind,
    BubbleTranslator,
    PageResult,
    TranslationError,
)

logger = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Gemini geeft coördinaten terug als [ymin, xmin, ymax, xmax] op een schaal van
# 0..1000. Wij bewaren [x0, y0, x1, y1] op 0..1; hier wordt dat omgerekend.
_GEMINI_SCALE = 1000.0

_LANGUAGE_NAMES = {
    "nl": "Nederlands",
    "en": "Engels",
    "de": "Duits",
    "fr": "Frans",
    "es": "Spaans",
    "ja": "Japans",
}

# De eis over box_2d staat er niet voor de sier: zonder die zin kapte het model
# stelselmatig de laatste regel van een ballon af ("PHILOSO-" zonder "PHY.").
_PROMPT = """Je krijgt één pagina uit een stripverhaal.

Vind ELK tekstvlak: tekstballonnen, gedachteballonnen, bijschriften en
geluidseffecten. Sla tekst die in de tekening zelf hoort over (winkelborden op
de achtergrond, logo's), tenzij die duidelijk verhaal draagt.

box_2d moet ALLE regels van het tekstvlak RUIM omsluiten, van boven de eerste
regel tot ONDER de laatste regel, en van links van de breedste regel tot
rechts daarvan. Reken met een marge van een paar procent van de paginamaat
aan elke kant: een doos die net te klein is en een restje brontekst laat
staan, is een grotere fout dan een doos die iets te ruim is.

Geef per vlak:
- box_2d: [ymin, xmin, ymax, xmax], genormaliseerd naar 0-1000
- source: de tekst exact zoals hij er staat, op één regel
- translation: de vertaling naar {language}, in dezelfde toon en registers
- kind: "speech" | "thought" | "caption" of "sfx"
- bold: true als (een deel van) de brontekst duidelijk dikker/zwaarder staat
  dan de rest van diezelfde ballon — een nadruk binnen een zin, of een
  uitroep. Niet zomaar aanzetten omdat het lettertype al vet oogt: het gaat
  om een contrast BINNEN de pagina, niet om de stijl van het lettertype zelf.
- italic: true als de tekst duidelijk schuin staat ten opzichte van de rest
  van de lettering op deze pagina — een terzijde, een gedachte, een woord in
  een vreemde taal. Niet aanzetten voor gewone striplettering die toevallig
  wat handgeschreven of golvend oogt: dat is de norm, geen uitzondering.

Vertaal met de hele pagina als context, niet elke ballon los: een losse ballon
is vaak de tweede helft van een zin die in de vorige begon.

Antwoord met alleen een JSON-array."""


def _language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code.lower(), code)


def _to_bubble(item: dict[str, Any]) -> Bubble | None:
    """Eén vlak uit het antwoord. Geeft None terug als het onbruikbaar is —
    een half antwoord mag de rest van de pagina niet weggooien."""
    box = item.get("box_2d") or item.get("box")
    if not isinstance(box, list) or len(box) != 4:
        return None
    try:
        ymin, xmin, ymax, xmax = (float(value) / _GEMINI_SCALE for value in box)
    except (TypeError, ValueError):
        return None

    translation = str(item.get("translation") or "").strip()
    if not translation:
        return None

    try:
        kind = BubbleKind(str(item.get("kind", "speech")).lower())
    except ValueError:
        kind = BubbleKind.SPEECH

    # Het model haalt de hoeken wel eens door elkaar; sorteren is goedkoper dan
    # een vlak weggooien dat verder prima is.
    x0, x1 = sorted((xmin, xmax))
    y0, y1 = sorted((ymin, ymax))
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None

    return Bubble(
        x0=max(0.0, x0),
        y0=max(0.0, y0),
        x1=min(1.0, x1),
        y1=min(1.0, y1),
        source=str(item.get("source") or "").strip(),
        translation=translation,
        kind=kind,
        bold=bool(item.get("bold", False)),
        italic=bool(item.get("italic", False)),
    )


class GeminiBubbleTranslator(BubbleTranslator):
    provider = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-3-flash-preview",
        client: httpx.Client | None = None,
        rate: float = 1.0,
    ) -> None:
        if not api_key:
            raise TranslationError("geen Gemini-sleutel ingesteld (BOOKPAL_GEMINI_API_KEY)")
        self._api_key = api_key
        self._model = model
        # De sleutel in een header en niet in de URL: httpx logt elk verzoek
        # met volledige URL, en dan staat je sleutel in de containerlogs.
        self._client = client or httpx.Client(
            base_url=API_BASE,
            timeout=180.0,
            headers={"x-goog-api-key": api_key},
        )
        self._limiter = RateLimiter(rate)

    @property
    def model(self) -> str:
        return self._model

    def translate_page(self, image: bytes, *, media_type: str, target_lang: str) -> PageResult:
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": _PROMPT.format(language=_language_name(target_lang))},
                        {
                            "inline_data": {
                                "mime_type": media_type,
                                "data": base64.b64encode(image).decode("ascii"),
                            }
                        },
                    ]
                }
            ],
            # Temperatuur 0: bij een vertaling wil je hetzelfde antwoord als je
            # dezelfde pagina nog eens aanbiedt, niet elke keer een variant.
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }

        self._limiter.acquire()
        try:
            response = self._client.post(
                f"/models/{self._model}:generateContent",
                json=body,
            )
        except httpx.HTTPError as exc:
            raise TranslationError(f"Gemini niet bereikbaar: {exc}") from exc

        if response.status_code == 429:
            raise TranslationError("Gemini geeft rate limit aan; probeer het later opnieuw")
        if response.status_code >= 400:
            raise TranslationError(f"Gemini gaf {response.status_code}")

        return self._parse(response.json())

    def _parse(self, payload: dict[str, Any]) -> PageResult:
        candidates = payload.get("candidates") or []
        if not candidates:
            # Een lege kandidatenlijst betekent meestal dat een filter heeft
            # ingegrepen; dat is geen fout in onze code en geen reden om de
            # hele leessessie te laten struikelen.
            raise TranslationError("Gemini gaf geen antwoord terug")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts).strip()
        if not text:
            raise TranslationError("Gemini gaf een leeg antwoord")

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TranslationError("Gemini gaf geen geldige JSON") from exc

        # Soms komt de lijst verpakt in een object; beide vormen accepteren is
        # goedkoper dan een pagina laten mislukken om een omhulsel.
        if isinstance(parsed, dict):
            for key in ("bubbles", "items", "regions", "result"):
                if isinstance(parsed.get(key), list):
                    parsed = parsed[key]
                    break
        if not isinstance(parsed, list):
            raise TranslationError("Gemini gaf geen lijst tekstvlakken")

        bubbles = [
            bubble
            for item in parsed
            if isinstance(item, dict)
            if (bubble := _to_bubble(item)) is not None
        ]
        return PageResult(bubbles=bubbles, model=self._model)

    def close(self) -> None:
        self._client.close()
