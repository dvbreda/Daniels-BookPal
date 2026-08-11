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


class SeriesDetailOut(SeriesOut):
    books: list[BookOut] = Field(default_factory=list)


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


class SourceIn(BaseModel):
    type: str = Field(max_length=50)
    name: str = Field(max_length=100)
    enabled: bool = True


class SearchResultOut(BaseModel):
    """Een treffer bij een bron — nog geen serie in je bibliotheek."""

    ref: str
    title: str
    description: str | None = None
    year: int | None = None
    status: str | None = None
    original_language: str | None = None
    tracker_ids: dict[str, str] = Field(default_factory=dict)
    # Volg je deze al? Dan hoeft de UI geen tweede aanroep te doen.
    subscribed_series_id: int | None = None
    # Rechtstreeks te tonen als miniatuur in een zoekresultaat; pas bij
    # koppelen (POST .../cover) gaat hij door de eigen cache en beeldpipeline.
    cover_url: str | None = None


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
    last_checked_at: datetime | None
    preferred_group_id: str | None = None
    available_groups: list[GroupOut] = Field(default_factory=list)
    series_title: str = ""
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
