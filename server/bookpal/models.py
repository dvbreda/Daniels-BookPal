"""SQLAlchemy-modellen.

Velden die pas in latere milestones gevuld worden (bron-referenties, tracker-ids,
abonnementen) staan er nu al in, zodat M2 t/m M10 geen migratiepijn geven.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[object, object]] = {
        dict[str, Any]: JSON,
        list[str]: JSON,
        list[dict[str, Any]]: JSON,
    }


class BookKind(enum.StrEnum):
    """Hoe een boek gelezen wordt — niet per se de bestandsextensie."""

    COMIC = "comic"  # cbz/cbr: een reeks paginabeelden
    EPUB = "epub"  # herschikbare tekst
    PDF = "pdf"  # vaste opmaak


class OriginRegion(enum.StrEnum):
    """Afgeleide regio waarop tab-regels filteren.

    Regels filteren hierop in plaats van op los land, zodat 'strips uit Europa'
    geen twaalf landcodes hoeft op te sommen.
    """

    EUROPE = "europe"
    JAPAN = "japan"
    KOREA = "korea"
    CHINA = "china"
    US = "us"
    OTHER = "other"
    UNKNOWN = "unknown"


class OriginSource(enum.StrEnum):
    """Welke stap van de herkomst-keten de waarde heeft gezet.

    Bewaard zodat de UI kan tonen waaróm iets als manga geldt, en zodat een
    hernieuwde scan een handmatige keuze nooit overschrijft.
    """

    MANUAL = "manual"  # 1. door de gebruiker gezet — wint altijd
    ONLINE = "online"  # 2. metadata van een bron (MangaDex originalLanguage)
    EMBEDDED = "embedded"  # 3. ComicInfo.xml / OPF / uitgever-mapping
    ROOT_DEFAULT = "root_default"  # 4. de default van de library-root
    NONE = "none"


ORIGIN_PRECEDENCE: dict[OriginSource, int] = {
    OriginSource.MANUAL: 4,
    OriginSource.ONLINE: 3,
    OriginSource.EMBEDDED: 2,
    OriginSource.ROOT_DEFAULT: 1,
    OriginSource.NONE: 0,
}


class SubscriptionPolicy(enum.StrEnum):
    PERMANENT = "permanent"
    READAHEAD = "readahead"  # tijdelijk downloaden om vooruit te lezen, met TTL


class JobState(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def _enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Opslaan als VARCHAR in plaats van een native enum — SQLite kent die niet."""
    return SAEnum(
        enum_cls, name=name, native_enum=False, values_callable=lambda e: [m.value for m in e]
    )


class LibraryRoot(Base):
    """Een map op de NAS die gescand wordt."""

    __tablename__ = "library_root"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Stap 4 van de herkomst-keten: wat geldt er voor alles onder deze map?
    default_origin_language: Mapped[str | None] = mapped_column(String(8), default=None)
    default_origin_region: Mapped[OriginRegion | None] = mapped_column(
        _enum(OriginRegion, "origin_region"), default=None
    )

    # Gebruik submappen als collecties (ontwerp 2: group_by=folder).
    folder_as_collection: Mapped[bool] = mapped_column(Boolean, default=False)

    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    files: Mapped[list[File]] = relationship(back_populates="root", cascade="all, delete-orphan")


