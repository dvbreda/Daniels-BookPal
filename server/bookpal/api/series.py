"""Series doorbladeren."""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Any, NamedTuple, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.formats.base import UnsupportedOperation
from bookpal.images import (
    ImageProfile,
    RenderedImage,
    open_source,
    render_cover,
    render_page,
    render_remote_cover,
    source_id_for,
)
from bookpal.library import editions, groups, sidecars
from bookpal.library import merge as merge_module
from bookpal.metadata.filename import normalise_number as _sort_number
from bookpal.metadata.filename import sort_title as sort_title_for
from bookpal.metadata.titles import normalise
from bookpal.models import (
    Book,
    BookKind,
    Edition,
    File,
    LibraryRoot,
    OriginRegion,
    OriginSource,
    Progress,
    Series,
    Source,
    Subscription,
    User,
)
from bookpal.schemas import (
    AttachCoverIn,
    BookAlternativeOut,
    BookOut,
    BookSlotIn,
    ContinueOut,
    EditionOrderIn,
    EditionOut,
    EditionPatch,
    ImportSeriesIn,
    ImportSeriesOut,
    MarkReadBeforeOut,
    MergeCandidateOut,
    MergeSeriesIn,
    MergeSuggestionOut,
    OriginPatch,
    Paginated,
    SeriesDetailOut,
    SeriesOut,
    SeriesRenameIn,
    SeriesRenameOut,
    SetCoverPageIn,
    SyncCoversOut,
)
from bookpal.sources import SourceError, importer
from bookpal.sources import service as source_service

from . import deps

router = APIRouter(prefix="/api/series", tags=["series"])


SelectT = TypeVar("SelectT", bound=Select[Any])


def _apply_filters(
    statement: SelectT,
    *,
    root_id: int | None,
    region: OriginRegion | None,
    kind: BookKind | None,
    group: groups.SeriesGroup | None,
    search: str | None,
) -> SelectT:
    if root_id is not None:
        statement = statement.where(Series.library_root_id == root_id)
    if region is not None:
        statement = statement.where(Series.origin_region == region)
    if kind is not None:
        statement = statement.where(Series.books.any(Book.kind == kind))
    if group is not None:
        statement = statement.where(groups.condition(group))
    if search:
        statement = statement.where(Series.title.ilike(f"%{search}%"))
    return statement


class SeriesSort(enum.StrEnum):
    """Waarop de bibliotheek gesorteerd staat."""

    NAAM = "naam"
    VERSCHENEN = "verschenen"
    TOEGEVOEGD = "toegevoegd"


def _geordend(statement: SelectT, sort: SeriesSort, *, omgekeerd: bool = False) -> SelectT:
    """De volgorde. Altijd met de titel als laatste sleutel, zodat twee series
    uit hetzelfde jaar niet bij elke aanroep van plek wisselen.

    Op verschijningsjaar sorteert een serie op haar nieuwste deel: dat is wat
    "wat is hier het recentst" betekent bij een tijdschrift met dertig
    jaargangen. Series zonder datum gaan achteraan in plaats van vooraan —
    onbekend is geen 1900.
    """
    # Elke sortering heeft een natuurlijke kant: namen lopen van A naar Z,
    # data van nieuw naar oud. `omgekeerd` klapt precies dát om, zodat de knop
    # doet wat je verwacht ongeacht waarop je sorteert.
    if sort is SeriesSort.NAAM:
        titel = Series.sort_title.desc() if omgekeerd else Series.sort_title
        return statement.order_by(titel)

    if sort is SeriesSort.TOEGEVOEGD:
        nieuwste = (
            select(func.max(Book.added_at)).where(Book.series_id == Series.id).scalar_subquery()
        )
        volgorde = nieuwste.asc().nulls_last() if omgekeerd else nieuwste.desc().nulls_last()
        return statement.order_by(volgorde, Series.sort_title)

    jaar = (
        select(func.max(Book.published_year)).where(Book.series_id == Series.id).scalar_subquery()
    )
    volgorde = jaar.asc().nulls_last() if omgekeerd else jaar.desc().nulls_last()
    return statement.order_by(volgorde, Series.sort_title)


