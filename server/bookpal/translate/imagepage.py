"""Een hele pagina laten hertekenen mét vertaling (M8).

Het beeldmodel krijgt de pagina en geeft dezelfde pagina terug met Nederlandse
tekst in de ballonnen. Dat leest mooier dan een vlakje over het origineel, maar
het is een generatief model: het hertekent de pagina, en dan kan er van alles
mis gaan waar geen foutmelding bij hoort.

Wat we tegen die stilzwijgende fouten doen:

* **Afmeting terugzetten.** Het model levert zijn eigen canonieke resolutie
  (bijvoorbeeld 848x1256 voor een pagina van 810x1200). Gemeten op twee
  pagina's is de
  compositie na terugschalen 0 tot 1 pixel verschoven, dus terugschalen is
  genoeg — maar het moet wel gebeuren, anders klopt geen enkele coördinaat meer.
* **Grijswaarden bewaken.** Een zwart-wit manga hoort zwart-wit terug te komen;
  het model geeft altijd RGB terug.
* **Niet stilletjes vervangen.** Het origineel blijft gewoon staan en is één
  tik verderop — bij deze standen is dat de enige controle die de lezer heeft.

Wat we er *niet* tegen kunnen doen: controleren of de vertaling klopt. In onze
tests liet het snelle model op drie van de vier pagina's iets liggen (een
onvertaalde ballon, een verzonnen regel, en één keer een gewijzigd bedrag op een
menukaart). Dat laatste is het gevaarlijkst omdat het er correct uitziet. Het
zware model kwam er in alle vier de tests goed doorheen. Zie
`docs/architectuur.md` voor de metingen.
"""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from typing import Any

import httpx
from PIL import Image

from bookpal.ratelimit import RateLimiter
from bookpal.translate.base import TranslationError
from bookpal.translate.gemini import _LANGUAGE_NAMES, API_BASE

logger = logging.getLogger(__name__)

_PROMPT = """Dit is een pagina uit een stripverhaal.

Vervang ALLE tekst in elke tekstballon, elk bijschrift en elk geluidseffect door
een goede vertaling naar {language}, met de hele pagina als context: een losse
ballon is vaak de tweede helft van een zin die in de vorige begon.

Regels:
- Vertaal ELKE ballon. Een ballon in de oorspronkelijke taal laten staan is een
  fout, ook een korte.
- Verzin niets bij. Voeg geen tekst, ballonnen of regels toe die er niet staan.
- Neem getallen, bedragen en eigennamen exact over. Een bedrag of naam
  veranderen is de ergste fout die je kunt maken, want die valt niet op.
- Laat tekst die bij de tekening hoort (winkelborden, opschriften in een andere
  taal) staan zoals hij is.
- Gebruik per vlak dezelfde letterstijl, grootte en uitlijning als het origineel.
- Verander verder NIETS: geen tekening, geen arcering, geen kleuren, geen
  paneelindeling, geen ballonvormen. Een zwart-wit pagina blijft zwart-wit.

Geef alleen de bewerkte pagina terug, op exact dezelfde afmeting als deze."""



class GeminiPageTranslator:
    """Levert een hele vertaalde pagina in plaats van losse tekstvlakken."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        client: httpx.Client | None = None,
        rate: float = 0.5,
    ) -> None:
        if not api_key:
            raise TranslationError("geen Gemini-sleutel ingesteld (BOOKPAL_GEMINI_API_KEY)")
        self._api_key = api_key
        self._model = model
        # Ruimer dan de tekststand: dit duurt 10-30 seconden per pagina en
        # loopt nooit in een wachtrij die er honderden achter elkaar doet.
        # De sleutel in een header en niet in de URL: httpx logt elk verzoek
        # met volledige URL, en dan staat je sleutel in de containerlogs.
        self._client = client or httpx.Client(
            base_url=API_BASE,
            timeout=300.0,
            headers={"x-goog-api-key": api_key},
        )
        self._limiter = RateLimiter(rate)

    @property
    def model(self) -> str:
        return self._model

    def translate_page(self, image: bytes, *, media_type: str, target_lang: str) -> bytes:
        language = _LANGUAGE_NAMES.get(target_lang.lower(), target_lang)
        return self._run(image, media_type, _PROMPT.format(language=language))

    def _run(self, image: bytes, media_type: str, prompt: str) -> bytes:
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": media_type,
                                "data": base64.b64encode(image).decode("ascii"),
                            }
                        },
                    ]
                }
            ]
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

        produced = _extract_image(response.json())
        return _match_original(produced, image)

    def close(self) -> None:
        self._client.close()


def _extract_image(payload: dict[str, Any]) -> bytes:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise TranslationError("Gemini gaf geen antwoord terug")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    for part in parts:
        blob = part.get("inlineData") or part.get("inline_data")
        if blob and blob.get("data"):
            try:
                return base64.b64decode(blob["data"])
            except (ValueError, TypeError) as exc:
                raise TranslationError("Gemini gaf een onleesbare afbeelding") from exc
    raise TranslationError("Gemini gaf geen afbeelding terug")


def _match_original(produced: bytes, original: bytes) -> bytes:
    """Terug naar de afmeting en het kleurkarakter van het origineel.

    Het model werkt in zijn eigen resolutie, dus zonder dit past de vertaalde
    pagina niet meer op de plek van de originele — en dat merk je pas als de
    lezer ernaast staat.
    """
    with Image.open(BytesIO(original)) as source:
        source.load()
        size = source.size
        was_gray = _is_grayscale(source)

    try:
        with Image.open(BytesIO(produced)) as opened:
            opened.load()
            result: Image.Image = opened
            if result.size != size:
                result = result.resize(size, Image.Resampling.LANCZOS)
            if was_gray:
                # Een zwart-wit manga hoort zwart-wit terug te komen; het model
                # levert altijd RGB, en een grijze pagina als kleurenplaat
                # bewaren kost bytes zonder iets toe te voegen.
                result = result.convert("L")
            elif result.mode not in ("RGB", "L"):
                result = result.convert("RGB")

            buffer = BytesIO()
            result.save(buffer, format="WEBP", quality=88)
            return buffer.getvalue()
    except OSError as exc:
        raise TranslationError(f"vertaalde pagina kon niet verwerkt worden: {exc}") from exc


def _is_grayscale(image: Image.Image, *, sample: int = 64) -> bool:
    """Was de bronpagina in wezen zwart-wit?

    Op een verkleinde kopie, want dit hoeft alleen te weten of er kleur ín zit,
    niet precies hoeveel.
    """
    if image.mode in ("L", "1"):
        return True
    small = image.convert("RGB").resize((sample, sample), Image.Resampling.BILINEAR)
    for pixel in list(small.getdata()):
        red, green, blue = pixel[0], pixel[1], pixel[2]
        if abs(red - green) > 12 or abs(green - blue) > 12 or abs(red - blue) > 12:
            return False
    return True
