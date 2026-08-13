"""Pydantic-schema's voor de API.

Bewust losgekoppeld van de SQLAlchemy-modellen: de clients (web, Lite, iOS,
Kobo) hangen aan dít contract, niet aan het databaseschema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from bookpal.models import BookKind, OriginRegion, OriginSource, SubscriptionPolicy


class LibraryRootIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1)
    default_origin_language: str | None = None
    default_origin_region: OriginRegion | None = None
    folder_as_collection: bool = False
    enabled: bool = True


class LibraryRootOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    path: str
    enabled: bool
    default_origin_language: str | None
    default_origin_region: OriginRegion | None
    folder_as_collection: bool
    last_scan_at: datetime | None
    series_count: int = 0
    book_count: int = 0
    # Kan BookPal hier zelf iets neerzetten? Zo niet, dan staat hier waarom —
    # in gewone taal, want de oplossing verschilt per oorzaak.
    writable: bool = True
    write_problem: str | None = None


class ProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: dict[str, Any]
    percent: float
    finished: bool
    device: str | None
    updated_at: datetime


class ProgressIn(BaseModel):
    book_id: int
    position: dict[str, Any] = Field(default_factory=dict)
    percent: float = Field(ge=0.0, le=100.0)
    finished: bool = False
    device: str | None = Field(default=None, max_length=100)


class BookAlternativeOut(BaseModel):
    """Hetzelfde hoofdstuk uit een andere uitgave."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    edition_id: int | None = None
    edition_name: str | None = None
    edition_language: str | None = None
    edition_note: str | None = None
    has_file: bool = False


class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    series_id: int
    kind: BookKind
    title: str
    number: str | None
    volume: str | None
    page_count: int | None
    right_to_left: bool
    # Lokaal bestand of alleen een bron-referentie? Clients gebruiken dit om te
    # bepalen of ze kunnen lezen of eerst moeten downloaden.
    has_file: bool
    # Komt dit van een abonnement of uit je eigen mappen? Samen met has_file
    # geeft dat de drie toestanden die een client wil tonen: eigen bestand,
    # opgehaald van een bron, en nog op te halen.
    from_source: bool = False
    # Wie heeft dit vertaald? Alleen gevuld bij bronnen die dat meegeven.
    source_group_name: str | None = None
    # Bij een tijdelijke (readahead-)download: wanneer mag het bestand weg?
    expires_at: datetime | None = None
    extension: str | None
    added_at: datetime
    progress: ProgressOut | None = None
    # Uit welke uitgave dit deel komt, en wat er verder voor deze aflevering
    # klaarligt. Alleen gevuld in de serie-detailweergave, want daar worden de
    # uitgaven samengevouwen tot één leeslijst.
    edition_id: int | None = None
    edition_name: str | None = None
    # Waarin deze uitgave zich onderscheidt: de taal van het abonnement en een
    # label als "kleur". Per hoofdstuk zichtbaar, want dat is precies wat je
    # wilt weten voordat je hem opent.
    edition_language: str | None = None
    edition_note: str | None = None
    alternatives: list[BookAlternativeOut] = Field(default_factory=list)


class SeriesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    sort_title: str
    library_root_id: int | None
    folder_path: str | None
    origin_language: str | None
    origin_country: str | None
    origin_region: OriginRegion
    origin_source: OriginSource
    publisher: str | None
    authors: list[str] = Field(default_factory=list)
    tags: list[str]
    summary: str | None
    book_count: int = 0
    kinds: list[BookKind] = Field(default_factory=list)
    # Gevolgd bij een bron? Dan toont de client dat, en weet hij dat er
    # hoofdstukken kunnen zijn zonder lokaal bestand.
    from_source: bool = False
    # Heeft deze serie een omslag van een bron? Zonder dit weet de client niet
    # of /api/series/{id}/cover iets oplevert, en moet hij het gewoon proberen
    # en op een 404 wachten.
    has_cover_url: bool = False
    # Handmatig gekozen paginanummer voor de omslag, als dat gezet is.
    cover_page_index: int | None = None