@router.get("", response_model=Paginated[SeriesOut])
def list_series(
    root_id: int | None = None,
    region: OriginRegion | None = None,
    kind: BookKind | None = None,
    group: groups.SeriesGroup | None = None,
    search: str | None = Query(default=None, max_length=200),
    sort: SeriesSort = SeriesSort.NAAM,
    desc: bool = Query(default=False, description="De sorteervolgorde omkeren."),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=500),
    session: Session = Depends(get_session),
) -> Paginated[SeriesOut]:
    """Bladeren met de filters die M3 straks als regelboom automatiseert.

    Nu nog losse query-parameters; de tab-regels compileren later naar precies
    deze where-clausules. ``group`` is de grove indeling van de startpagina —
    zie `bookpal.library.groups` waarom die niet in de client kan.
    """
    base = _apply_filters(
        select(Series), root_id=root_id, region=region, kind=kind, group=group, search=search
    )
    total = session.scalar(
        _apply_filters(
            select(func.count(Series.id)),
            root_id=root_id,
            region=region,
            kind=kind,
            group=group,
            search=search,
        )
    )
    rows = session.scalars(
        _geordend(base, sort, omgekeerd=desc).offset(offset).limit(limit)
    ).all()
    items = deps.series_out_list(session, list(rows))

    return Paginated(items=items, total=int(total or 0), offset=offset, limit=limit)


@router.get("/{series_id}", response_model=SeriesDetailOut)
def get_series(
    series_id: int,
    all_editions: bool = Query(
        default=False,
        description="Elk bestand apart tonen in plaats van één regel per aflevering.",
    ),
    session: Session = Depends(get_session),
) -> SeriesDetailOut:
    """Eén serie met zijn leeslijst.

    Standaard samengevouwen tot één regel per aflevering: heb je dezelfde reeks
    in kleur én zwart-wit, dan is hoofdstuk 5 één ding om te lezen. Met
    ``all_editions`` krijg je alles los, om te zien wat waar vandaan komt.
    """
    series = deps.get_series(session, series_id)
    user = current_user(session)
    books = list(series.books)
    uitgaven = list(series.editions)
    kenmerken = _edition_traits(session, uitgaven)
    progress = deps.progress_for(session, user, [book.id for book in books])
    extensions = {
        row.id: row.extension
        for row in session.scalars(
            select(File).where(File.id.in_([b.file_id for b in books if b.file_id]))
        )
    }

    detail = SeriesDetailOut(
        **deps.to_series_out(
            series, len(books), sorted({book.kind.value for book in books})
        ).model_dump()
    )

    gekozen: list[editions.Slot] = editions.slots(books, uitgaven)
    if all_editions:
        regels = [
            deps.to_book_out(book, progress.get(book.id), extensions.get(book.file_id or -1))
            for book in books
        ]
        for regel in regels:
            _apply_traits(regel, kenmerken.get(regel.edition_id or -1))
    else:
        regels = []
        for slot in gekozen:
            book = slot.chosen
            regel = deps.to_book_out(
                book,
                editions.best_progress(slot, progress),
                extensions.get(book.file_id or -1),
            )
            _apply_traits(regel, kenmerken.get(book.edition_id or -1))
            regel.alternatives = [
                _alternative_out(andere, kenmerken.get(andere.edition_id or -1))
                for andere in slot.alternatives
            ]
            regels.append(regel)

    detail.books = regels
    detail.editions = _editions_out(
        uitgaven, books, gekozen, {key: value.language for key, value in kenmerken.items()}
    )
    return detail


class _Traits(NamedTuple):
    """Waarin een uitgave zich onderscheidt, klaar om te tonen."""

    name: str
    language: str | None
    note: str | None


def _edition_traits(session: Session, uitgaven: list[Edition]) -> dict[int, _Traits]:
    """Naam, taal en label per uitgave.

    De taal staat op het abonnement en niet op de uitgave zelf: hij hoort bij
    waar de hoofdstukken vandaan komen, niet bij de ordening.
    """
    talen: dict[int, str] = {}
    ids = [edition.subscription_id for edition in uitgaven if edition.subscription_id]
    if ids:
        talen = {
            row.id: row.language
            for row in session.scalars(select(Subscription).where(Subscription.id.in_(ids)))
        }
    return {
        edition.id: _Traits(
            name=edition.name,
            language=talen.get(edition.subscription_id or -1),
            # Zelf gezet wint; anders afgeleid uit de naam, zodat uitgaven van
            # vóór dit label ook gewoon "kleur" tonen.
            note=edition.note or source_service.edition_note(edition.name),
        )
        for edition in uitgaven
    }


def _apply_traits(regel: BookOut, traits: _Traits | None) -> None:
    if traits is None:
        return
    regel.edition_name = traits.name
    regel.edition_language = traits.language
    regel.edition_note = traits.note


def _alternative_out(book: Book, traits: _Traits | None) -> BookAlternativeOut:
    return BookAlternativeOut(
        id=book.id,
        title=book.title,
        edition_id=book.edition_id,
        edition_name=traits.name if traits else None,
        edition_language=traits.language if traits else None,
        edition_note=traits.note if traits else None,
        has_file=book.file_id is not None,
    )


