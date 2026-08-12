"""Internet Archive als bron.

Naast MangaDex, dat vooral scanlations per hoofdstuk heeft, staat op
archive.org veel als hele delen: één item met een cbz per volume. Dat vult
elkaar aan — waar de vertaling ophoudt, staat het origineel soms hier.

De API is publiek en gedocumenteerd (advancedsearch voor zoeken, ``/metadata``
voor de inhoud van een item, ``/download`` voor de bestanden), dus dit blijft
binnen het uitgangspunt van ``Source``: geen scrapers.

Twee dingen die deze bron anders maken dan MangaDex:

* **Een item is geen reeks maar een verzameling bestanden.** Dezelfde inhoud
  staat er vaak vijf keer in — cbz, epub, pdf, een jp2-zip en een versneutelde
  epub. Daaruit kiezen we er één per deel, anders krijg je vijf "hoofdstukken"
  die allemaal hetzelfde zijn.
* **Er zijn geen losse pagina-URL's.** Je haalt het hele bestand op. Online
  bladeren zonder downloaden kan hier dus niet, en dat zegt ``page_urls`` ook.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

from bookpal.metadata.filename import normalise_number, parse_filename
from bookpal.ratelimit import RateLimiter
from bookpal.sources.base import ChapterInfo, CoverInfo, SearchResult, Source, SourceError

API_BASE = "https://archive.org"
USER_AGENT = "DanielsBookPal/0.1 (persoonlijke bibliotheek; +https://github.com/dvbreda)"

# Welke bestandsvormen we kunnen lezen, van beste naar minst beste. Een cbz is
# wat we willen: pagina's als beeld, precies waar de lezer op gebouwd is. Een
# pdf kan ook, en een epub is voor een strip meestal de slechtste van de drie.
_PREFERENCE = (".cbz", ".cbr", ".pdf", ".epub")

# Hier trappen we niet in: een jp2-zip is de ruwe scan van de bewaardienst zelf
# (traag en enorm), en een lcp-epub zit achter drm.
_SKIP = re.compile(
    r"(_jp2\.zip|_lcp\.epub|_encrypted\.pdf|_daisy\.zip|_djvu\.txt)$", re.IGNORECASE
)

# Alleen tekstmateriaal: dezelfde zoekterm levert anders ook de tv-serie op.
_MEDIATYPE = "texts"

# archive.org gebruikt drieletterige taalcodes.
_LANGUAGES = {
    "en": "eng",
    "ja": "jpn",
    "nl": "dut",
    "de": "ger",
    "fr": "fre",
    "es": "spa",
    "it": "ita",
    "pt": "por",
    "ko": "kor",
    "zh": "chi",
}


def _first(value: Any) -> str | None:
    """archive.org geeft velden soms als lijst en soms als losse waarde."""
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value not in (None, "") else None


def _year(doc: dict[str, Any]) -> int | None:
    ruw = _first(doc.get("year")) or _first(doc.get("date"))
    if not ruw:
        return None
    match = re.search(r"\d{4}", ruw)
    return int(match.group()) if match else None


#: Items die je alleen kunt lénen. Het Internet Archive scant boeken voor
#: bibliotheken en leent ze één tegelijk uit; de bestanden zijn dan versleuteld
#: en niet op te halen. Ze staan wél gewoon in de zoekresultaten, dus zonder dit
#: onderscheid abonneer je je op iets wat nooit binnenkomt.
_LENDING = ("inlibrary", "printdisabled")


def _restricted(doc: dict[str, Any]) -> bool:
    collecties = doc.get("collection") or []
    if isinstance(collecties, str):
        collecties = [collecties]
    if any(naam in _LENDING for naam in collecties):
        return True
    return str(doc.get("access-restricted-item") or "").lower() == "true"


def _to_result(doc: dict[str, Any]) -> SearchResult:
    identifier = str(doc.get("identifier"))
    maker = _first(doc.get("creator"))
    return SearchResult(
        ref=identifier,
        title=_first(doc.get("title")) or identifier,
        description=_first(doc.get("description")),
        year=_year(doc),
        # Er is geen apart veld voor "kan ik dit ophalen", dus het staat waar je
        # het ziet: op de plek waar MangaDex "ongoing" zet.
        status="alleen te leen" if _restricted(doc) else None,
        url=f"{API_BASE}/details/{identifier}",
        # Elk item heeft een afbeeldingsdienst; die kiest zelf de omslag.
        cover_url=f"{API_BASE}/services/img/{identifier}",
        authors=[maker] if maker else [],
        languages=[
            code
            for code, drieletterig in _LANGUAGES.items()
            if drieletterig in (doc.get("language") or [])
        ],
    )


def _readable_files(files: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per deel het beste bestand.

    Gegroepeerd op de naam zonder extensie: "v01 c01-14.cbz" en dezelfde als
    epub en pdf zijn hetzelfde deel. Zonder deze stap wordt elk deel drie tot
    vijf keer een hoofdstuk.
    """
    per_deel: dict[str, dict[str, Any]] = {}
    for bestand in files:
        naam = str(bestand.get("name", ""))
        if _SKIP.search(naam):
            continue
        suffix = Path(naam).suffix.lower()
        if suffix not in _PREFERENCE:
            continue
        sleutel = Path(naam).stem
        huidig = per_deel.get(sleutel)
        if huidig is None or _PREFERENCE.index(suffix) < _PREFERENCE.index(
            Path(str(huidig["name"])).suffix.lower()
        ):
            per_deel[sleutel] = bestand
    return per_deel


