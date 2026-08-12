"""Bron naar datamodel: abonneren en hoofdstukken binnenhalen (M5).

Het kernidee uit het datamodel: een ``Book`` heeft een bestand **of** een
bron-referentie. Abonneren maakt dus boeken zonder bestand aan; downloaden vult
er een bestand bij zonder de bron-referentie weg te gooien. Daardoor kan de
TTL-opruiming een bestand later weer weghalen zonder dat het hoofdstuk
verdwijnt uit je bibliotheek.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.formats import FORMAT_KINDS, detect_format, open_book
from bookpal.formats.base import UnsupportedOperation
from bookpal.library import editions
from bookpal.metadata.filename import sort_title
from bookpal.metadata.origin import Origin, from_online, resolve
from bookpal.metadata.titles import normalise
from bookpal.models import (
    Book,
    BookKind,
    Edition,
    File,
    LibraryRoot,
    Progress,
    Series,
    Source,
    Subscription,
    SubscriptionPolicy,
    utcnow,
)
from bookpal.sources import ChapterInfo, SearchResult
from bookpal.sources import Source as SourceImpl
from bookpal.sources.base import SourceError

logger = logging.getLogger(__name__)

#: Naam van de map waarin gedownloade hoofdstukken belanden.
DOWNLOAD_ROOT_NAME = "Downloads"

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text: str, *, fallback: str = "zonder-titel", limit: int = 120) -> str:
    """Een titel als mapnaam, zonder tekens die een bestandssysteem breken."""
    cleaned = _UNSAFE.sub("", text).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:limit].strip() or fallback)


def download_root(session: Session) -> LibraryRoot:
    """De library-root voor downloads, aangemaakt als hij nog niet bestaat.

    Bewust een gewone root: gedownloade hoofdstukken lopen daarna door
    dezelfde scanner, formats en beeldpipeline als je eigen bestanden.
    """
    path = str(settings.download_dir.resolve())
    root = session.scalar(select(LibraryRoot).where(LibraryRoot.path == path))
    if root is None:
        settings.download_dir.mkdir(parents=True, exist_ok=True)
        root = LibraryRoot(name=DOWNLOAD_ROOT_NAME, path=path)
        session.add(root)
        session.flush()
    return root


def find_existing(session: Session, result: SearchResult) -> Series | None:
    """De serie die je hier al van hebt, ook als hij net anders heet.

    "Shinya Shokudou" bij de bron en "Shinya Shokudo" in jouw map zijn hetzelfde
    ding; alleen de romanisering verschilt. Zonder deze stap komt er een tweede
    serie naast te staan die je daarna met de hand moet samenvoegen — terwijl je
    juist een bron aan het toevoegen was aan wat je al hebt.

    Alleen op titel en niet op iets slimmers: dat is wat jij ook ziet, en het
    valt met één blik te controleren. Wat je aan de verkeerde plakt haal je met
    het losmaken van de uitgave weer uit elkaar.
    """
    gezocht = normalise(result.title)
    if not gezocht:
        return None
    for series in session.scalars(select(Series)):
        if normalise(series.title) == gezocht:
            return series
    return None


def upsert_series(session: Session, source: Source, result: SearchResult) -> Series:
    """Maak of werk de serie bij die bij een bron-treffer hoort."""
    series = session.scalar(
        select(Series).where(Series.source_id == source.id, Series.source_ref == result.ref)
    )
    if series is None:
        # Nog geen serie voor déze reeks; misschien heb je hem al onder een
        # net andere titel staan. Dan hoort dit een uitgave erbij te worden.
        series = find_existing(session, result)
    if series is None:
        series = Series(
            title=result.title,
            sort_title=sort_title(result.title),
            library_root_id=download_root(session).id,
            source_id=source.id,
            source_ref=result.ref,
        )
        session.add(series)
        # Direct flushen, net als de scanner doet: column-defaults (tags,
        # tracker_ids) worden pas dan gevuld.
        session.flush()
    elif series.source_id is None:
        # Een serie uit je eigen mappen die nu ook een bron krijgt. De
        # verwijzing per abonnement is leidend; deze twee velden blijven voor
        # alles wat maar één bron kent.
        series.source_id = source.id
        series.source_ref = result.ref

    series.summary = result.description or series.summary
    if result.cover_url:
        series.cover_url = result.cover_url
    if result.authors:
        # Samenvoegen zoals de scanner dat doet, zodat een auteur uit ComicInfo
        # niet verdwijnt zodra dezelfde serie ook bij een bron staat.
        series.authors = list(dict.fromkeys([*(series.authors or []), *result.authors]))
    if result.tracker_ids:
        # Let op de `or {}`: column-defaults vullen pas bij het flushen, dus op
        # een net aangemaakte serie staat hier nog None.
        series.tracker_ids = {**(series.tracker_ids or {}), **result.tracker_ids}

    # Stap 2 van de herkomst-keten. resolve() weegt dit tegen wat er al staat,
    # dus een handmatige keuze blijft vanzelf overeind.
    if result.original_language:
        current = Origin(
            series.origin_language,
            series.origin_country,
            series.origin_region,
            series.origin_source,
        )
        chosen = resolve(from_online(result.original_language), current=current)
        series.origin_language = chosen.language
        series.origin_country = chosen.country
        series.origin_region = chosen.region
        series.origin_source = chosen.source

    session.flush()
    return series


def group_summary(chapters: list[ChapterInfo]) -> list[dict[str, Any]]:
    """Welke vertaalgroepen zitten er in deze reeks, en hoeveel doen ze?

    Wordt op het abonnement bewaard zodat de UI een keuzelijst kan tonen: na
    het ontdubbelen bestaan de afgevallen hoofdstukken niet meer als boek, dus
    daar valt niet meer uit af te leiden wat er te kiezen viel.
    """
    counts: dict[str | None, dict[str, Any]] = {}
    for chapter in chapters:
        if chapter.group_id is None:
            continue
        entry = counts.setdefault(
            chapter.group_id,
            {"id": chapter.group_id, "name": chapter.group_name or chapter.group_id, "chapters": 0},
        )
        entry["chapters"] = int(entry["chapters"]) + 1
    return sorted(counts.values(), key=lambda item: -int(item["chapters"]))


def pick_best_chapters(
    chapters: list[ChapterInfo], preferred_group_id: str | None = None
) -> list[ChapterInfo]:
    """Bij dubbele afleveringen er één kiezen.

    Een bron kan dezelfde aflevering meerdere keren hebben, vertaald door
    verschillende groepen — Oishinbo heeft 276 van zulke paren, met identiek
    volume, nummer én paginatelling. Nummer of omvang helpt dus niet; wie het
    vertaald heeft wel.

    Met ``preferred_group_id`` wint die groep overal waar hij iets heeft. Dat
    is er omdat "de meeste hoofdstukken" niet hetzelfde is als "de mooiste
    vertaling"; die afweging kan alleen de lezer maken.

    Zonder voorkeur valt de keuze op **consistentie**: de groep die het
    grootste deel van de reeks heeft gedaan wint. Je leest dan één vertaling in
    plaats van een mengelmoes van stijl en naamgeving, en alleen waar die groep
    niets heeft val je terug op een andere. Bij gelijke stand wint de nieuwste
    upload, en anders de laagste ref — zodat een tweede ronde dezelfde keuze
    maakt en er niets gaat wisselen.
    """
    per_group: dict[str | None, int] = {}
    for chapter in chapters:
        per_group[chapter.group_id] = per_group.get(chapter.group_id, 0) + 1

    def weight(chapter: ChapterInfo) -> int:
        # De voorkeur telt zwaarder dan welke telling ook, maar alleen voor de
        # afleveringen die die groep daadwerkelijk heeft.
        if preferred_group_id is not None and chapter.group_id == preferred_group_id:
            return len(chapters) + 1
        return per_group.get(chapter.group_id, 0)

    def is_better(candidate: ChapterInfo, current: ChapterInfo) -> bool:
        candidate_group = weight(candidate)
        current_group = weight(current)
        if candidate_group != current_group:
            return candidate_group > current_group
        if (candidate.published_at or "") != (current.published_at or ""):
            return (candidate.published_at or "") > (current.published_at or "")
        # Laatste redmiddel: een vaste volgorde, zodat een tweede ronde
        # dezelfde keuze maakt en er niets omwisselt.
        return candidate.ref < current.ref

    best: dict[tuple[str | None, str | None], ChapterInfo] = {}
    for chapter in chapters:
        key = (chapter.volume, chapter.number)
        current = best.get(key)
        if current is None or is_better(chapter, current):
            best[key] = chapter

    chosen = set(best.values())
    return [chapter for chapter in chapters if chapter in chosen]


# Bronnen zetten het in de titel: "One Piece (Official Colored)". Dat is het
# enige signaal dat er is — of een scan kleur heeft valt niet aan de metadata te
# zien, en elke pagina bekijken is er niet aan.
_COLOUR_IN_TITLE = re.compile(r"\b(colou?red|colou?r|kleur)\b", re.IGNORECASE)


def edition_note(source_title: str | None) -> str | None:
    """Een kort label bij de uitgave, als de bron het prijsgeeft."""
    if source_title and _COLOUR_IN_TITLE.search(source_title):
        return "kleur"
    return None


def _edition_name(
    session: Session, series: Series, subscription: Subscription, source_title: str | None
) -> str:
    """Hoe deze uitgave heet in de lijst.

    Bij voorkeur de titel zoals de bron hem noemt: "Dragon Ball Super (Coloured
    Edition)" naast "Dragon Ball Super" zegt precies wat het onderscheid is,
    terwijl jouw eigen serietitel voor beide hetzelfde is.

    De taal komt er alleen bij als hij nodig is om ze uit elkaar te houden —
    dezelfde reeks in het Engels en het Japans levert anders twee regels met
    exact dezelfde naam.
    """
    naam = source_title or series.title
    bezet = {
        edition.name
        for edition in session.scalars(
            select(Edition).where(
                Edition.series_id == series.id, Edition.subscription_id != subscription.id
            )
        )
    }
    return f"{naam} · {subscription.language}" if naam in bezet else naam


def sync_chapters(
    session: Session,
    series: Series,
    chapters: list[ChapterInfo],
    *,
    subscription: Subscription | None = None,
    source_title: str | None = None,
) -> tuple[int, int]:
    """Zet de hoofdstukkenlijst van een bron om in boeken zonder bestand.

    Geeft (nieuw, ongewijzigd) terug. Bestaande boeken worden niet aangeraakt,
    ook niet als ze inmiddels een bestand hebben.

    Dubbele afleveringen zijn er al uit voordat er iets wordt aangemaakt; zie
    ``pick_best_chapters``. Staat er een voorkeursgroep op het abonnement, dan
    wint die. Eerder aangemaakte dubbelen worden opgeruimd, maar alleen als ze
    niets kosten: een aflevering die al is opgehaald of waarin gelezen is,
    blijft staan. Anders zou een verandering in de bron — of het omzetten van
    je voorkeur — zomaar iets weghalen wat je al had.
    """
    edition: Edition | None = None
    if subscription is not None:
        # Vastleggen wat er te kiezen viel, vóór het ontdubbelen: daarna
        # bestaan de afgevallen hoofdstukken niet meer.
        subscription.available_groups = group_summary(chapters)
        # Alles van deze bron hoort bij één uitgave. Zo blijft "de gekleurde
        # versie" bij elkaar als er straks een tweede bron bij komt.
        edition = editions.for_subscription(
            session,
            series,
            subscription,
            name=_edition_name(session, series, subscription, source_title),
        )
        # Alleen invullen als je er zelf nog niets van gemaakt hebt.
        if edition.note is None:
            edition.note = edition_note(source_title)

    preferred = subscription.preferred_group_id if subscription is not None else None
    chapters = pick_best_chapters(chapters, preferred)
    keep = {chapter.ref for chapter in chapters}

    # Alleen de hoofdstukken van déze uitgave. Een serie kan er meer hebben —
    # een Engelse vertaling naast het Japanse origineel — en die horen niet als
    # "niet meer bij de bron" te worden opgeruimd wanneer de ander synchroniseert.
    statement = select(Book).where(Book.series_id == series.id)
    if edition is not None:
        statement = statement.where(
            or_(Book.edition_id == edition.id, Book.edition_id.is_(None))
        )
    existing = {
        book.source_ref: book for book in session.scalars(statement) if book.source_ref
    }

    for ref, book in list(existing.items()):
        if ref in keep or book.file_id is not None:
            continue
        has_progress = session.scalar(
            select(Progress.id).where(Progress.book_id == book.id).limit(1)
        )
        if has_progress:
            continue
        session.delete(book)
        del existing[ref]

    added = 0
    for chapter in chapters:
        known = existing.get(chapter.ref)
        if known is not None:
            # Groep bijwerken op wat er al stond: bestaande boeken van vóór
            # deze kolommen weten nog niet wie ze vertaald heeft.
            known.source_group_id = known.source_group_id or chapter.group_id
            known.source_group_name = known.source_group_name or chapter.group_name
            # Hoofdstukken van vóór dit model horen alsnog bij hun uitgave.
            if known.edition_id is None and edition is not None:
                known.edition_id = edition.id
            continue
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title=chapter.title or _default_title(chapter),
                number=chapter.number,
                volume=chapter.volume,
                sort_number=_sort_number(chapter.number),
                sort_volume=_sort_number(chapter.volume),
                page_count=chapter.page_count,
                # Manga leest van rechts naar links; dat is bij een
                # manga-bron de juiste aanname.
                right_to_left=True,
                source_id=series.source_id,
                source_ref=chapter.ref,
                source_group_id=chapter.group_id,
                source_group_name=chapter.group_name,
                edition_id=edition.id if edition is not None else None,
            )
        )
        added += 1
    session.flush()
    return added, len(existing)


def _default_title(chapter: ChapterInfo) -> str:
    parts = []
    if chapter.volume:
        parts.append(f"Vol. {chapter.volume}")
    if chapter.number:
        parts.append(f"Hoofdstuk {chapter.number}")
    return " ".join(parts) or "Hoofdstuk"


def _sort_number(number: str | None) -> float:
    try:
        return float(number) if number is not None else 0.0
    except ValueError:
        return 0.0


def attach_cover(series: Series, implementation: SourceImpl, ref: str) -> Series:
    """Koppel de officiële omslag van een bron aan een bestaande, lokale serie.

    Bewust geen ``upsert_series``: die zoekt en maakt series op
    ``(source_id, source_ref)``, en een lokale serie heeft dat paar niet — die
    zou dan een tweede, lege serie krijgen in plaats van zijn eigen omslag.
    Dit raakt daarom alleen de metadata die je hier komt halen — omslag en
    auteur; de serie blijft "lokaal", er komt geen abonnement of
    bron-referentie bij.
    """
    detail = implementation.detail(ref)
    if not detail.cover_url:
        raise SourceError(f"{detail.title} heeft geen omslag bij deze bron")
    series.cover_url = detail.cover_url
    if detail.authors:
        # We hebben het detail-antwoord toch al binnen; een lokale strip- of
        # mangamap heeft zelden ComicInfo met een schrijver erin.
        series.authors = list(dict.fromkeys([*(series.authors or []), *detail.authors]))
    return series


def subscribe(
    session: Session,
    source_row: Source,
    implementation: SourceImpl,
    ref: str,
    *,
    policy: SubscriptionPolicy = SubscriptionPolicy.READAHEAD,
    readahead_n: int = 3,
    ttl_days: int = 14,
    language: str = "en",
) -> tuple[Series, Subscription, int]:
    """Volg een serie: serie + hoofdstukken aanmaken en het abonnement vastleggen."""
    detail = implementation.detail(ref)
    series = upsert_series(session, source_row, detail)


    # Het abonnement moet er zijn vóór het synchroniseren: daar staat de
    # voorkeursgroep op, en die bepaalt welke vertaling er wordt aangemaakt.
    # Ook op taal, want twee talen naast elkaar is een geldige wens: van
    # Shinya Shokudo is maar een klein deel vertaald, dus de Engelse uitgave
    # voorop en het Japanse origineel eronder om verder te kunnen lezen. Zonder
    # de taal in de sleutel zou het tweede abonnement het eerste overschrijven.
    subscription = session.scalar(
        select(Subscription).where(
            Subscription.source_id == source_row.id,
            Subscription.series_id == series.id,
            Subscription.language == language,
        )
    )
    if subscription is None:
        subscription = Subscription(
            source_id=source_row.id, series_id=series.id, language=language
        )
        session.add(subscription)
    # Altijd bijwerken: bij een serie met meerdere abonnementen is dit het
    # enige dat vastlegt wélke reeks bij de bron dít abonnement volgt.
    subscription.source_ref = ref
    subscription.policy = policy
    subscription.readahead_n = readahead_n
    subscription.ttl_days = ttl_days
    subscription.last_checked_at = utcnow()
    session.flush()

    chapters = implementation.chapters(ref, language=language)
    added, _ = sync_chapters(
        session, series, chapters, subscription=subscription, source_title=detail.title
    )
    session.flush()

    # Omslagen erbij, nu de delen bestaan. Zonder dit toont elk deel "pagina 1",
    # en dat is bij scanlations vaak een credits-pagina van de vertaalgroep.
    edition = session.scalar(select(Edition).where(Edition.subscription_id == subscription.id))
    sync_covers(session, implementation, series, ref=ref, edition=edition)
    session.flush()
    return series, subscription, added


def chapter_path(series: Series, book: Book) -> Path:
    """Waar een gedownload hoofdstuk komt te staan.

    Absoluut, want ``File.path`` is elders in de app ook absoluut en
    ``download_root`` legt de root met een opgelost pad vast.

    Volume en nummer alleen zijn níét uniek: een bron kan meerdere vertalingen
    van hetzelfde hoofdstuk hebben (Oishinbo heeft er honderden, "Tofu & Water"
    naast "Tofu and Water"). Die kregen dan hetzelfde pad, en omdat ``file_id``
    uniek is per boek liep de tweede download stuk op de database. Daarom staat
    de bron-referentie in de naam — kort, maar genoeg om te onderscheiden, en
    deterministisch zodat opnieuw ophalen op hetzelfde pad uitkomt.
    """
    parts = []
    if book.volume:
        parts.append(f"v{book.volume}")
    if book.number:
        parts.append(f"c{book.number}")
    if book.source_ref:
        parts.append(f"[{book.source_ref[:8]}]")
    stem = " ".join(parts) or str(book.id)
    # ``.cbz`` is een beginwaarde, geen belofte: een bron die hele bestanden
    # levert kan net zo goed een pdf of epub geven. ``download`` geeft terug
    # waar hij het écht heeft neergezet.
    return settings.download_dir.resolve() / safe_name(series.title) / f"{safe_name(stem)}.cbz"


def download_book(
    session: Session,
    implementation: SourceImpl,
    book: Book,
    *,
    data_saver: bool = False,
    temporary: bool = False,
    ttl_days: int = 14,
) -> Book:
    """Haal één hoofdstuk binnen en hang het bestand aan het boek.

    ``temporary`` zet een vervaldatum: dat is het "tijdelijk downloaden om
    vooruit te lezen" uit het datamodel. De bron-referentie blijft staan, dus
    na het opruimen is het hoofdstuk nog steeds zichtbaar — alleen niet meer
    lokaal.
    """
    if book.source_ref is None:
        raise SourceError("dit boek heeft geen bron-referentie om te downloaden")

    # Een file_id alleen zegt niets: het bestand kan weg zijn (opgeruimd,
    # volume kwijt, handmatig verwijderd). Alleen overslaan als het er echt
    # nog staat, anders halen we het gewoon opnieuw op.
    if book.file_id is not None:
        existing = session.get(File, book.file_id)
        if existing is not None and Path(existing.path).is_file():
            return book

    series = session.get(Series, book.series_id)
    if series is None:
        raise SourceError("serie niet gevonden")

    target = chapter_path(series, book)
    # De bron bepaalt de extensie: hij weet welk bestand hij ophaalt. Zonder dit
    # kwam een pdf van het Internet Archive als ".cbz" op schijf te staan, en
    # dan opent er niets — het is geen zip.
    target = implementation.download(book.source_ref, target, data_saver=data_saver)

    # Uitlezen wat er nu op schijf staat. Zonder dit weet de lezer niet hoeveel
    # pagina's er zijn — en bij een bron die hele bestanden levert weet hij ook
    # niet dat het een pdf is in plaats van een strip. Beide komen anders pas
    # bij de eerstvolgende scan goed, en tot dan opent het hoofdstuk niet.
    fmt = detect_format(target)
    if fmt is not None:
        book.kind = FORMAT_KINDS[fmt]
        try:
            with open_book(target, fmt) as bestand:
                book.page_count = bestand.page_count()
        except (OSError, UnsupportedOperation, ValueError) as exc:
            logger.warning("paginatelling van %s: %s", target.name, exc)

    stat = target.stat()
    file_row = session.scalar(select(File).where(File.path == str(target)))
    if file_row is not None:
        # Eén bestand hoort bij één boek (``Book.file_id`` is uniek). Als een
        # ander boek dit pad al claimt, klopt de padberekening niet — zeg dat
        # dan hardop in plaats van de database er tegenaan te laten lopen.
        claimed_by = session.scalar(select(Book).where(Book.file_id == file_row.id))
        if claimed_by is not None and claimed_by.id != book.id:
            raise SourceError(
                f"pad {target.name} hoort al bij hoofdstuk {claimed_by.id}; "
                "twee hoofdstukken leveren dezelfde bestandsnaam op"
            )
    if file_row is None:
        file_row = File(
            library_root_id=download_root(session).id,
            path=str(target),
            size=stat.st_size,
            mtime=stat.st_mtime,
            extension=".cbz",
        )
        session.add(file_row)
        session.flush()
    else:
        file_row.size = stat.st_size
        file_row.mtime = stat.st_mtime
        file_row.missing = False

    book.file_id = file_row.id
    book.expires_at = utcnow() + timedelta(days=ttl_days) if temporary else None
    session.flush()
    logger.info("hoofdstuk %s opgehaald naar %s", book.source_ref, target)
    return book


def expire_downloads(session: Session, *, now: datetime | None = None) -> int:
    """Ruim tijdelijke downloads op waarvan de TTL voorbij is.

    Het bestand gaat weg, het boek blijft: de bron-referentie maakt het straks
    opnieuw op te halen.
    """
    moment = now or utcnow()
    expired = session.scalars(
        select(Book).where(
            Book.expires_at.isnot(None),
            Book.expires_at <= moment,
            Book.file_id.isnot(None),
        )
    ).all()

    removed = 0
    for book in expired:
        file_row = session.get(File, book.file_id) if book.file_id else None
        if file_row is not None:
            Path(file_row.path).unlink(missing_ok=True)
            session.delete(file_row)
        book.file_id = None
        book.expires_at = None
        removed += 1
    session.flush()
    return removed


def sync_covers(
    session: Session,
    implementation: SourceImpl,
    series: Series,
    *,
    ref: str | None = None,
    edition: Edition | None = None,
) -> int:
    """Haal de omslagen per deel op en hang ze aan de bijbehorende boeken.

    MangaDex heeft er meestal één per volume. Zonder dit toont elk deel
    "pagina 1", en dat is bij scanlations vaak een credits-pagina van de
    vertaalgroep in plaats van de echte omslag.

    ``ref`` en ``edition`` horen bij elkaar: bij een serie met meerdere
    uitgaven hoort de gekleurde omslag alleen bij de gekleurde delen.

    Faalt zacht: een serie zonder omslagen is nog steeds prima leesbaar.
    """
    getter = getattr(implementation, "covers", None)
    ref = ref or series.source_ref
    if getter is None or not ref:
        return 0

    try:
        covers = getter(ref)
    except SourceError as exc:
        logger.warning("omslagen ophalen voor %s: %s", series.title, exc)
        return 0

    per_volume = {cover.volume: cover.url for cover in covers if cover.volume}
    if not per_volume:
        return 0

    statement = select(Book).where(Book.series_id == series.id)
    if edition is not None:
        statement = statement.where(Book.edition_id == edition.id)

    aantal = 0
    for book in session.scalars(statement):
        url = per_volume.get(book.volume) if book.volume else None
        if url and book.cover_url != url:
            book.cover_url = url
            aantal += 1
    return aantal