def _editions_out(
    uitgaven: list[Edition],
    books: list[Book],
    gekozen: list[editions.Slot],
    talen: dict[int, str | None] | None = None,
) -> list[EditionOut]:
    """De uitgaven met hun aandeel in de leeslijst.

    Dat aandeel is het nuttige getal: een uitgave die 0 van de 300 delen levert
    doet niets, en een die er 40 aanvult vertelt je precies waar je eerste keus
    ophoudt.
    """
    talen = talen or {}
    per_uitgave: dict[int, int] = {}
    for book in books:
        if book.edition_id is not None:
            per_uitgave[book.edition_id] = per_uitgave.get(book.edition_id, 0) + 1

    zichtbaar: dict[int, int] = {}
    for slot in gekozen:
        key = slot.chosen.edition_id
        if key is not None:
            zichtbaar[key] = zichtbaar.get(key, 0) + 1

    return [
        EditionOut(
            **{
                **{veld: getattr(edition, veld) for veld in ("id", "series_id", "name", "rank")},
                # Zelf gezet wint; anders afgeleid uit de naam, net als bij de
                # hoofdstukken zelf.
                "note": edition.note or source_service.edition_note(edition.name),
                "language": talen.get(edition.id),
                "subscription_id": edition.subscription_id,
                "folder_path": edition.folder_path,
                "book_count": per_uitgave.get(edition.id, 0),
                "chosen_count": zichtbaar.get(edition.id, 0),
            }
        )
        for edition in sorted(uitgaven, key=lambda edition: edition.rank)
    ]


@router.patch("/{series_id}/title", response_model=SeriesRenameOut)
def rename_series(
    series_id: int, payload: SeriesRenameIn, session: Session = Depends(get_session)
) -> SeriesRenameOut:
    """Hernoem een serie.

    Blijft staan bij een nieuwe scan: alleen de titel verandert, de mappen en
    bestanden blijven waar ze zijn.

    Kom je daarmee op de naam van een serie die je al hebt, dan komt die terug
    als ``merge_candidate``. Bijna altijd is dat hetzelfde ding — je bent
    tenslotte aan het opruimen — maar samenvoegen gebeurt pas als je het zegt.
    """
    series = deps.get_series(session, series_id)
    titel = payload.title.strip()
    if not titel:
        raise HTTPException(status_code=400, detail="een serie heeft een titel nodig")

    # Eerst kijken of de naam vrij is, dán pas opslaan. Binnen één map is de
    # titel uniek, dus een botsing is geen fout maar een aanwijzing: die andere
    # serie is bijna altijd hetzelfde ding.
    bezet = session.scalar(
        select(Series).where(
            Series.id != series.id,
            Series.library_root_id == series.library_root_id,
            Series.title == titel,
        )
    )
    if bezet is None:
        series.title = titel
        series.sort_title = sort_title_for(titel)
        session.commit()

    uit = SeriesRenameOut(
        **deps.to_series_out(
            series, len(series.books), sorted({book.kind.value for book in series.books})
        ).model_dump()
    )
    uit.renamed = bezet is None
    naamgenoot = bezet or _same_name(session, series, titel)
    if naamgenoot is not None:
        uit.merge_candidate = MergeCandidateOut(
            id=naamgenoot.id, title=naamgenoot.title, books=len(naamgenoot.books)
        )
    return uit


def _same_name(session: Session, series: Series, titel: str) -> Series | None:
    """Een andere serie die na normaliseren dezelfde naam heeft.

    Dezelfde vergelijking als bij het toevoegen van een bron, zodat "Shinya
    Shokudou" en "Shinya Shokudo" hier ook als één ding gelden.
    """
    gezocht = normalise(titel)
    if not gezocht:
        return None
    for andere in session.scalars(select(Series).where(Series.id != series.id)):
        if normalise(andere.title) == gezocht:
            return andere
    return None


def _remember_title(session: Session, book: Book, titel: str, *, lang: str) -> None:
    """Leg een opgehaalde titel vast in de sidecar naast het bestand."""
    if book.file_id is None:
        return
    bestand = session.get(File, book.file_id)
    if bestand is None:
        return
    pad = Path(bestand.path)
    if not pad.is_file():
        return
    zijkant = sidecars.read(pad) or sidecars.Sidecar()
    # Onder de taalcode én als naamloze titel: de eerste bewaart dat dit de
    # Engelse naam is, de tweede is wat je ziet als je niets vraagt.
    zijkant.titles[lang] = titel
    zijkant.set_title(titel, herkomst="source")
    sidecars.write(pad, zijkant)


@router.get("/{series_id}/similar", response_model=list[MergeCandidateOut])
def similar_series(
    series_id: int, session: Session = Depends(get_session)
) -> list[MergeCandidateOut]:
    """Series die op deze lijken, om samen te voegen.

    Staat permanent bij de instellingen: een dubbele serie ontstaat vanzelf —
    door een scan, door een bron met een net andere titel — en dan wil je erop
    gewezen worden in plaats van het zelf te moeten opmerken.
    """
    series = deps.get_series(session, series_id)
    return [
        MergeCandidateOut(id=andere.id, title=andere.title, books=len(andere.books))
        for andere in merge_module.similar(session, series)
    ]