class File(Base):
    """Een bestand op schijf. Losgekoppeld van Book zodat een geabonneerd boek
    zonder bestand kan bestaan, en een tijdelijke download weer weg kan."""

    __tablename__ = "file"

    id: Mapped[int] = mapped_column(primary_key=True)
    library_root_id: Mapped[int] = mapped_column(ForeignKey("library_root.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    size: Mapped[int] = mapped_column(Integer)
    mtime: Mapped[float] = mapped_column(Float)
    extension: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    root: Mapped[LibraryRoot] = relationship(back_populates="files")
    book: Mapped[Book | None] = relationship(back_populates="file", uselist=False)

    __table_args__ = (Index("ix_file_root_missing", "library_root_id", "missing"),)


class Series(Base):
    """Een serie groepeert boeken. Ook een los boek krijgt er een, zodat tabs en
    collecties maar één ding hoeven te kennen."""

    __tablename__ = "series"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    sort_title: Mapped[str] = mapped_column(String(500), index=True)
    library_root_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_root.id", ondelete="CASCADE"), default=None
    )
    folder_path: Mapped[str | None] = mapped_column(String(1024), default=None)

    origin_language: Mapped[str | None] = mapped_column(String(8), default=None)
    origin_country: Mapped[str | None] = mapped_column(String(8), default=None)
    origin_region: Mapped[OriginRegion] = mapped_column(
        _enum(OriginRegion, "origin_region"), default=OriginRegion.UNKNOWN, index=True
    )
    origin_source: Mapped[OriginSource] = mapped_column(
        _enum(OriginSource, "origin_source"), default=OriginSource.NONE
    )

    publisher: Mapped[str | None] = mapped_column(String(200), default=None)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    # M7: elke format-parser levert dit al (ComicInfo, epub-OPF, pdf-metadata),
    # maar niets bewaarde het — nodig voor de titel+auteur-matching die
    # Goodreads' CSV-import gebruikt.
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    # De officiële omslag van een bron, als afwijkend beter is dan "pagina 1
    # van het eerste boek". Bij scanlaties is die pagina vaak een
    # credits-pagina van de vertaalgroep over de echte cover heen, dus de
    # schone versie van de bron is dan de betere keuze. Werkt zowel voor een
    # abonnement als voor een lokale serie die je handmatig koppelt.
    cover_url: Mapped[str | None] = mapped_column(String(500), default=None)
    # Handmatig gekozen: "pagina 1" is niet altijd de omslag, en niet elke
    # serie heeft een bron met een schone versie. Wint van cover_url zodra
    # gezet — de laatste keuze van de twee geldt, zie attach_cover die dit
    # weer leegmaakt.
    cover_page_index: Mapped[int | None] = mapped_column(Integer, default=None)

    # M5: waar deze serie vandaan komt als hij geabonneerd is.
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("source.id", ondelete="SET NULL"), default=None
    )
    source_ref: Mapped[str | None] = mapped_column(String(200), default=None)

    # M7: {"mal": 1234, "goodreads": "5678"}
    tracker_ids: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    books: Mapped[list[Book]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
        order_by="Book.sort_volume, Book.sort_number",
    )
    editions: Mapped[list[Edition]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
        order_by="Edition.rank",
    )

    __table_args__ = (UniqueConstraint("library_root_id", "title", name="uq_series_root_title"),)


