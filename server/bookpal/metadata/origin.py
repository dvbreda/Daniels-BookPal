"""De herkomst-keten: waar komt een serie vandaan?

Dit is de lastigste eis van BookPal, want **ComicInfo.xml kent geen land van
herkomst**. Er zijn alleen indirecte signalen. De keten werkt van sterk naar
zwak en de eerste treffer wint:

1. ``MANUAL``       — door de gebruiker gezet; wint altijd, ook bij een rescan
2. ``ONLINE``       — metadata van een bron (MangaDex geeft ``originalLanguage``)
3. ``EMBEDDED``     — ComicInfo's Manga-veld, uitgever, taal van het bestand
4. ``ROOT_DEFAULT`` — de default van de library-root (``/manga`` → Japan)

Eén subtiliteit die makkelijk misgaat: ``LanguageISO`` is de taal van **deze
editie**, niet van het origineel. Een Nederlandse scan van een Japanse manga
heeft ``nl``. Daarom telt taal alleen zwaar als het een taal is waarin nauwelijks
vertaald wordt uitgegeven (ja/ko/zh); voor Europese talen is het een zwak
signaal dat pas meetelt als niets op manga wijst.
"""

from __future__ import annotations

from dataclasses import dataclass

from bookpal.models import ORIGIN_PRECEDENCE, OriginRegion, OriginSource

# Uitgever → (landcode, regio). De originele uitgever is een sterk signaal;
# een licentienemer zoals Glénat voor een Japanse titel niet, dus die staan er
# bewust niet in.
PUBLISHER_ORIGINS: dict[str, tuple[str, OriginRegion]] = {
    # Franstalig-Belgisch/Frans stripcircuit
    "dupuis": ("be", OriginRegion.EUROPE),
    "dargaud": ("fr", OriginRegion.EUROPE),
    "casterman": ("be", OriginRegion.EUROPE),
    "le lombard": ("be", OriginRegion.EUROPE),
    "lombard": ("be", OriginRegion.EUROPE),
    "delcourt": ("fr", OriginRegion.EUROPE),
    "soleil": ("fr", OriginRegion.EUROPE),
    "bamboo": ("fr", OriginRegion.EUROPE),
    "standaard uitgeverij": ("be", OriginRegion.EUROPE),
    "ballon media": ("be", OriginRegion.EUROPE),
    "silvester": ("nl", OriginRegion.EUROPE),
    "oog & blik": ("nl", OriginRegion.EUROPE),
    "sherpa": ("nl", OriginRegion.EUROPE),
    "bonelli": ("it", OriginRegion.EUROPE),
    "sergio bonelli": ("it", OriginRegion.EUROPE),
    "norma editorial": ("es", OriginRegion.EUROPE),
    "carlsen": ("de", OriginRegion.EUROPE),
    "egmont": ("de", OriginRegion.EUROPE),
    "rebellion": ("gb", OriginRegion.EUROPE),
    "titan": ("gb", OriginRegion.EUROPE),
    "2000 ad": ("gb", OriginRegion.EUROPE),
    # Japan
    "shueisha": ("jp", OriginRegion.JAPAN),
    "kodansha": ("jp", OriginRegion.JAPAN),
    "shogakukan": ("jp", OriginRegion.JAPAN),
    "kadokawa": ("jp", OriginRegion.JAPAN),
    "square enix": ("jp", OriginRegion.JAPAN),
    "hakusensha": ("jp", OriginRegion.JAPAN),
    "akita shoten": ("jp", OriginRegion.JAPAN),
    "futabasha": ("jp", OriginRegion.JAPAN),
    "ichijinsha": ("jp", OriginRegion.JAPAN),
    "shonen gahosha": ("jp", OriginRegion.JAPAN),
    "hobby japan": ("jp", OriginRegion.JAPAN),
    # Korea
    "naver": ("kr", OriginRegion.KOREA),
    "lezhin": ("kr", OriginRegion.KOREA),
    "daewon": ("kr", OriginRegion.KOREA),
    "haksan": ("kr", OriginRegion.KOREA),
    "kakao": ("kr", OriginRegion.KOREA),
    # China
    "tencent": ("cn", OriginRegion.CHINA),
    "bilibili": ("cn", OriginRegion.CHINA),
    "kuaikan": ("cn", OriginRegion.CHINA),
    # Verenigde Staten
    "marvel": ("us", OriginRegion.US),
    "dc comics": ("us", OriginRegion.US),
    "dc": ("us", OriginRegion.US),
    "image comics": ("us", OriginRegion.US),
    "image": ("us", OriginRegion.US),
    "dark horse": ("us", OriginRegion.US),
    "idw": ("us", OriginRegion.US),
    "boom! studios": ("us", OriginRegion.US),
    "valiant": ("us", OriginRegion.US),
    "vertigo": ("us", OriginRegion.US),
    "oni press": ("us", OriginRegion.US),
    "archie": ("us", OriginRegion.US),
    "dynamite": ("us", OriginRegion.US),
}