@router.patch("/{series_id}/origin", response_model=SeriesOut)
def set_origin(
    series_id: int, payload: OriginPatch, session: Session = Depends(get_session)
) -> SeriesOut:
    """Handmatig de herkomst corrigeren.

    Dit zet ``origin_source`` op MANUAL, en dat is het hele punt: vanaf nu
    overschrijft geen enkele rescan of online-bron deze keuze meer.
    """
    series = deps.get_series(session, series_id)
    series.origin_language = payload.origin_language
    series.origin_country = payload.origin_country
    series.origin_region = payload.origin_region
    series.origin_source = OriginSource.MANUAL
    session.commit()

    book_count = int(
        session.scalar(select(func.count(Book.id)).where(Book.series_id == series.id)) or 0
    )
    return deps.to_series_out(series, book_count, [])


@router.post("/{series_id}/cover", response_model=SeriesOut)
def attach_cover(
    series_id: int, payload: AttachCoverIn, session: Session = Depends(get_session)
) -> SeriesOut:
    """Koppel de officiële omslag van een bron aan deze serie.

    Nuttig bij scanlaties: 'pagina 1 van hoofdstuk 1' is daar vaak een
    credits-pagina van de vertaalgroep over de echte omslag heen. Werkt ook
    voor een serie die je zelf hebt gescand — er komt geen abonnement bij,
    alleen de omslag zelf.
    """
    series = deps.get_series(session, series_id)
    source = deps.get_source_row(session, payload.source_id)
    implementation = deps.get_source_implementation(source)
    try:
        source_service.attach_cover(series, implementation, payload.ref)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # Een net gekozen bron-omslag mag niet verborgen blijven achter een oude
    # handmatige paginakeuze; die kan altijd terug via .../cover-page.
    series.cover_page_index = None
    session.commit()

    book_count = int(
        session.scalar(select(func.count(Book.id)).where(Book.series_id == series.id)) or 0
    )
    return deps.to_series_out(series, book_count, [])


@router.patch("/{series_id}/cover-page", response_model=SeriesOut)
def set_cover_page(
    series_id: int, payload: SetCoverPageIn, session: Session = Depends(get_session)
) -> SeriesOut:
    """Een vaste pagina van het eerste boek als omslag.

    Nuttig als er geen bron met een schone omslag bestaat, of als 'pagina 1'
    domweg niet de omslag is. Wint van een eerder gekoppelde bron-omslag —
    die blijft ondertussen bewaard en komt terug zodra je dit weer op de
    standaardkeuze zet (``page_index: null``).
    """
    series = deps.get_series(session, series_id)
    if payload.page_index is not None:
        first = series.books[0] if series.books else None
        if first is None:
            raise HTTPException(status_code=409, detail="deze serie heeft nog geen boeken")
        if first.kind is BookKind.EPUB:
            raise HTTPException(
                status_code=409,
                detail="een epub heeft geen vaste pagina's om als omslag te kiezen",
            )
        if first.page_count is not None and payload.page_index >= first.page_count:
            raise HTTPException(
                status_code=400,
                detail=f"pagina {payload.page_index} bestaat niet; {first.title} heeft er "
                f"{first.page_count}",
            )
    series.cover_page_index = payload.page_index
    session.commit()

    book_count = int(
        session.scalar(select(func.count(Book.id)).where(Book.series_id == series.id)) or 0
    )
    return deps.to_series_out(series, book_count, [])


@router.get("/{series_id}/cover")
def get_series_cover(
    series_id: int,
    profile: ImageProfile = deps.ProfileDep,
    session: Session = Depends(get_session),
) -> Response:
    """De omslag van deze serie: eerst een handmatig gekozen pagina, dan een
    omslag van de bron, dan pagina 1 van het eerste boek.

    Alle drie via dezelfde cache en beeldpipeline als elke andere afbeelding
    — dus ook grijswaarden en dithering voor de Kobo.
    """
    series = deps.get_series(session, series_id)

    if series.cover_page_index is not None:
        first = series.books[0] if series.books else None
        if first is not None and first.file_id is not None:
            path = deps.book_file_path(session, first)
            source = open_source(path)
            try:
                rendered = render_page(
                    source, series.cover_page_index, profile, source_id=source_id_for(path)
                )
                return _cover_response(rendered)
            except (IndexError, UnsupportedOperation):
                pass  # gekozen pagina bestaat niet meer; val terug

    if series.cover_url:
        try:
            rendered = render_remote_cover(
                series.cover_url, profile, source_id=f"series-cover:{series.id}:{series.cover_url}"
            )
        except UnsupportedOperation as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _cover_response(rendered)

    first = series.books[0] if series.books else None
    if first is not None and first.file_id is not None:
        path = deps.book_file_path(session, first)
        source = open_source(path)
        maybe_rendered = render_cover(source, profile, source_id=source_id_for(path))
        if maybe_rendered is not None:
            return _cover_response(maybe_rendered)

    raise HTTPException(status_code=404, detail="deze serie heeft nog geen omslag")