class EditionOut(BaseModel):
    """Eén uitgave binnen een serie, in voorkeursvolgorde."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    series_id: int
    name: str
    rank: int
    note: str | None = None
    # De taal van het abonnement waar deze uitgave bij hoort; leeg voor je
    # eigen bestanden, want daar zegt niets wat de taal is.
    language: str | None = None
    subscription_id: int | None = None
    folder_path: str | None = None
    # Hoeveel delen deze uitgave heeft, en hoeveel daarvan je te zien krijgt.
    # Het verschil is precies wat een lager gerangschikte uitgave aanvult.
    book_count: int = 0
    chosen_count: int = 0


class MergeCandidateOut(BaseModel):
    """Een serie die na het hernoemen dezelfde naam blijkt te hebben."""

    id: int
    title: str
    books: int


class SidecarSyncOut(BaseModel):
    """Hoeveel metadata-bestandjes er zijn weggeschreven."""

    written: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class HomeItemOut(BaseModel):
    """Eén tegel op de startpagina: genoeg om te tonen en te openen."""

    book_id: int
    series_id: int
    series_title: str
    title: str
    number: str | None = None
    volume: str | None = None
    kind: BookKind
    has_file: bool = True
    extension: str | None = None
    page_count: int | None = None
    percent: float = 0.0
    finished: bool = False
    # De pagina waar je gebleven was; de lezer opent hier.
    page: int = 0
    updated_at: datetime | None = None
    added_at: datetime


class HomeRailOut(BaseModel):
    """Eén rij op de startpagina."""

    key: str
    title: str
    items: list[HomeItemOut] = Field(default_factory=list)


class HomeOut(BaseModel):
    # Lege rails komen niet mee: een kop zonder inhoud is ruis.
    rails: list[HomeRailOut] = Field(default_factory=list)


class KoboStatusOut(BaseModel):
    """Wat er van de Kobo-koppeling aanstaat, en of het apparaat er is."""

    mount: str | None = None
    connected: bool = False
    writable: bool = False
    error: str | None = None
    folder: str = "BookPal"
    ahead: int = 3
    series_ids: list[int] = Field(default_factory=list)
    export_books: bool = True
    write_shelves: bool = True
    read_progress: bool = True
    dry_run: bool = True


class KoboSettingsIn(BaseModel):
    """Alleen wat je meestuurt wordt aangepast."""

    mount: str | None = None
    folder: str | None = None
    ahead: int | None = Field(default=None, ge=1, le=50)
    series_ids: list[int] | None = None
    export_books: bool | None = None
    write_shelves: bool | None = None
    read_progress: bool | None = None
    dry_run: bool | None = None


class KoboPlanOut(BaseModel):
    book_id: int
    series_title: str
    title: str
    path: str


class KoboSyncOut(BaseModel):
    dry_run: bool = True
    planned: int = 0
    copied: int = 0
    skipped: int = 0
    removed: int = 0
    shelves_created: list[str] = Field(default_factory=list)
    shelf_entries: int = 0
    not_imported: int = 0
    progress_updated: int = 0
    # De naam van de kopie die vóór het schrijven is gemaakt.
    backup: str | None = None
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SyncCoversOut(BaseModel):
    """Hoeveel omslagen er zijn bijgewerkt, en waar het misging."""

    updated: int = 0
    editions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SeriesRenameIn(BaseModel):
    """De naam van de serie zoals jij hem wilt zien.

    Nodig zodra een serie meerdere uitgaven heeft: hij houdt de titel van de
    uitgave waar hij mee begon, en "Dragon Ball Super (Official Colored)" klopt
    niet meer als de zwart-witte uitgave er ook in zit.
    """

    title: str = Field(min_length=1, max_length=500)


class SeriesRenameOut(SeriesOut):
    """De serie na het hernoemen, plus wat je er waarschijnlijk mee wilde.

    Hernoemen naar een naam die al bestaat betekent bijna altijd dat het
    hetzelfde ding is. Dat is een vraag en geen automatisme: gelijknamig is niet
    hetzelfde, en samenvoegen laat zich niet met één druk terugdraaien.

    Is die naam in dezelfde map al bezet, dan kán de serie niet hernoemd worden
    — twee mappen met dezelfde naam bestaan niet. Dan blijft ``renamed`` op
    false en is samenvoegen de enige weg vooruit.
    """

    renamed: bool = True
    merge_candidate: MergeCandidateOut | None = None


class EditionPatch(BaseModel):
    name: str | None = None
    note: str | None = None


class EditionOrderIn(BaseModel):
    """De uitgaven in de volgorde die je wilt lezen, eerste keus vooraan."""

    edition_ids: list[int]


class BookSlotIn(BaseModel):
    """Welke boeken dezelfde uitgave van hetzelfde ding zijn.

    Voor titels zonder deelnummer — drie drukken van één boek horen bij elkaar,
    maar dat is aan de titel niet te zien.
    """

    book_ids: list[int]


class SeriesDetailOut(SeriesOut):
    books: list[BookOut] = Field(default_factory=list)
    editions: list[EditionOut] = Field(default_factory=list)


class OriginPatch(BaseModel):
    """Handmatige correctie. Zet ``origin_source`` op MANUAL, waardoor een
    rescan de keuze niet meer overschrijft."""

    origin_language: str | None = None
    origin_country: str | None = None
    origin_region: OriginRegion


class AttachCoverIn(BaseModel):
    """Koppel de omslag van een bron aan een (ook lokale) serie, zonder
    daarmee te abonneren."""

    source_id: int
    ref: str = Field(max_length=200)


class SetCoverPageIn(BaseModel):
    """Een vaste pagina van het eerste boek als omslag, in plaats van
    'pagina 1'. ``None`` zet de serie terug op de standaardkeuze."""

    page_index: int | None = Field(default=None, ge=0)


class ContinueOut(BaseModel):
    """Waar je verder leest in deze serie."""

    book_id: int
    title: str
    number: str | None
    # De pagina waar je gebleven was; 0 voor een hoofdstuk dat je nog moet
    # beginnen. Een epub heeft geen paginanummer — daar gebruikt de lezer zijn
    # eigen opgeslagen positie.
    page: int
    # Ga je verder in iets dat je al begonnen was, of begin je aan een nieuw
    # hoofdstuk? Bepaalt of de knop "Lees verder" of "Beginnen" heet.
    resuming: bool
    # Staat dit hoofdstuk al op de NAS? Zo niet, dan hoort de knop het eerst op
    # te halen. Bij een serie die je vooral online volgt is dat de normale
    # situatie: je bent bij 124 en 125 moet nog binnenkomen.
    has_file: bool = True
    # Hoeveel hoofdstukken hiervóór nog niet uitgelezen zijn — dat is precies
    # wat de knop "markeer vorige als gelezen" zou opruimen.
    unread_before: int


class MarkReadBeforeOut(BaseModel):
    marked: int


class NextChapterOut(BaseModel):
    """Het volgende hoofdstuk, om aan te bieden als je er een uit hebt."""

    book_id: int
    title: str
    number: str | None
    volume: str | None
    # Al binnen, of moet het nog opgehaald worden? Bepaalt of de knop meteen
    # opent of eerst downloadt.
    has_file: bool


class IntakeCandidateOut(BaseModel):
    path: str
    name: str
    size: int
    series: str | None = None
    number: str | None = None


class IntakeScanOut(BaseModel):
    # Welke mappen er daadwerkelijk bestaan; anders zoek je je scheel naar
    # waarom er niets staat.
    folders: list[str] = Field(default_factory=list)
    # Mappen die bestaan maar waaruit niets verplaatst kan worden — meestal
    # omdat Docker ze als root heeft aangemaakt.
    unwritable: list[str] = Field(default_factory=list)
    files: list[IntakeCandidateOut] = Field(default_factory=list)


class IntakeImportIn(BaseModel):
    paths: list[str]
    root_id: int
    # Submap op serienaam; leeg zet ze los in de root.
    folder: str | None = Field(default=None, max_length=200)


class IntakeImportOut(BaseModel):
    moved: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class MergeSeriesIn(BaseModel):
    """De serie die opgaat in deze. Verdwijnt daarna."""

    absorb_id: int


class MergeSuggestionOut(BaseModel):
    keep_id: int
    keep_title: str
    keep_books: int
    absorb_id: int
    absorb_title: str
    absorb_books: int


class ImportSeriesIn(BaseModel):
    """Een gevolgde serie als gewone bestanden in je eigen mappen zetten."""

    root_id: int
    # Ontbrekende hoofdstukken ophalen, of alleen verplaatsen wat er al is.
    download_missing: bool = True


class ImportSeriesOut(BaseModel):
    moved: int
    downloaded: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class WikiHitOut(BaseModel):
    title: str
    key: str
    description: str | None = None
    lang: str


class TocEntryOut(BaseModel):
    title: str
    target: str
    level: int


class BookDetailOut(BookOut):
    series_title: str
    toc: list[TocEntryOut] = Field(default_factory=list)


class ScanResultOut(BaseModel):
    root: str
    added: int
    updated: int
    unchanged: int
    removed: int
    errors: list[str]


class PageInfoOut(BaseModel):
    index: int
    url: str


class ProfileOut(BaseModel):
    name: str
    max_width: int | None
    max_height: int | None
    format: str
    grayscale: bool


class TabIn(BaseModel):
    """Een tab: naam + icoon + volgorde + regel + weergave (ontwerp 2)."""

    name: str = Field(max_length=100)
    icon: str | None = Field(default=None, max_length=60)
    position: int = 0
    rule: dict[str, Any] = Field(default_factory=dict)
    view_mode: str = Field(default="grid", max_length=20)
    group_by: str | None = Field(default=None, max_length=20)
    enabled: bool = True


class TabOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    icon: str | None
    position: int
    rule: dict[str, Any]
    view_mode: str
    group_by: str | None
    enabled: bool


class CollectionIn(BaseModel):
    """Een slimme collectie: dezelfde regel-engine als tabs, plus group_by."""

    name: str = Field(max_length=200)
    smart: bool = True
    rule: dict[str, Any] = Field(default_factory=dict)
    group_by: str | None = Field(default=None, max_length=20)


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    smart: bool
    rule: dict[str, Any]
    group_by: str | None


class SourceOut(BaseModel):
    """Een externe bron (M5), bv. MangaDex."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    name: str
    enabled: bool
    # Wat een zelf toegevoegde bron nodig heeft, bv. het adres van een
    # OPDS-catalogus. Een wachtwoord gaat er niet uit; zie SourceIn.
    config: dict[str, Any] = Field(default_factory=dict)


