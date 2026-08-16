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
zware model kwam er in alle vier de tests goed doorheen. De metingen staan in
`docs/architectuur.md` onder "De drie vertaalstanden".
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
- Gebruik per vlak dezelfde letterstijl en grootte als het origineel.
- Zet de vertaling ALTIJD horizontaal, van links naar rechts, en verdeel hem
  over meerdere regels binnen de ballon. Ook als het origineel verticaal van
  boven naar beneden loopt, zoals in Japanse ballonnen: die richting hoort bij
  het Japanse schrift, niet bij de ballon. Losse letters onder elkaar gestapeld
  zijn onleesbaar.
- De ballon zelf houdt zijn vorm en plek. Past de vertaling er horizontaal niet
  fatsoenlijk in, maak de letters dan kleiner — niet de ballon groter.
- Verander verder NIETS: geen tekening, geen arcering, geen kleuren, geen
  paneelindeling, geen ballonvormen. Een zwart-wit pagina blijft zwart-wit.

Geef alleen de bewerkte pagina terug, op exact dezelfde afmeting als deze."""


# Waarom de opdracht begint met wat er níét mag veranderen: een model dat
# vrijelijk mag inkleuren, componeert de pagina opnieuw. Door de omtrekken,
# paneelranden en ballonnen als anker te benoemen blijft de tekening staan.
# Gemeten over twee pagina's legde dit de uitlijning van 0,840 op 0,886 en
# 0,861 op 0,868 (overlap met het origineel, zonder enige correctie achteraf),
# en leverde het meteen meer kleur op. Zie recolour.py voor wat er daarna
# gebeurt: hiervan gebruiken we alleen de kleur.
_COLOUR_PROMPT = """Dit is een zwart-witte pagina uit een stripverhaal.

Schilder er aquarel in, en houd daarbij de tekening exact op zijn plek.

Wat onaangetast blijft, pixel voor pixel:
- De omtrekken van alle figuren, gezichten en voorwerpen.
- De randen van elk paneel, en de vorm en plek van elke tekstballon.
- Alle tekst, in dezelfde letters op dezelfde plek. Vertaal niets en herschrijf
  niets.

Wat je toevoegt — aquarel, zoals de kleurpagina's die mangaka zelf schilderen:
- Doorschijnende wassingen, geen egale vlakken. Binnen één vlak mag de kleur
  verlopen van vol naar bijna niets, en het wit van het papier schijnt eronder
  door.
- Zachte randen, en kleuren die in elkaar mogen lopen waar ze elkaar raken.
- Kies de kleur die het onderwerp in het echt heeft. Bladeren zijn groen,
  bloemen en kleding mogen uitgesproken kleurrijk zijn, eten ziet er eetbaar
  uit. Verf het niet allemaal in bruin en grijs.
- De arcering mag opgaan in de wassing; de omtrekken zelf niet. Die blijven
  scherp, met de verf eronder.
- Tekstballonnen en de papierrand blijven wit. Papier is papier en inkt is inkt.
- Houd het rustig genoeg om te blijven lezen. Een overdreven verzadigde pagina
  leest slechter dan het zwart-witte origineel.

Verschuif, herschaal of herteken niets. Iemand legt jouw pagina straks precies
over deze heen, en dan moet elke lijn samenvallen.