def _cover_response(rendered: RenderedImage) -> Response:
    return Response(
        content=rendered.data,
        media_type=rendered.media_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-BookPal-Cache": "hit" if rendered.from_cache else "miss",
        },
    )


def _readable_slots(session: Session, series_id: int) -> list[editions.Slot]:
    """De afleveringen in leesvolgorde, alleen wat je kunt openen.

    Eén regel per aflevering, niet per bestand: heb je dezelfde reeks in kleur
    én zwart-wit, dan is hoofdstuk 5 één ding om te lezen en niet twee. Welke
    uitgave je krijgt bepaalt de volgorde van de uitgaven.

    Hoofdstukken zonder bestand (een abonnement dat nog niet is opgehaald)
    vallen af: "lees verder" hoort je niet op een lege pagina te zetten.
    """
    books = list(
        session.scalars(
            select(Book)
            .where(Book.series_id == series_id)
            .order_by(Book.sort_volume, Book.sort_number)
        )
    )
    uitgaven = list(session.scalars(select(Edition).where(Edition.series_id == series_id)))
    return editions.readable(editions.slots(books, uitgaven))


def _all_slots(session: Session, series_id: int) -> list[editions.Slot]:
    """Alle afleveringen in leesvolgorde, opgehaald of niet."""
    books = list(
        session.scalars(
            select(Book)
            .where(Book.series_id == series_id)
            .order_by(Book.sort_volume, Book.sort_number)
        )
    )
    uitgaven = list(session.scalars(select(Edition).where(Edition.series_id == series_id)))
    return editions.slots(books, uitgaven)


def _readable_books(session: Session, series_id: int) -> list[Book]:
    return [slot.chosen for slot in _readable_slots(session, series_id)]


def _slot_progress(session: Session, user: User, slots: list[editions.Slot]) -> dict[int, Progress]:
    """Voortgang per aflevering, op de naam van het deel dat je te zien krijgt.

    Uitgelezen in de gekleurde uitgave telt ook als je nu de zwart-witte leest;
    anders zou het omzetten van je voorkeur een halve serie weer ongelezen
    maken.
    """
    alle = [book.id for slot in slots for book in slot.books]
    rows = deps.progress_for(session, user, alle)
    gevonden: dict[int, Progress] = {}
    for slot in slots:
        beste = editions.best_progress(slot, rows)
        if beste is not None:
            gevonden[slot.chosen.id] = beste
    return gevonden


@router.get("/{series_id}/continue", response_model=ContinueOut)
def continue_reading(series_id: int, session: Session = Depends(get_session)) -> ContinueOut:
    """Waar je verder leest: vanaf hoe ver je in de serie bent.

    Het ankerpunt is het **laatste** hoofdstuk in leesvolgorde waar voortgang op
    staat, niet het eerste. Dat verschil is het hele punt: een hoofdstuk uit
    deel 1 dat je ooit even hebt opengeslagen blijft anders eeuwig "de eerste
    die nog openstaat", terwijl je allang in deel 3 zit. Zo'n oud restje hoort
    je niet terug te trekken — daar is de knop "markeer eerdere als gelezen"
    voor.

    Staat er op dat anker nog voortgang, dan ga je daar verder op je eigen
    pagina. Is het uit, dan het eerstvolgende hoofdstuk dat nog niet uit is.
    """
    deps.get_series(session, series_id)
    # Bewust over álle afleveringen, ook wat nog niet is opgehaald. Anders komt
    # een serie die je grotendeels online volgt uit op het laatste bestand dat
    # je toevallig hebt staan: bij One Piece hoofdstuk 3, terwijl je bij 124
    # bent. Wat er nog niet is, wordt een ophaalknop — daar is ``has_file``
    # voor.
    slots = _all_slots(session, series_id)
    if not slots:
        raise HTTPException(status_code=404, detail="deze serie heeft nog niets te lezen")

    user = current_user(session)
    books = [slot.chosen for slot in slots]
    progress = _slot_progress(session, user, slots)

    anchor_index: int | None = None
    for index, book in enumerate(books):
        if book.id in progress:
            anchor_index = index

    if anchor_index is None:
        target = books[0]
    else:
        anchor = books[anchor_index]
        anchor_row = progress[anchor.id]
        if not anchor_row.finished:
            target = anchor
        else:
            later = [
                book
                for book in books[anchor_index + 1 :]
                if not (book.id in progress and progress[book.id].finished)
            ]
            # Niets meer erna: dan maar het laatste hoofdstuk, zodat de knop
            # iets doet in plaats van te verdwijnen.
            target = later[0] if later else books[-1]

    row = progress.get(target.id)
    position = row.position if row is not None else {}
    page = position.get("page") if isinstance(position, dict) else None

    unread_before = sum(
        1
        for book in books[: books.index(target)]
        if not (book.id in progress and progress[book.id].finished)
    )

    return ContinueOut(
        book_id=target.id,
        title=target.title,
        number=target.number,
        has_file=target.file_id is not None,
        page=page if isinstance(page, int) and page >= 0 else 0,
        resuming=row is not None and row.percent > 0 and not row.finished,
        unread_before=unread_before,
    )


