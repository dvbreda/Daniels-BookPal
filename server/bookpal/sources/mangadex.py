"""MangaDex als bron (M5).

Gebruikt de publieke API (https://api.mangadex.org). Twee dingen die de
architectuur als aandachtspunt noemt en hier terugkomen:

* **Rate limits.** ~5 req/s per IP, strenger op ``/at-home/server/``. Beide
  krijgen een eigen limiter, en de at-home-limiter is bewust trager.
* **Eigen User-Agent.** Een dienst mag kunnen zien wie er langskomt.

``originalLanguage`` uit de API voedt stap 2 van de herkomst-keten (ontwerp 1),
en ``links.mal`` levert de MyAnimeList-koppeling die M7 anders met de hand zou
moeten leggen.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import httpx

from bookpal.sources.base import ChapterInfo, SearchResult, Source, SourceError
from bookpal.sources.ratelimit import RateLimiter

API_BASE = "https://api.mangadex.org"
USER_AGENT = "DanielsBookPal/0.1 (persoonlijke bibliotheek; +https://github.com/dvbreda)"

# Welke van de vele titelvarianten tonen we? Engels als dat er is, anders de
# geromaniseerde Japanse, anders wat er ook maar in zit.
_TITLE_PREFERENCE = ("en", "ja-ro", "ja")

# De trackers die M7 kent, met de sleutel zoals MangaDex hem noemt.
_TRACKER_LINKS = {"mal": "mal", "al": "anilist"}


def _pick_title(attributes: dict[str, Any]) -> str:
    titles: dict[str, str] = attributes.get("title") or {}
    for language in _TITLE_PREFERENCE:
        if titles.get(language):
            return str(titles[language])
    if titles:
        return str(next(iter(titles.values())))
    for alt in attributes.get("altTitles") or []:
        if alt:
            return str(next(iter(alt.values())))
    return "(zonder titel)"


def _pick_description(attributes: dict[str, Any]) -> str | None:
    descriptions: dict[str, str] = attributes.get("description") or {}
    return descriptions.get("en") or (next(iter(descriptions.values()), None))


def _to_result(item: dict[str, Any]) -> SearchResult:
    attributes = item.get("attributes") or {}
    links = attributes.get("links") or {}
    tracker_ids = {
        ours: str(links[theirs]) for theirs, ours in _TRACKER_LINKS.items() if links.get(theirs)
    }
    return SearchResult(
        ref=str(item["id"]),
        title=_pick_title(attributes),
        description=_pick_description(attributes),
        year=attributes.get("year"),
        status=attributes.get("status"),
        original_language=attributes.get("originalLanguage"),
        tracker_ids=tracker_ids,
    )


def _chapter_sort_key(chapter: ChapterInfo) -> tuple[float, float]:
    def as_number(value: str | None) -> float:
        try:
            return float(value) if value is not None else float("inf")
        except ValueError:
            return float("inf")

    return (as_number(chapter.volume), as_number(chapter.number))


class MangaDexSource(Source):
    type = "mangadex"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        rate: float = 4.0,
        at_home_rate: float = 1.0,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=API_BASE,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )
        self._limiter = RateLimiter(rate)
        # Apart en trager: hier is MangaDex expliciet strenger.
        self._at_home_limiter = RateLimiter(at_home_rate)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        limiter = self._at_home_limiter if path.startswith("/at-home/") else self._limiter
        limiter.acquire()
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"MangaDex niet bereikbaar: {exc}") from exc
        if response.status_code == 429:
            raise SourceError("MangaDex geeft rate limit aan; probeer het later opnieuw")
        if response.status_code >= 400:
            raise SourceError(f"MangaDex gaf {response.status_code} op {path}")
        payload: dict[str, Any] = response.json()
        if payload.get("result") == "error":
            raise SourceError(f"MangaDex meldde een fout op {path}")
        return payload

    def search(self, query: str, *, limit: int = 20) -> list[SearchResult]:
        payload = self._get("/manga", {"title": query, "limit": limit})
        return [_to_result(item) for item in payload.get("data", [])]

    def detail(self, ref: str) -> SearchResult:
        payload = self._get(f"/manga/{ref}")
        data = payload.get("data")
        if not data:
            raise SourceError(f"serie {ref} niet gevonden bij MangaDex")
        return _to_result(data)

    def chapters(self, ref: str, *, language: str = "en") -> list[ChapterInfo]:
        """Alle hoofdstukken, paginerend want de feed geeft er maximaal 500."""
        found: list[ChapterInfo] = []
        offset = 0
        page_size = 100
        while True:
            payload = self._get(
                f"/manga/{ref}/feed",
                {
                    "translatedLanguage[]": language,
                    "limit": page_size,
                    "offset": offset,
                    "order[volume]": "asc",
                    "order[chapter]": "asc",
                },
            )
            batch = payload.get("data", [])
            for item in batch:
                attributes = item.get("attributes") or {}
                # Externe hoofdstukken wijzen naar een andere site; die kunnen
                # we niet ophalen, dus tonen we ze ook niet als beschikbaar.
                if attributes.get("externalUrl") or attributes.get("isUnavailable"):
                    continue
                found.append(
                    ChapterInfo(
                        ref=str(item["id"]),
                        number=attributes.get("chapter"),
                        volume=attributes.get("volume"),
                        title=attributes.get("title"),
                        language=attributes.get("translatedLanguage", language),
                        page_count=attributes.get("pages"),
                        published_at=attributes.get("publishAt"),
                    )
                )
            total = int(payload.get("total", 0))
            offset += page_size
            if offset >= total or not batch:
                break
        return sorted(found, key=_chapter_sort_key)

    def page_urls(self, chapter_ref: str, *, data_saver: bool = False) -> list[str]:
        payload = self._get(f"/at-home/server/{chapter_ref}")
        base_url = payload.get("baseUrl")
        chapter = payload.get("chapter") or {}
        chapter_hash = chapter.get("hash")
        if not base_url or not chapter_hash:
            raise SourceError(f"MangaDex gaf geen pagina's voor hoofdstuk {chapter_ref}")
        quality = "data-saver" if data_saver else "data"
        names = chapter.get("dataSaver" if data_saver else "data") or []
        return [f"{base_url}/{quality}/{chapter_hash}/{name}" for name in names]

    def download(self, chapter_ref: str, target: Path, *, data_saver: bool = False) -> Path:
        """Eén hoofdstuk als cbz.

        Schrijft eerst naar een tijdelijk bestand: een half binnengehaald
        hoofdstuk mag de scanner nooit als geldig archief tegenkomen.
        """
        urls = self.page_urls(chapter_ref, data_saver=data_saver)
        if not urls:
            raise SourceError(f"hoofdstuk {chapter_ref} heeft geen pagina's")

        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_STORED) as archive:
                for index, url in enumerate(urls, start=1):
                    self._at_home_limiter.acquire()
                    try:
                        response = self._client.get(url)
                        response.raise_for_status()
                    except httpx.HTTPError as exc:
                        raise SourceError(f"pagina {index} ophalen mislukt: {exc}") from exc
                    suffix = Path(url).suffix or ".jpg"
                    archive.writestr(f"{index:03d}{suffix}", response.content)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        return target

    def close(self) -> None:
        self._client.close()
