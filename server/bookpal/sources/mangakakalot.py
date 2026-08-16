"""MangaKakalot als bron.

De eerste bron zonder API: alles komt uit de HTML van de site zelf. Dat brengt
twee dingen mee die de andere bronnen niet hebben.

**Hij breekt zodra de opmaak verandert.** Een API is een afspraak, een pagina
niet. Daarom faalt elke stap hier hard en met naam en toenaam ("geen
hoofdstukken gevonden — opmaak waarschijnlijk veranderd") in plaats van een
lege lijst terug te geven. Een lege lijst zou als "deze reeks heeft geen
hoofdstukken" worden gelezen, en dan verdwijnt er stilletjes werk uit je
bibliotheek.

**Zoeken kan niet.** De zoekpagina bouwt zichzelf in de browser op, dus er
staat geen resultaat in de HTML om te lezen. In plaats daarvan lost ``search``
een slug op: je plakt de URL van de reeks (of alleen het laatste stuk daarvan)
en krijgt die reeks terug als hij bestaat. Voor deze bron is dat ook de
natuurlijke weg — je komt hier met een link, niet met een zoekterm.

Rustiger dan MangaDex (1 verzoek per seconde): dit zijn hele HTML-pagina's en
er is geen gepubliceerde limiet om je aan te houden, dus dan is voorzichtig de
enige nette stand. De User-Agent zegt gewoon wie er langskomt — dat werd
geaccepteerd, dus er is geen reden ons voor te doen als browser.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from lxml import html as lxml_html

from bookpal.ratelimit import RateLimiter
from bookpal.sources.base import ChapterInfo, SearchResult, Source, SourceError

SITE_BASE = "https://mangakakalot.fun"
USER_AGENT = "DanielsBookPal/0.1 (persoonlijke bibliotheek; +https://github.com/dvbreda)"

#: Een slug is het laatste stuk van /manga/<slug>. Streng, want hij wordt een
#: URL: alleen kleine letters, cijfers en streepjes.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9\-]*$")

#: `/chapter/<slug>/chapter-89.5` -> "89.5". Ook "chapter-0" hoort erbij, en
#: soms staat er nog iets achter (`-vol-3`), dat we laten vallen.
_NUMMER = re.compile(r"chapter-([0-9]+(?:\.[0-9]+)?)", re.I)

#: Vanaf het eerste teken in een niet-Latijns schrift tot het eind. De h1 zet
#: de geromaniseerde en de originele titel zonder scheidingsteken naast elkaar;
#: dit knipt daar tussen. Bewust op schrift en niet op "niet-ASCII", want een
#: accent in een Latijnse titel hoort gewoon te blijven staan.
_ROMAJI_TOT = re.compile(r"\s*[　-鿿가-힯Ѐ-ӿऀ-ॿ＀-￯].*$")

#: De omschrijving begint bij deze bron altijd met "<titel> Manga:". Op de
#: titel matchen ging mis zodra die zelf werd opgeschoond, dus op de vorm.
_MANGA_VOORVOEGSEL = re.compile(r"^.{0,120}?\bmanga:\s*", re.I)

#: Waarboven een "hoofdstuknummer" geen hoofdstuk meer kan zijn. Zie de
#: toelichting in `chapters`; ruim boven de langste bestaande reeks.
_HOOGSTE_HOOFDSTUK = 10_000.0


def _slug_uit(ref: str) -> str:
    """De slug uit een losse slug of een volledige URL.

    Beide toegestaan omdat je hier met een link binnenkomt: plakken hoort te
    werken zonder dat je eerst zelf het laatste stuk eruit knipt.
    """
    tekst = ref.strip().rstrip("/")
    if "://" in tekst:
        delen = [deel for deel in urlparse(tekst).path.split("/") if deel]
        # /manga/<slug> en /chapter/<slug>/... leveren allebei de slug.
        if len(delen) >= 2 and delen[0] in ("manga", "chapter"):
            tekst = delen[1]
        elif delen:
            tekst = delen[-1]
    tekst = tekst.lower()
    if not _SLUG.match(tekst):
        raise SourceError(f"{ref!r} ziet er niet uit als een reeks van MangaKakalot")
    return tekst


class MangaKakalotSource(Source):
    type = "mangakakalot"

    def __init__(self, *, client: httpx.Client | None = None, rate: float = 1.0) -> None:
        self._client = client or httpx.Client(
            base_url=SITE_BASE,
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        self._limiter = RateLimiter(rate)

    # MARK: - Ophalen

    def _pagina(self, pad: str) -> lxml_html.HtmlElement:
        self._limiter.acquire()
        try:
            antwoord = self._client.get(pad)
        except httpx.HTTPError as exc:
            raise SourceError(f"MangaKakalot niet bereikbaar: {exc}") from exc
        if antwoord.status_code == 404:
            raise SourceError(f"niet gevonden bij MangaKakalot: {pad}")
        if antwoord.status_code >= 400:
            raise SourceError(f"MangaKakalot gaf {antwoord.status_code} op {pad}")
        return lxml_html.fromstring(antwoord.text)

    @staticmethod
    def _meta(boom: lxml_html.HtmlElement, eigenschap: str) -> str | None:
        gevonden = boom.xpath(f'//meta[@property="{eigenschap}"]/@content')
        return str(gevonden[0]).strip() if gevonden else None

    # MARK: - De interface

    def search(
        self, query: str, *, limit: int = 20, language: str | None = None
    ) -> list[SearchResult]:
        """Zoekt niet, maar lost een slug of URL op.

        De zoekpagina van de site vult zichzelf in de browser, dus er valt
        niets te lezen. Wie hier komt heeft een link, en die werkt wél.
        """
        try:
            slug = _slug_uit(query)
        except SourceError:
            return []
        try:
            return [self.detail(slug)]
        except SourceError:
            return []

    def detail(self, ref: str) -> SearchResult:
        slug = _slug_uit(ref)
        boom = self._pagina(f"/manga/{slug}")

        koppen = boom.xpath("//h1//text()")
        titel = " ".join(" ".join(koppen).split())
        if not titel:
            raise SourceError(
                f"geen titel gevonden voor {slug} — "
                "opmaak van MangaKakalot waarschijnlijk veranderd"
            )
        # De h1 stapelt alle taalvarianten achter elkaar: eerst met
        # puntkomma's ertussen, maar de geromaniseerde en de originele naam
        # staan zónder scheidingsteken naast elkaar ("Hirayasumi ひらやすみ").
        # In een bibliotheek wil je er één, en dat is de eerste.
        titel = titel.split(";")[0].strip()
        titel = _ROMAJI_TOT.sub("", titel).strip() or titel

        omschrijving = self._meta(boom, "og:description")
        if omschrijving:
            omschrijving = _MANGA_VOORVOEGSEL.sub("", omschrijving).strip() or None

        return SearchResult(
            ref=slug,
            title=titel,
            description=omschrijving or None,
            cover_url=self._meta(boom, "og:image"),
            url=f"{SITE_BASE}/manga/{slug}",
            # De site zegt niet in welke taal iets staat en levert in de
            # praktijk Engelse scanlations. Dat gokken we niet: leeg laten is
            # eerlijker dan een taal verzinnen waar de herkomst-keten op gaat
            # bouwen.
            languages=[],
        )

    def chapters(self, ref: str, *, language: str = "en") -> list[ChapterInfo]:
        slug = _slug_uit(ref)
        boom = self._pagina(f"/manga/{slug}")

        # Alleen links van déze reeks: de pagina heeft ook een zijbalk met
        # hoofdstukken van heel andere series, en die hoorden er een keer
        # gewoon tussen te staan.
        gezien: dict[str, ChapterInfo] = {}
        for anker in boom.xpath("//a[@href]"):
            pad = urlparse(str(anker.get("href"))).path
            delen = [deel for deel in pad.split("/") if deel]
            if len(delen) < 3 or delen[0] != "chapter" or delen[1] != slug:
                continue
            staart = delen[2]
            treffer = _NUMMER.search(staart)
            nummer = treffer.group(1) if treffer else None
            # Onmogelijke nummers overslaan. De pagina bevat naast de echte
            # hoofdstukken een reeks links als `chapter-961707.5` — gemeten 71
            # van de 163 bij Hirayasumi — die een 302 geven in plaats van een
            # pagina, en die de leesvolgorde volledig omgooiden. Het is een
            # vuistregel en geen contract, maar wel een veilige: er bestaat
            # geen reeks met tienduizend hoofdstukken, en `rel="nofollow"` als
            # signaal bleek onbruikbaar omdat de site dat ook op echte
            # hoofdstukken zet (dan bleven er 51 van de 92 over).
            if nummer is not None and float(nummer) > _HOOGSTE_HOOFDSTUK:
                continue
            chapter_ref = f"{slug}/{staart}"
            if chapter_ref in gezien:
                continue
            gezien[chapter_ref] = ChapterInfo(
                ref=chapter_ref,
                number=nummer,
                volume=None,
                title=None,
                language=language,
                # Geen paginatelling zonder de hoofdstukpagina op te halen, en
                # dat zou honderden verzoeken zijn voor een getal dat de
                # scanner straks zelf uit het cbz leest.
                page_count=None,
            )

        if not gezien:
            raise SourceError(
                f"geen hoofdstukken gevonden voor {slug} — "
                "opmaak van MangaKakalot waarschijnlijk veranderd"
            )

        def sleutel(info: ChapterInfo) -> tuple[float, str]:
            try:
                return (float(info.number), info.ref) if info.number else (float("inf"), info.ref)
            except ValueError:
                return (float("inf"), info.ref)

        return sorted(gezien.values(), key=sleutel)

    def page_urls(self, chapter_ref: str, *, data_saver: bool = False) -> list[str]:
        deel = chapter_ref.strip("/").split("/")
        if len(deel) != 2:
            raise SourceError(f"{chapter_ref!r} is geen hoofdstukverwijzing (verwacht 'slug/deel')")
        slug = _slug_uit(deel[0])
        boom = self._pagina(f"/chapter/{slug}/{deel[1]}")

        adressen: list[str] = []
        for bron in boom.xpath("//img/@src | //img/@data-src"):
            adres = str(bron).strip()
            # Alleen de paginabeelden: de logo's van de site staan er ook
            # tussen, en die horen niet in een hoofdstuk.
            beeld = re.search(r"\.(jpe?g|png|webp)$", adres, re.I)
            if beeld and slug in adres and adres not in adressen:
                adressen.append(adres)

        if not adressen:
            raise SourceError(
                f"geen pagina's gevonden in {chapter_ref} — "
                "opmaak van MangaKakalot waarschijnlijk veranderd"
            )
        return adressen

    def download(self, chapter_ref: str, target: Path, *, data_saver: bool = False) -> Path:
        """Eén hoofdstuk als cbz.

        Eerst naar een tijdelijk bestand, net als bij MangaDex: een half
        binnengehaald hoofdstuk mag de scanner nooit als geldig archief
        tegenkomen.
        """
        adressen = self.page_urls(chapter_ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        deels = target.with_suffix(target.suffix + ".partial")
        try:
            with zipfile.ZipFile(deels, "w", zipfile.ZIP_STORED) as archief:
                for nummer, adres in enumerate(adressen, start=1):
                    self._limiter.acquire()
                    try:
                        antwoord = self._client.get(adres, headers={"Referer": SITE_BASE})
                        antwoord.raise_for_status()
                    except httpx.HTTPError as exc:
                        raise SourceError(f"pagina {nummer} ophalen mislukt: {exc}") from exc
                    achtervoegsel = Path(urlparse(adres).path).suffix or ".jpg"
                    archief.writestr(f"{nummer:03d}{achtervoegsel}", antwoord.content)
            deels.replace(target)
        finally:
            deels.unlink(missing_ok=True)
        return target

    def close(self) -> None:
        self._client.close()