@router.post("/{series_id}/mark-read-before/{book_id}", response_model=MarkReadBeforeOut)
def mark_read_before(
    series_id: int, book_id: int, session: Session = Depends(get_session)
) -> MarkReadBeforeOut:
    """Alles vóór dit hoofdstuk als gelezen wegzetten.

    Voor de gewone situatie dat je elders al tot hier was, of dat je een serie
    halverwege oppakt. Het hoofdstuk zelf blijft ongemoeid — daar ga je juist
    lezen.
    """
    deps.get_series(session, series_id)
    target = deps.get_book(session, book_id)
    if target.series_id != series_id:
        raise HTTPException(status_code=400, detail="dit hoofdstuk hoort niet bij deze serie")

    user = current_user(session)
    slots = _readable_slots(session, series_id)
    books = [slot.chosen for slot in slots]
    progress = _slot_progress(session, user, slots)

    marked = 0
    for book in books:
        if (book.sort_volume, book.sort_number) >= (target.sort_volume, target.sort_number):
            continue
        row = progress.get(book.id)
        if row is not None and row.finished:
            continue
        deps.upsert_progress(
            session,
            user,
            book.id,
            series_id=series_id,
            position={"page": max(0, (book.page_count or 1) - 1)},
            percent=100.0,
            device="web",
            finished=True,
        )
        marked += 1
    return MarkReadBeforeOut(marked=marked)


@router.post("/{series_id}/import", response_model=ImportSeriesOut)
def import_series_to_library(
    series_id: int,
    payload: ImportSeriesIn,
    session: Session = Depends(get_session),
) -> ImportSeriesOut:
    """Zet een gevolgde serie als gewone bestanden in een van je eigen mappen.

    Daarna is het een lokale serie als elke andere: geen TTL die het bestand
    weer weghaalt, en leesbaar zonder dat de bron bereikbaar is. Het abonnement
    blijft staan, zodat nieuwe hoofdstukken gewoon binnen blijven komen.
    """
    series = deps.get_series(session, series_id)
    root = session.get(LibraryRoot, payload.root_id)
    if root is None:
        raise HTTPException(status_code=404, detail="die map bestaat niet")
    if not root.enabled:
        raise HTTPException(status_code=409, detail="die map staat uit")

    source_row = session.get(Source, series.source_id) if series.source_id else None
    implementation = deps.get_source_implementation(source_row) if source_row else None
    if implementation is None and payload.download_missing:
        raise HTTPException(
            status_code=409,
            detail="deze serie hoort niet bij een bron; er valt niets op te halen",
        )

    try:
        report = importer.import_series(
            session,
            implementation,  # type: ignore[arg-type]
            series,
            root,
            download_missing=payload.download_missing and implementation is not None,
        )
    except SourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ImportSeriesOut(
        moved=report.moved,
        downloaded=report.downloaded,
        skipped=report.skipped,
        errors=report.errors,
    )


@router.get("/merge/suggestions", response_model=list[MergeSuggestionOut])
def merge_suggestions(session: Session = Depends(get_session)) -> list[MergeSuggestionOut]:
    """Series die waarschijnlijk hetzelfde zijn.

    Alleen op genormaliseerde titel — dat vangt hoofdletter- en
    leestekenverschillen zonder te gaan raden.
    """
    out: list[MergeSuggestionOut] = []
    for keep, absorb in merge_module.suggest(session):
        out.append(
            MergeSuggestionOut(
                keep_id=keep.id,
                keep_title=keep.title,
                keep_books=_book_count(session, keep.id),
                absorb_id=absorb.id,
                absorb_title=absorb.title,
                absorb_books=_book_count(session, absorb.id),
            )
        )
    return out


def _book_count(session: Session, series_id: int) -> int:
    return int(session.scalar(select(func.count(Book.id)).where(Book.series_id == series_id)) or 0)