class SourceIn(BaseModel):
    type: str = Field(max_length=50)
    name: str = Field(max_length=100)
    enabled: bool = True
    # Vrij veld per bronsoort. Bij OPDS: {"url": "...", "username": ...,
    # "password": ...}. Bewust geen apart model per soort — dan zou elke nieuwe
    # bron een schemawijziging vragen.
    config: dict[str, Any] = Field(default_factory=dict)


class SearchResultOut(BaseModel):
    """Een treffer bij een bron — nog geen serie in je bibliotheek."""

    ref: str
    title: str
    description: str | None = None
    year: int | None = None
    status: str | None = None
    original_language: str | None = None
    tracker_ids: dict[str, str] = Field(default_factory=dict)
    # Volg je precies deze reeks al bij deze bron? Dan hoeft de UI geen tweede
    # aanroep te doen.
    subscribed_series_id: int | None = None
    # Heb je hier al een serie van onder (bijna) dezelfde titel? Dan voeg je
    # hiermee een bron toe aan wat je al hebt in plaats van een tweede serie te
    # maken — en dat hoor je te zien vóórdat je op volgen drukt.
    existing_series_id: int | None = None
    existing_series_title: str | None = None
    # Rechtstreeks te tonen als miniatuur in een zoekresultaat; pas bij
    # koppelen (POST .../cover) gaat hij door de eigen cache en beeldpipeline.
    cover_url: str | None = None
    # De pagina bij de bron, om te kunnen controleren wat dit is.
    url: str | None = None
    # In welke talen er vertalingen bestaan.
    languages: list[str] = Field(default_factory=list)