# Talen waarin vrijwel alleen origineel werk verschijnt.
ORIGINAL_LANGUAGE_REGIONS: dict[str, tuple[str, OriginRegion]] = {
    "ja": ("jp", OriginRegion.JAPAN),
    "jp": ("jp", OriginRegion.JAPAN),
    "ko": ("kr", OriginRegion.KOREA),
    "zh": ("cn", OriginRegion.CHINA),
    "zh-hk": ("cn", OriginRegion.CHINA),
}

# Talen die op een Europese uitgave wijzen, maar net zo goed een vertaling
# kunnen zijn — daarom alleen bruikbaar als niets op manga wijst.
EUROPEAN_LANGUAGES: dict[str, str] = {
    "nl": "nl",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "it": "it",
    "da": "dk",
    "sv": "se",
    "no": "no",
    "fi": "fi",
    "pl": "pl",
    "pt": "pt",
    "cs": "cz",
}

REGION_BY_COUNTRY: dict[str, OriginRegion] = {
    "jp": OriginRegion.JAPAN,
    "kr": OriginRegion.KOREA,
    "cn": OriginRegion.CHINA,
    "tw": OriginRegion.CHINA,
    "us": OriginRegion.US,
    "ca": OriginRegion.US,
}


@dataclass(slots=True)
class Origin:
    language: str | None = None
    country: str | None = None
    region: OriginRegion = OriginRegion.UNKNOWN
    source: OriginSource = OriginSource.NONE

    @property
    def known(self) -> bool:
        return self.region is not OriginRegion.UNKNOWN


def region_for_country(country: str | None) -> OriginRegion:
    if not country:
        return OriginRegion.UNKNOWN
    code = country.strip().lower()
    if code in REGION_BY_COUNTRY:
        return REGION_BY_COUNTRY[code]
    if len(code) == 2:
        # Al het overige tweeletterige is in de praktijk Europees materiaal.
        return (
            OriginRegion.EUROPE if code in set(EUROPEAN_LANGUAGES.values()) else OriginRegion.OTHER
        )
    return OriginRegion.UNKNOWN


def _lookup_publisher(publisher: str | None) -> tuple[str, OriginRegion] | None:
    if not publisher:
        return None
    needle = publisher.strip().lower()
    if needle in PUBLISHER_ORIGINS:
        return PUBLISHER_ORIGINS[needle]
    # Uitgeversnamen staan zelden precies zo in het bestand ("Dupuis Éditions").
    for name, value in PUBLISHER_ORIGINS.items():
        if name in needle:
            return value
    return None