class Edition(Base):
    """Eén uitgave binnen een serie: dezelfde reeks, andere herkomst.

    Van één serie bestaan vaak meerdere versies naast elkaar: de gekleurde
    uitgave online, de zwart-witte met meer delen, je eigen bestanden op de
    NAS, en van een boek soms gewoon drie drukken. Dat zijn geen aparte series
    — je wilt ze in één lijst lezen, met een voorkeur die zegt welke versie
    wint als beide een deel hebben.

    ``rank`` legt die voorkeur vast: 0 is eerste keus. Een lager gerangschikte
    uitgave verdwijnt daarmee niet, hij vult aan waar je eerste keus niets
    heeft — precies wat je nodig hebt bij een gekleurde uitgave die achterloopt
    op het zwart-witte origineel.
    """

    __tablename__ = "edition"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    rank: Mapped[int] = mapped_column(Integer, default=0)

    # Waar deze uitgave vandaan komt — precies één van beide is gevuld.
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscription.id", ondelete="SET NULL"), default=None
    )
    folder_path: Mapped[str | None] = mapped_column(String(1024), default=None)

    # Vrij label voor jezelf: "kleur", "zwart-wit", "hardcover".
    note: Mapped[str | None] = mapped_column(String(100), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    series: Mapped[Series] = relationship(back_populates="editions")


class Book(Base):
    """Eén leesbaar item: een album, een deel, een hoofdstuk of een boek.

    Heeft een ``file`` (lokaal) óf een ``source_ref`` (geabonneerd). Dat is wat
    lokale en online items in dezelfde tab laat verschijnen.
    """

    __tablename__ = "book"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[int | None] = mapped_column(
        ForeignKey("file.id", ondelete="SET NULL"), default=None, unique=True
    )

    kind: Mapped[BookKind] = mapped_column(_enum(BookKind, "book_kind"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    number: Mapped[str | None] = mapped_column(String(40), default=None)
    # Genormaliseerd voor sorteren: "10.5" -> 10.5, ontbrekend -> heel groot.
    sort_number: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[str | None] = mapped_column(String(40), default=None)
    # Zonder dit sorteert een reeks puur op hoofdstuknummer, en dat nummer telt
    # meestal opnieuw per deel: hoofdstuk 1 van deel 1, deel 2, deel 10 komen
    # dan allemaal naast elkaar te staan in scan-volgorde in plaats van
    # leesvolgorde. Eerst op deel, dan pas op hoofdstuk.
    sort_volume: Mapped[float] = mapped_column(Float, default=0.0)

    # Uit welke uitgave dit deel komt. Leeg voor alles wat er stond voordat een
    # serie meerdere uitgaven kon hebben; dat telt als de eerste keus.
    edition_id: Mapped[int | None] = mapped_column(
        ForeignKey("edition.id", ondelete="SET NULL"), default=None, index=True
    )
    # Titel met de hand of bij de bron opgehaald? Dan laat de scanner hem staan.
    # Zonder dit zet de eerstvolgende scan er weer de bestandsnaam overheen, en
    # bij een scanlation is dat vaak de naam van de tekenaar of "Chapter 12".
    title_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Welke aflevering dit ís, los van de uitgave. Normaal afgeleid van het
    # nummer, zodat hoofdstuk 5 uit de gekleurde en de zwart-witte uitgave
    # hetzelfde vakje vullen. Handmatig te zetten voor boeken zonder nummer:
    # drie drukken van één boek horen ook bij elkaar.
    slot: Mapped[str | None] = mapped_column(String(200), default=None)

    page_count: Mapped[int | None] = mapped_column(Integer, default=None)
    right_to_left: Mapped[bool] = mapped_column(Boolean, default=False)

    # De omslag van dít deel bij de bron. MangaDex heeft er meestal één per
    # volume; zonder dit zou elk deel "pagina 1" tonen, en dat is bij
    # scanlations vaak een credits-pagina van de vertaalgroep.
    cover_url: Mapped[str | None] = mapped_column(String(500), default=None)

    # M5: geabonneerde hoofdstukken zonder lokaal bestand.
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("source.id", ondelete="SET NULL"), default=None
    )
    source_ref: Mapped[str | None] = mapped_column(String(200), default=None)
    # Wie heeft dit vertaald? Bij bronnen met meerdere vertalingen van dezelfde
    # aflevering is dit het enige onderscheid — nummer en omvang zijn gelijk.
    source_group_id: Mapped[str | None] = mapped_column(String(200), default=None)
    source_group_name: Mapped[str | None] = mapped_column(String(200), default=None)
    # Bij een readahead-download: wanneer mag dit bestand weer weg?
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    series: Mapped[Series] = relationship(back_populates="books")
    file: Mapped[File | None] = relationship(back_populates="book")
    progress: Mapped[list[Progress]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_book_series_sort", "series_id", "sort_volume", "sort_number"),
    )


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Progress(Base):
    """Leespositie. Eén endpoint voor alle clients, dus één waarheid.

    ``position`` is bewust vormvrij: ``{"page": 12}`` voor comics, een CFI voor
    epub. ``percent`` is de gemene deler waarop alle clients kunnen sorteren.
    """

    __tablename__ = "progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id", ondelete="CASCADE"))

    position: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    percent: Mapped[float] = mapped_column(Float, default=0.0)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    device: Mapped[str | None] = mapped_column(String(100), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    book: Mapped[Book] = relationship(back_populates="progress")

    __table_args__ = (UniqueConstraint("user_id", "book_id", name="uq_progress_user_book"),)


class Tab(Base):
    """M3. Een tab is een naam plus een regelboom die naar SQL gecompileerd wordt."""

    __tablename__ = "tab"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str | None] = mapped_column(String(60), default=None)
    position: Mapped[int] = mapped_column(Integer, default=0)
    rule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    view_mode: Mapped[str] = mapped_column(String(20), default="grid")
    group_by: Mapped[str | None] = mapped_column(String(20), default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Collection(Base):
    """M3. Slimme collecties gebruiken dezelfde regel-engine als tabs."""

    __tablename__ = "collection"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    smart: Mapped[bool] = mapped_column(Boolean, default=True)
    rule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    group_by: Mapped[str | None] = mapped_column(String(20), default=None)


class Source(Base):
    """M5. Een externe bron zoals MangaDex."""

    __tablename__ = "source"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Subscription(Base):
    """M5. Een gevolgde serie, met beleid voor lokaal downloaden."""

    __tablename__ = "subscription"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"))
    policy: Mapped[SubscriptionPolicy] = mapped_column(
        _enum(SubscriptionPolicy, "subscription_policy"), default=SubscriptionPolicy.READAHEAD
    )
    readahead_n: Mapped[int] = mapped_column(Integer, default=3)
    ttl_days: Mapped[int] = mapped_column(Integer, default=14)
    # Welke reeks bij de bron dit abonnement volgt. Staat ook op Series, maar
    # dat veld kan er maar één bevatten: zodra een serie meerdere abonnementen
    # heeft — een gekleurde uitgave naast de zwart-witte — hoort elk zijn eigen
    # bron-reeks te onthouden. Leeg betekent: die van de serie.
    source_ref: Mapped[str | None] = mapped_column(String(200), default=None)
    # In welke taal je deze reeks volgt. Nodig omdat je er meerdere naast
    # elkaar kunt hebben: van Shinya Shokudo is maar een klein deel vertaald,
    # dus de Engelse uitgave voorop en het Japanse origineel eronder om de rest
    # te kunnen lezen. Zonder dit veld haalt de achtergrondronde altijd Engels
    # op en klapt het Japanse abonnement bij de eerste ronde om.
    language: Mapped[str] = mapped_column(String(8), default="en")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Welke vertaalgroep je wilt lezen. Leeg = automatisch kiezen (de groep die
    # het grootste deel van de reeks heeft gedaan). Zelf kiezen is nodig omdat
    # "de meeste hoofdstukken" niet hetzelfde is als "de mooiste vertaling".
    preferred_group_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # Wat er bij de laatste ronde te kiezen viel: [{"id", "name", "chapters"}].
    # Opgeslagen zodat de UI een keuzelijst kan tonen zonder de bron te
    # bevragen — na het ontdubbelen bestaan de afgevallen hoofdstukken hier
    # namelijk niet meer als boek.
    available_groups: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class DownloadJob(Base):
    __tablename__ = "download_job"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id", ondelete="CASCADE"))
    state: Mapped[JobState] = mapped_column(_enum(JobState, "job_state"), default=JobState.PENDING)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Translation(Base):
    """M6/M8. Vertaalresultaat, gecached zodat een pagina maar één keer door de
    OCR- en vertaalmolen hoeft.

    ``page_index`` is NULL voor een heel epub-hoofdstuk, gevuld voor een
    stripbladzijde met tekstwolkjes.
    """

    __tablename__ = "translation"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id", ondelete="CASCADE"))
    page_index: Mapped[int | None] = mapped_column(Integer, default=None)
    target_lang: Mapped[str] = mapped_column(String(8))
    provider: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "book_id", "page_index", "target_lang", "provider", name="uq_translation_target"
        ),
    )


class TrackerAccount(Base):
    """M7. MyAnimeList of Goodreads. ``dry_run`` staat standaard aan zodat je
    eerst ziet wat er gepusht zou worden."""

    __tablename__ = "tracker_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), unique=True)
    credentials: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Setting(Base):
    """Vrije sleutel/waarde-opslag, o.a. voor de Nickel-integratie uit M2."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