@router.post("/{series_id}/merge", response_model=SeriesDetailOut)
def merge_series(
    series_id: int, payload: MergeSeriesIn, session: Session = Depends(get_session)
) -> SeriesDetailOut:
    """Voeg een andere serie in deze samen. De andere verdwijnt."""
    keep = deps.get_series(session, series_id)
    absorb = session.get(Series, payload.absorb_id)
    if absorb is None:
        raise HTTPException(status_code=404, detail="die serie bestaat niet")

    try:
        merge_module.merge(session, keep, absorb)
    except merge_module.MergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return get_series(series_id, False, session)


@router.get("/{series_id}/editions", response_model=list[EditionOut])
def list_editions(series_id: int, session: Session = Depends(get_session)) -> list[EditionOut]:
    """De uitgaven van deze serie, eerste keus vooraan."""
    series = deps.get_series(series_id=series_id, session=session)
    books = list(series.books)
    uitgaven = list(series.editions)
    return _editions_out(
        uitgaven,
        books,
        editions.slots(books, uitgaven),
        {key: value.language for key, value in _edition_traits(session, uitgaven).items()},
    )


@router.post("/{series_id}/editions/order", response_model=list[EditionOut])
def order_editions(
    series_id: int, payload: EditionOrderIn, session: Session = Depends(get_session)
) -> list[EditionOut]:
    """Bepaal welke uitgave wint waar er meerdere hetzelfde deel hebben.

    Wat je niet noemt schuift er achteraan; zo hoeft een client die één uitgave
    naar boven sleept niet de hele lijst mee te sturen.
    """
    series = deps.get_series(series_id=series_id, session=session)
    per_id = {edition.id: edition for edition in series.editions}
    onbekend = [edition_id for edition_id in payload.edition_ids if edition_id not in per_id]
    if onbekend:
        raise HTTPException(status_code=400, detail="die uitgave hoort niet bij deze serie")

    rang = 0
    for edition_id in payload.edition_ids:
        per_id.pop(edition_id).rank = rang
        rang += 1
    for edition in sorted(per_id.values(), key=lambda edition: edition.rank):
        edition.rank = rang
        rang += 1
    session.commit()

    books = list(series.books)
    uitgaven = list(series.editions)
    return _editions_out(
        uitgaven,
        books,
        editions.slots(books, uitgaven),
        {key: value.language for key, value in _edition_traits(session, uitgaven).items()},
    )


@router.patch("/{series_id}/editions/{edition_id}", response_model=EditionOut)
def rename_edition(
    series_id: int,
    edition_id: int,
    payload: EditionPatch,
    session: Session = Depends(get_session),
) -> EditionOut:
    """Een uitgave een naam geven die jou iets zegt: "kleur", "de mooie scan"."""
    edition = session.get(Edition, edition_id)
    if edition is None or edition.series_id != series_id:
        raise HTTPException(status_code=404, detail="uitgave niet gevonden")
    if payload.name is not None:
        naam = payload.name.strip()
        if not naam:
            raise HTTPException(status_code=400, detail="een uitgave heeft een naam nodig")
        edition.name = naam
    if payload.note is not None:
        edition.note = payload.note.strip() or None
    session.commit()

    series = deps.get_series(series_id=series_id, session=session)
    books = list(series.books)
    uitgaven = list(series.editions)
    for regel in _editions_out(
        uitgaven,
        books,
        editions.slots(books, uitgaven),
        {key: value.language for key, value in _edition_traits(session, uitgaven).items()},
    ):
        if regel.id == edition.id:
            return regel
    raise HTTPException(status_code=404, detail="uitgave niet gevonden")


@router.post("/{series_id}/slots", response_model=SeriesDetailOut)
def bind_slot(
    series_id: int, payload: BookSlotIn, session: Session = Depends(get_session)
) -> SeriesDetailOut:
    """Zeg dat deze boeken dezelfde uitgave van hetzelfde zijn.

    Bij hoofdstukken regelt het nummer dat vanzelf. Bij losse boeken niet: drie
    drukken van hetzelfde boek heten net iets anders, en alleen jij weet dat het
    er één is. Daarna gelden ze als één regel in je lijst, en telt gelezen in de
    ene ook voor de andere.
    """
    deps.get_series(series_id=series_id, session=session)
    if len(payload.book_ids) < 2:
        raise HTTPException(status_code=400, detail="hier horen minstens twee boeken bij")

    books = list(session.scalars(select(Book).where(Book.id.in_(payload.book_ids))))
    if len(books) != len(set(payload.book_ids)):
        raise HTTPException(status_code=404, detail="niet elk boek bestaat")
    if any(book.series_id != series_id for book in books):
        raise HTTPException(status_code=400, detail="deze boeken staan niet in dezelfde serie")

    # De eerste bepaalt het slot: bestaat die al als groep, dan voegen de rest
    # zich daarbij in plaats van dat er een nieuwe groep ontstaat.
    sleutel = books[0].slot or editions.slot_of(books[0])
    for book in books:
        book.slot = sleutel
    session.commit()
    return get_series(series_id, False, session)