class ChapterCountOut(BaseModel):
    """Hoeveel hoofdstukken een reeks bij de bron heeft, in één taal."""

    ref: str
    language: str
    count: int


class SubscribeIn(BaseModel):
    ref: str = Field(max_length=200)
    policy: str = Field(default="readahead", pattern="^(permanent|readahead)$")
    readahead_n: int = Field(default=3, ge=0, le=50)
    ttl_days: int = Field(default=14, ge=1, le=365)
    language: str = Field(default="en", max_length=8)


class GroupOut(BaseModel):
    """Een vertaalgroep die deze reeks (deels) heeft gedaan."""

    id: str
    name: str
    chapters: int


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    series_id: int
    policy: SubscriptionPolicy
    readahead_n: int
    ttl_days: int
    # In welke taal je deze reeks volgt; meerdere talen naast elkaar worden
    # uitgaven van één serie.
    language: str = "en"
    last_checked_at: datetime | None
    preferred_group_id: str | None = None
    available_groups: list[GroupOut] = Field(default_factory=list)
    series_title: str = ""
    # Hoe de bron deze reeks noemt. Bij een serie met meerdere abonnementen is
    # dít het onderscheid — "Dragon Ball Super (Coloured Edition)" naast
    # "Dragon Ball Super" — want jouw serietitel is voor beide dezelfde.
    source_title: str = ""
    chapters_total: int = 0
    chapters_local: int = 0