def from_embedded(
    publisher: str | None = None,
    language: str | None = None,
    manga_flag: str | None = None,
    *,
    weak_language_ok: bool = True,
) -> Origin:
    """Stap 3: wat het bestand zelf prijsgeeft.

    ``weak_language_ok`` staat uit voor epub en pdf. Bij een strip zegt "geen
    manga-vlag plus een Europese taal" nog iets, maar bij een boek is de taal
    vrijwel altijd die van de vertaling — een Nederlandse epub van een Amerikaanse
    roman zou anders als Europees materiaal binnenkomen.
    """
    is_manga = manga_flag is not None and manga_flag.strip().lower() in {"yes", "yesandrighttoleft"}
    lang = (language or "").strip().lower()

    # Het Manga-veld is het enige expliciete herkomst-achtige signaal dat
    # ComicInfo heeft, dus het weegt het zwaarst.
    if is_manga:
        return Origin("ja", "jp", OriginRegion.JAPAN, OriginSource.EMBEDDED)

    publisher_hit = _lookup_publisher(publisher)
    if publisher_hit is not None:
        country, region = publisher_hit
        return Origin(lang or None, country, region, OriginSource.EMBEDDED)

    if lang in ORIGINAL_LANGUAGE_REGIONS:
        country, region = ORIGINAL_LANGUAGE_REGIONS[lang]
        return Origin(lang, country, region, OriginSource.EMBEDDED)

    # Zwak signaal: een Europese taal zonder manga-aanwijzing.
    base_lang = lang.split("-")[0]
    if weak_language_ok and base_lang in EUROPEAN_LANGUAGES and manga_flag is None:
        return Origin(
            lang, EUROPEAN_LANGUAGES[base_lang], OriginRegion.EUROPE, OriginSource.EMBEDDED
        )

    return Origin()


def from_root_default(default_language: str | None, default_region: OriginRegion | None) -> Origin:
    """Stap 4: wat er voor de hele map is ingesteld."""
    if default_region is None and not default_language:
        return Origin()
    language = (default_language or "").strip().lower() or None
    region = default_region
    country: str | None = None
    if region is None and language:
        if language in ORIGINAL_LANGUAGE_REGIONS:
            country, region = ORIGINAL_LANGUAGE_REGIONS[language]
        elif language in EUROPEAN_LANGUAGES:
            country, region = EUROPEAN_LANGUAGES[language], OriginRegion.EUROPE
    if region is None:
        return Origin()
    return Origin(language, country, region, OriginSource.ROOT_DEFAULT)


def from_online(original_language: str | None) -> Origin:
    """Stap 2: MangaDex en soortgenoten geven de oorspronkelijke taal, wat het
    eerlijkste signaal is dat er bestaat."""
    lang = (original_language or "").strip().lower()
    if not lang:
        return Origin()
    if lang in ORIGINAL_LANGUAGE_REGIONS:
        country, region = ORIGINAL_LANGUAGE_REGIONS[lang]
        return Origin(lang, country, region, OriginSource.ONLINE)
    if lang == "en":
        return Origin(lang, "us", OriginRegion.US, OriginSource.ONLINE)
    base = lang.split("-")[0]
    if base in EUROPEAN_LANGUAGES:
        return Origin(lang, EUROPEAN_LANGUAGES[base], OriginRegion.EUROPE, OriginSource.ONLINE)
    return Origin(lang, None, OriginRegion.OTHER, OriginSource.ONLINE)


def resolve(
    *candidates: Origin,
    current: Origin | None = None,
) -> Origin:
    """Kies de sterkste bekende herkomst.

    ``current`` is wat er al op de serie staat; een handmatige keuze overleeft
    daardoor elke rescan, wat de belangrijkste eigenschap van deze keten is.
    """
    best = current if current is not None and current.known else Origin()
    best_rank = ORIGIN_PRECEDENCE[best.source] if best.known else -1
    for candidate in candidates:
        if not candidate.known:
            continue
        rank = ORIGIN_PRECEDENCE[candidate.source]
        if rank > best_rank:
            best, best_rank = candidate, rank
    return best