Geef alleen de geschilderde pagina terug, op exact dezelfde afmeting als deze."""


def build_image_request(image: bytes, media_type: str, target_lang: str) -> dict[str, Any]:
    """Het verzoek om deze pagina te hertekenen mét vertaling.

    Losgetrokken van de klasse zodat de batch exact hetzelfde stuurt; twee
    plekken met elk hun eigen opbouw lopen vroeg of laat uit elkaar.
    """
    language = _LANGUAGE_NAMES.get(target_lang.lower(), target_lang)
    return _request(image, media_type, _PROMPT.format(language=language))


def build_colour_request(image: bytes, media_type: str) -> dict[str, Any]:
    """Het verzoek om deze pagina in te kleuren."""
    return _request(image, media_type, _COLOUR_PROMPT)


def _request(image: bytes, media_type: str, prompt: str) -> dict[str, Any]:
    return {
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


def read_image(payload: dict[str, Any], original: bytes, *, keep_gray: bool) -> bytes:
    """Het beeld uit een antwoord halen en terugbrengen naar onze maat."""
    return _match_original(_extract_image(payload), original, keep_gray=keep_gray)


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
        return self._send(
            build_image_request(image, media_type, target_lang), image, keep_gray=True
        )

    def colorise_page(self, image: bytes, *, media_type: str) -> bytes:
        """Dezelfde pagina, ingekleurd.

        Dit is geen vertaling en hoort er ook niet mee te concurreren: het
        resultaat wordt apart bewaard, zodat een ingekleurde pagina nooit in de
        plaats komt van een vertaalde. Wel houden we grijs níét terug — dat is
        precies wat er hier moet veranderen.
        """
        return self._send(build_colour_request(image, media_type), image, keep_gray=False)

    def _send(self, body: dict[str, Any], original: bytes, *, keep_gray: bool) -> bytes:
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

        return read_image(response.json(), original, keep_gray=keep_gray)

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


def _match_original(produced: bytes, original: bytes, *, keep_gray: bool = True) -> bytes:
    """Naar de verhouding van het origineel, maar nooit naar beneden.

    Het model werkt in zijn eigen resolutie en levert soms een net andere maat
    terug. Zonder correctie past de vertaalde pagina niet meer op de plek van de
    originele, en dat merk je pas als de lezer ernaast staat — vandaar dat de
    *verhouding* van het origineel altijd wint.

    De *maat* niet. Bij het hertekenen tekent het model de hele plaat, dus zijn
    resolutie ís de resolutie van je pagina. Gemeten is Oishinbo 750x1080 en One
    Piece 780x1200, terwijl het model rond de 1024 breed teruggeeft: dat naar
    750 terugbrengen gooide bij elke betaalde pagina de helft van de lijnen weg.
    Daarom schalen we alleen nog op, nooit meer af.

    Voor het inkleuren maakt dit niets uit: daar komt het lijnwerk uit het
    origineel en gebruiken we van het model alleen de kleur (zie recolour.py),
    dus een grotere plaat zou daar alleen een grotere waas zijn.

    ``keep_gray`` uit bij het inkleuren: daar is het veranderen van grijs naar
    kleur juist de bedoeling, en terugzetten zou het hele werk ongedaan maken.
    """
    with Image.open(BytesIO(original)) as source:
        source.load()
        size = source.size
        was_gray = keep_gray and _is_grayscale(source)

    try:
        with Image.open(BytesIO(produced)) as opened:
            opened.load()
            result: Image.Image = opened
            doel = _doelmaat(size, result.size)
            if result.size != doel:
                result = result.resize(doel, Image.Resampling.LANCZOS)
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


def _doelmaat(origineel: tuple[int, int], geleverd: tuple[int, int]) -> tuple[int, int]:
    """De verhouding van het origineel, op de grootste breedte van de twee.

    Losgetrokken van ``_match_original`` omdat dit het enige rekenwerk erin is
    en het precies het soort regel is waar je een tabelletje van wilt kunnen
    testen.
    """
    breed_o, hoog_o = origineel
    if breed_o <= 0 or hoog_o <= 0:
        return geleverd
    breedte = max(breed_o, geleverd[0])
    return breedte, max(1, round(breedte * hoog_o / breed_o))


def _is_grayscale(image: Image.Image, *, sample: int = 64) -> bool:
    """Was de bronpagina in wezen zwart-wit?

    Op een verkleinde kopie, want dit hoeft alleen te weten of er kleur ín zit,
    niet precies hoeveel.
    """
    if image.mode in ("L", "1"):
        return True
    small = image.convert("RGB").resize((sample, sample), Image.Resampling.BILINEAR)
    # tobytes en niet getdata: dat laatste is in nieuwere Pillow afgeschaft, en
    # drie bytes per pixel uitlezen komt op hetzelfde neer.
    raw = small.tobytes()
    for start in range(0, len(raw), 3):
        red, green, blue = raw[start], raw[start + 1], raw[start + 2]
        if abs(red - green) > 12 or abs(green - blue) > 12 or abs(red - blue) > 12:
            return False
    return True