class SubscriptionPatch(BaseModel):
    """Wat je aan een lopend abonnement kunt bijstellen.

    ``preferred_group_id`` op ``null`` zet hem terug op automatisch kiezen.
    """

    preferred_group_id: str | None = Field(default=None, max_length=200)
    policy: str | None = Field(default=None, pattern="^(permanent|readahead)$")
    readahead_n: int | None = Field(default=None, ge=0, le=50)
    ttl_days: int | None = Field(default=None, ge=1, le=365)


class SubscribeResultOut(BaseModel):
    subscription: SubscriptionOut
    series_id: int
    chapters_added: int


class RunReportOut(BaseModel):
    """Wat een ronde van de abonnementen-worker heeft gedaan."""

    subscriptions: int
    chapters_added: int
    downloaded: int
    expired: int
    errors: list[str] = Field(default_factory=list)


class TrackerAccountOut(BaseModel):
    """Nooit ``credentials`` hierin — dat zijn client-secrets en tokens."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    enabled: bool
    dry_run: bool
    last_sync_at: datetime | None
    # Voor MAL: heeft dit account al een access token, of moet er nog
    # gekoppeld worden? De UI kan dit tonen zonder de credentials te kennen.
    connected: bool = False


class TrackerAccountIn(BaseModel):
    provider: str = Field(max_length=50)
    # Alleen voor MAL nodig: je eigen app-registratie bij MyAnimeList.
    client_id: str | None = Field(default=None, max_length=200)
    client_secret: str | None = Field(default=None, max_length=200)


class TrackerAccountPatch(BaseModel):
    enabled: bool | None = None
    dry_run: bool | None = None


class GoodreadsLoginIn(BaseModel):
    """Inloggen bij Goodreads via hun eigen site.

    Het wachtwoord wordt gebruikt om in te loggen en daarna niet bewaard —
    alleen de sessie gaat de database in, zodat er niet elke ronde opnieuw
    ingelogd hoeft te worden.
    """

    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class ShelfRowOut(BaseModel):
    """Eén serie zoals hij op een leeslijst zou staan."""

    series_id: int
    title: str
    author: str | None = None
    status: str
    shelf: str
    chapters_read: int = 0
    chapters_total: int = 0
    percent: float = 0.0
    # Het id bij deze tracker, als het bekend is. Zonder id kan er niet
    # gepusht worden — bij MyAnimeList is dat het gangbare geval voor series
    # die niet van een bron komen.
    remote_id: str | None = None
    pushable: bool = True


class ShelvesOut(BaseModel):
    """Wat er naar een tracker zou gaan, per plank gegroepeerd."""

    provider: str = "goodreads"
    # Hoeveel er niet gepusht kan worden omdat er geen id bij deze tracker is.
    without_id: int = 0
    reading: list[ShelfRowOut] = Field(default_factory=list)
    to_read: list[ShelfRowOut] = Field(default_factory=list)
    read: list[ShelfRowOut] = Field(default_factory=list)


class GoodreadsStatusOut(BaseModel):
    # Is er een browser beschikbaar? Chromium wordt pas op verzoek gedownload.
    browser_ready: bool
    browser_note: str = ""
    connected: bool
    last_sync_at: datetime | None = None


class GoodreadsSyncOut(BaseModel):
    updated: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class MalListItemOut(BaseModel):
    """Een reeks van je MyAnimeList-lijst."""

    mal_id: str
    title: str
    status: str
    chapters: int = 0
    chapters_read: int = 0
    score: int = 0
    # Heb je deze al in je bibliotheek? Dit is de harde koppeling: de serie
    # draagt dit MyAnimeList-id.
    series_id: int | None = None
    # Een serie die zó heet maar (nog) geen id draagt. Alleen een voorstel —
    # "Shinya Shokudou" en "Shinya Shokudo" zijn hetzelfde, maar dat blijft
    # raden, dus de gebruiker beslist.
    match_series_id: int | None = None
    match_title: str | None = None


class MalLinkIn(BaseModel):
    """Een serie uit je bibliotheek aan een MyAnimeList-reeks hangen."""

    series_id: int
    mal_id: str = Field(max_length=20)


class IntakeFetchIn(BaseModel):
    """Een deellink ophalen: een Dropbox-map, een los bestand."""

    url: str
    # Waar het terechtkomt. Leeg = de eerste intake-map, zodat je er daarna
    # zelf een bibliotheekmap voor kiest.
    folder: str | None = None


class IntakeFetchOut(BaseModel):
    """De stand van het ophalen: bezig, klaar, mislukt of niets."""

    state: str = "niets"
    url: str = ""
    folder: str | None = None
    bytes_done: int = 0
    # Wat de server zei dat er zou komen; bij een gedeelde map weet hij dat
    # vaak zelf niet, en dan is het aantal bytes het enige teken van leven.
    bytes_total: int | None = None
    saved: list[str] = Field(default_factory=list)
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class IntakeUploadOut(BaseModel):
    path: str
    name: str
    size: int


class ReadStateIn(BaseModel):
    """Zelf bepalen of iets gelezen is."""

    finished: bool


class ReadStateOut(BaseModel):
    book_id: int
    finished: bool
    # Hoeveel uitgaven van deze aflevering het betrof.
    affected: int = 1


class MalImportProgressIn(BaseModel):
    """Leesstatus van MyAnimeList overnemen.

    Zonder ``series_id`` gaat het over alles wat gekoppeld is.
    """

    series_id: int | None = None


class MalImportProgressOut(BaseModel):
    marked: int
    series: list[str] = Field(default_factory=list)


class MalAuthorizeOut(BaseModel):
    url: str
    # Dit adres moet in je MAL-app-registratie staan; de client toont het.
    redirect_uri: str = ""


class MalCallbackIn(BaseModel):
    code: str = Field(max_length=2000)


class PushResultOut(BaseModel):
    series_id: int
    title: str
    pushed: bool
    dry_run: bool
    detail: str = ""


class PushReportOut(BaseModel):
    provider: str
    pushed: int
    results: list[PushResultOut] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    # Niets te doen — bij een proefronde bijvoorbeeld.
    skipped: list[str] = Field(default_factory=list)
    # Andersom: de tracker stond verder en die stand is hier overgenomen.
    pulled: list[str] = Field(default_factory=list)


class BubbleOut(BaseModel):
    """Eén tekstvlak. ``box`` is [x0, y0, x1, y1] genormaliseerd op 0..1 ten
    opzichte van de hele pagina, zodat dezelfde vertaling over elk
    beeldprofiel past."""

    box: list[float]
    source: str
    translation: str
    kind: str
    bold: bool = False
    italic: bool = False


class PageTranslationOut(BaseModel):
    book_id: int
    page_index: int
    target_lang: str
    provider: str
    model: str = ""
    bubbles: list[BubbleOut] = Field(default_factory=list)
    # In de beeldstanden is de hele pagina hertekend in plaats van dat er
    # tekstvlakken over het origineel gaan. De lezer moet dat weten: hij toont
    # dan een andere afbeelding in plaats van een overlay, en er valt niet op
    # een losse ballon te tikken voor het origineel.
    mode: str = "text"
    full_page: bool = False


class PageColourOut(BaseModel):
    """Of er voor deze pagina een ingekleurde versie klaarstaat."""

    book_id: int
    page_index: int
    available: bool = False


class TranslateModeOut(BaseModel):
    mode: str
    # Wat de knop in de lezer doet. Losgekoppeld van de automatische stand:
    # vanzelf vertalen mag goedkoop zijn, maar als jij zelf op een pagina drukt
    # is dat juist omdat die ene het waard is.
    button_mode: str = "image_fast"
    # Met welk beeldmodel er ingekleurd wordt. Eigen stand, want inkleuren
    # stelt andere eisen dan vertalen: er komt geen letter aan te pas.
    colour_mode: str = "image_fast"
    # Zonder sleutel kan er niets; de client verbergt de keuze dan.
    configured: bool
    # Waar vertalingen bewaard worden, en of dat ook echt lukt. Een vertaling
    # kost geld; stilzwijgend niet kunnen bewaren is duur.
    sidecar_dir: str = ""
    sidecar_writable: bool = True
    # Ruwe richtprijs per pagina in dollar, zodat de keuze niet blind is.
    costs: dict[str, float] = Field(default_factory=dict)


class TranslateModeIn(BaseModel):
    """Beide standen zijn los te zetten; wat je niet meestuurt blijft staan."""

    mode: str | None = Field(default=None, max_length=20)
    button_mode: str | None = Field(default=None, max_length=20)
    colour_mode: str | None = Field(default=None, max_length=20)


class BatchPlanOut(BaseModel):
    """Wat een klus voor dit hoofdstuk gaat inhouden, vóór je hem start.

    Met de prijs erbij, want dit is de enige knop in de app die in één druk
    een heel hoofdstuk kost. Zonder bedrag is dat een gok.
    """

    kind: str
    mode: str
    pages: int
    price_per_page: float
    total: float
    # Batchwerk kost bij Google de helft van een gewone aanroep; dat staat hier
    # zodat de lezer het verschil kan laten zien in plaats van te suggereren
    # dat dit het normale tarief is.
    batch_factor: float


class BatchStatusOut(BaseModel):
    kind: str
    book_id: int
    mode: str
    state: str
    done: int
    total: int
    failed: int
    error: str | None = None


class TranslatePageIn(BaseModel):
    """De knop "vertaal deze pagina volledig". Bewust een expliciete keuze per
    aanroep: deze standen kosten geld, dus ze horen nooit vanzelf te lopen."""

    mode: str = Field(max_length=20)
    lang: str | None = Field(default=None, max_length=8)
    force: bool = False


class TranslationStatusOut(BaseModel):
    book_id: int
    target_lang: str
    provider: str
    # Zonder sleutel kan er niets; de client verbergt de knop dan.
    configured: bool
    page_count: int | None
    translated: int
    queued: int


class BatchStartIn(BaseModel):
    """Welke soort klus, en vanaf welke pagina."""

    kind: str = Field(max_length=20)
    from_page: int = Field(default=0, ge=0)


class TranslateBookIn(BaseModel):
    lang: str | None = Field(default=None, max_length=8)
    # Vanaf welke pagina; standaard vanaf het begin. De wachtrij werkt in
    # leesvolgorde, dus dit bepaalt ook wat er als eerste klaar is.
    from_page: int = Field(default=0, ge=0)


class TranslateBookOut(BaseModel):
    queued: int
    already_done: int


class DownloadIn(BaseModel):
    """Tijdelijk downloaden is het 'vooruitlezen' uit het datamodel: het
    bestand krijgt een vervaldatum, de bron-referentie blijft."""

    data_saver: bool = False
    temporary: bool = False
    ttl_days: int = Field(default=14, ge=1, le=365)


T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


SortField = Literal["title", "added", "number"]