@router.post("/{series_id}/slots/unbind", response_model=SeriesDetailOut)
def unbind_slot(
    series_id: int, payload: BookSlotIn, session: Session = Depends(get_session)
) -> SeriesDetailOut:
    """Haal boeken weer uit elkaar; ze krijgen hun eigen regel terug."""
    deps.get_series(series_id=series_id, session=session)
    books = list(session.scalars(select(Book).where(Book.id.in_(payload.book_ids))))
    for book in books:
        if book.series_id == series_id:
            book.slot = None
    session.commit()
    return get_series(series_id, False, session)


@router.post("/{series_id}/covers", response_model=SyncCoversOut)
def sync_series_covers(series_id: int, session: Session = Depends(get_session)) -> SyncCoversOut:
    """Haal de omslagen per deel op bij de bron.

    Voor series die je al volgde voordat dit bestond, en voor wanneer een bron
    er later betere heeft. Per uitgave apart: de gekleurde omslag hoort bij de
    gekleurde delen, niet bij de zwart-witte.
    """
    series = deps.get_series(session, series_id)
    abonnementen = list(
        session.scalars(select(Subscription).where(Subscription.series_id == series_id))
    )
    if not abonnementen:
        raise HTTPException(
            status_code=409, detail="deze serie heeft geen bron om omslagen bij te halen"
        )

    resultaat = SyncCoversOut()
    for subscription in abonnementen:
        source_row = session.get(Source, subscription.source_id)
        if source_row is None or not source_row.enabled:
            continue
        edition = session.scalar(select(Edition).where(Edition.subscription_id == subscription.id))
        try:
            implementation = deps.get_source_implementation(source_row)
        except HTTPException as exc:
            resultaat.errors.append(str(exc.detail))
            continue

        aantal = source_service.sync_covers(
            session,
            implementation,
            series,
            ref=subscription.source_ref or series.source_ref,
            edition=edition,
        )
        if aantal:
            resultaat.updated += aantal
            resultaat.editions.append(f"{edition.name if edition else series.title} ({aantal})")

    session.commit()
    return resultaat


@router.post("/{series_id}/titles", response_model=SyncCoversOut)
def sync_series_titles(series_id: int, session: Session = Depends(get_session)) -> SyncCoversOut:
    """Haal de hoofdstuktitels op bij de bron.

    Een bestandsnaam als "Shin'ya Shokudou Chapter 01 - Yarō Abe.cbz" levert de
    naam van de tekenaar op als titel; de bron weet dat het "Herring Roe" heet.
    Wat hier binnenkomt wordt vastgezet, zodat een volgende scan er niet weer de
    bestandsnaam overheen legt.
    """
    series = deps.get_series(session, series_id)
    abonnementen = list(
        session.scalars(select(Subscription).where(Subscription.series_id == series_id))
    )
    if not abonnementen and not series.source_ref:
        raise HTTPException(
            status_code=409, detail="deze serie heeft geen bron om titels bij te halen"
        )

    resultaat = SyncCoversOut()
    boeken = list(session.scalars(select(Book).where(Book.series_id == series_id)))

    for subscription in abonnementen:
        source_row = session.get(Source, subscription.source_id)
        ref = subscription.source_ref or series.source_ref
        if source_row is None or not source_row.enabled or not ref:
            continue
        try:
            implementation = deps.get_source_implementation(source_row)
            hoofdstukken = implementation.chapters(ref, language=subscription.language)
            # Volgt je deze reeks in een taal waarin niemand hem heeft
            # geüpload, dan zijn er geen titels. Een Engelse titel is dan beter
            # dan geen: het gaat om wát het hoofdstuk is, niet om de taal.
            if not any(chapter.title for chapter in hoofdstukken) and subscription.language != "en":
                hoofdstukken = implementation.chapters(ref, language="en")
        except (HTTPException, SourceError) as exc:
            resultaat.errors.append(str(getattr(exc, "detail", exc)))
            continue

        # Op nummer koppelen en niet op volgorde: je bibliotheek kan gaten
        # hebben, en dan zou tellen de titels één opschuiven.
        per_nummer = {
            _sort_number(chapter.number): chapter.title
            for chapter in hoofdstukken
            if chapter.number and chapter.title
        }
        aantal = 0
        for book in boeken:
            titel = per_nummer.get(book.sort_number)
            if titel and book.title != titel:
                book.title = titel
                book.title_locked = True
                # Ook naast het bestand, zodat het een herinstallatie overleeft
                # en meeverhuist als je de map ergens anders heen zet.
                _remember_title(session, book, titel, lang=subscription.language)
                aantal += 1
        if aantal:
            resultaat.updated += aantal
            resultaat.editions.append(f"{source_row.name} ({aantal})")

    session.commit()
    return resultaat