def _chapter(identifier: str, bestand: dict[str, Any]) -> ChapterInfo:
    naam = str(bestand["name"])
    stem = Path(naam).stem
    parsed = parse_filename(stem)
    return ChapterInfo(
        # Item én bestand, want een ref moet in zijn eentje te downloaden zijn.
        ref=f"{identifier}/{naam}",
        number=parsed.number,
        volume=parsed.volume,
        # De bestandsnaam zelf, niet wat de parser overhoudt: bij "v01 c01-14 +
        # Omake" blijft daar "14 + Omake" van over, en dat zegt minder dan de
        # hele naam. Deze bron levert hele delen, geen genummerde hoofdstukken
        # met een eigen titel.
        title=stem,
        language="",
        page_count=None,
        published_at=None,
    )


class ArchiveOrgSource(Source):
    type = "archiveorg"

    def __init__(self, client: httpx.Client | None = None, *, rate: float = 2.0) -> None:
        self._client = client or httpx.Client(
            base_url=API_BASE,
            headers={"User-Agent": USER_AGENT},
            timeout=60.0,
            follow_redirects=True,
        )
        # Rustig aan: dit is een archief dat door vrijwilligers betaald wordt,
        # geen dienst die op ons verkeer zit te wachten.
        self._limiter = RateLimiter(rate)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._limiter.acquire()
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"Internet Archive niet bereikbaar: {exc}") from exc
        if response.status_code >= 400:
            raise SourceError(f"Internet Archive gaf {response.status_code} op {path}")
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise SourceError(f"Internet Archive gaf geen JSON op {path}") from exc
        return payload

    def search(
        self, query: str, *, limit: int = 20, language: str | None = None
    ) -> list[SearchResult]:
        voorwaarden = [f'({query})', f"mediatype:{_MEDIATYPE}"]
        if language:
            drieletterig = _LANGUAGES.get(language, language)
            voorwaarden.append(f"language:{drieletterig}")
        payload = self._get(
            "/advancedsearch.php",
            {
                "q": " AND ".join(voorwaarden),
                "fl[]": [
                    "identifier",
                    "title",
                    "year",
                    "date",
                    "creator",
                    "language",
                    "collection",
                ],
                "rows": limit,
                "page": 1,
                "output": "json",
            },
        )
        docs = (payload.get("response") or {}).get("docs") or []
        return [_to_result(doc) for doc in docs]

    def detail(self, ref: str) -> SearchResult:
        payload = self._get(f"/metadata/{ref}")
        metadata = payload.get("metadata")
        if not metadata:
            raise SourceError(f"item {ref} niet gevonden bij Internet Archive")
        metadata = {**metadata, "identifier": ref}
        return _to_result(metadata)

    def chapters(self, ref: str, *, language: str = "en") -> list[ChapterInfo]:
        """De delen van dit item.

        ``language`` doet hier niets: een item heeft één taal, die je bij het
        zoeken al gekozen hebt. Het staat in de handtekening omdat elke bron
        dezelfde vorm heeft.
        """
        payload = self._get(f"/metadata/{ref}")
        if _restricted(payload.get("metadata") or {}):
            raise SourceError(
                "dit item is alleen te leen bij het Internet Archive, niet op te halen: "
                "de bestanden zijn versleuteld"
            )
        bestanden = payload.get("files") or []
        gekozen = _readable_files(bestanden)
        gevonden = [_chapter(ref, bestand) for bestand in gekozen.values()]
        gevonden.sort(
            key=lambda chapter: (
                normalise_number(chapter.volume),
                normalise_number(chapter.number),
                chapter.title or "",
            )
        )
        return gevonden

    def page_urls(self, chapter_ref: str, *, data_saver: bool = False) -> list[str]:
        raise SourceError(
            "Internet Archive levert hele bestanden, geen losse pagina's; haal het deel op"
        )

    def covers(self, ref: str, *, limit: int = 100) -> list[CoverInfo]:
        """Eén omslag per item; per deel heeft archive.org er geen."""
        return [CoverInfo(url=f"{API_BASE}/services/img/{ref}")]

    def chapter_count(self, ref: str, *, language: str = "en") -> int:
        return len(self.chapters(ref))

    def download(self, chapter_ref: str, target: Path, *, data_saver: bool = False) -> Path:
        """Haal dit deel op.

        Naar een tijdelijke naam en pas daarna omzetten: een half binnengehaald
        deel van tientallen MB mag de scanner nooit als geldig archief
        tegenkomen.
        """
        if "/" not in chapter_ref:
            raise SourceError(f"{chapter_ref} wijst niet naar een bestand in een item")
        # De naam bij de bron bepaalt de extensie: een pdf onder de naam ".cbz"
        # is geen zip en opent nergens.
        suffix = Path(chapter_ref).suffix.lower()
        if suffix and suffix != target.suffix.lower():
            target = target.with_suffix(suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")
        self._limiter.acquire()
        try:
            with self._client.stream("GET", f"/download/{chapter_ref}") as response:
                if response.status_code >= 400:
                    raise SourceError(
                        f"Internet Archive gaf {response.status_code} voor {chapter_ref}"
                    )
                with partial.open("wb") as uit:
                    for blok in response.iter_bytes(1024 * 1024):
                        uit.write(blok)
            partial.replace(target)
        except httpx.HTTPError as exc:
            raise SourceError(f"ophalen mislukt: {exc}") from exc
        finally:
            partial.unlink(missing_ok=True)
        return target

    def close(self) -> None:
        self._client.close()
