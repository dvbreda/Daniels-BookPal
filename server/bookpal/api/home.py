"""De homepagina: waar je gebleven was, en wat er nieuw is.

Een bibliotheek van duizenden hoofdstukken heeft geen behoefte aan nóg een
alfabetische lijst — die staat er al. Wat je bij het openen wilt zien is waar je
was en wat er sinds gisteren bij is gekomen, en dat past in rails: één rij per
vraag, horizontaal doorschuifbaar.

Eén endpoint voor alle rails, en niet vier. Ze delen dezelfde gegevens en
dezelfde beperking (per serie hooguit één regel), en vier losse aanroepen zouden
alleen maar vier keer dezelfde tabellen langsgaan.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.library import editions
from bookpal.models import Book, Edition, File, Progress, Series, User
from bookpal.schemas import HomeItemOut, HomeOut, HomeRailOut

router = APIRouter(prefix="/api/home", tags=["home"])

# Zoveel past er op een rij zonder dat het een lijst wordt. Doorschuiven mag,
# eindeloos scrollen hoort thuis in de bibliotheek.
_RAIL_SIZE = 20


def _item(
    book: Book, series: Series, progress: Progress | None, extension: str | None
) -> HomeItemOut:
    positie = progress.position if progress is not None else {}
    pagina = positie.get("page") if isinstance(positie, dict) else None
    return HomeItemOut(
        book_id=book.id,
        series_id=series.id,
        series_title=series.title,
        title=book.title,
        number=book.number,
        volume=book.volume,
        kind=book.kind,
        has_file=book.file_id is not None,
        extension=extension,
        page_count=book.page_count,
        percent=progress.percent if progress is not None else 0.0,
        finished=progress.finished if progress is not None else False,
        page=pagina if isinstance(pagina, int) and pagina >= 0 else 0,
        updated_at=progress.updated_at if progress is not None else None,
        added_at=book.added_at,
    )


def _extensions(session: Session, books: list[Book]) -> dict[int, str]:
    ids = [book.file_id for book in books if book.file_id]
    if not ids:
        return {}
    return {
        row.id: row.extension for row in session.scalars(select(File).where(File.id.in_(ids)))
    }


def _one_per_series(items: list[HomeItemOut], limit: int) -> list[HomeItemOut]:
    """Hooguit één regel per serie.

    Zonder deze grens vult één serie waarin je vlot leest de hele rij, en dan
    zie je juist niet meer wat je verder nog openstaan hebt.
    """
    gezien: set[int] = set()
    gekozen: list[HomeItemOut] = []
    for item in items:
        if item.series_id in gezien:
            continue
        gezien.add(item.series_id)
        gekozen.append(item)
        if len(gekozen) >= limit:
            break
    return gekozen


def _readable(statement: Select[tuple[Book]]) -> Select[tuple[Book]]:
    return statement.where(Book.file_id.isnot(None))


def _continue_rail(session: Session, user: User, limit: int) -> list[HomeItemOut]:
    """Waar je gebleven was, meest recent aangeraakt eerst."""
    rijen = session.execute(
        select(Progress, Book, Series)
        .join(Book, Book.id == Progress.book_id)
        .join(Series, Series.id == Book.series_id)
        .where(Progress.user_id == user.id, Progress.finished.is_(False))
        .order_by(Progress.updated_at.desc())
        .limit(limit * 4)
    ).all()
    boeken = [book for _p, book, _s in rijen]
    extensies = _extensions(session, boeken)
    items = [
        _item(book, series, progress, extensies.get(book.file_id or -1))
        for progress, book, series in rijen
    ]
    return _one_per_series(items, limit)


def _next_up_rail(session: Session, user: User, limit: int) -> list[HomeItemOut]:
    """Het eerstvolgende deel in series waar je in zit.

    Anders dan "verder lezen": daar staat wat je halverwege hebt, hier wat
    klaarligt omdat je het vorige deel uit hebt.
    """
    reeksen = session.scalars(
        select(Series.id)
        .join(Book, Book.series_id == Series.id)
        .join(Progress, (Progress.book_id == Book.id) & (Progress.user_id == user.id))
        .where(Progress.finished.is_(True))
        .distinct()
    ).all()

    gevonden: list[HomeItemOut] = []
    for series_id in reeksen:
        series = session.get(Series, series_id)
        if series is None:
            continue
        boeken = list(
            session.scalars(
                select(Book)
                .where(Book.series_id == series_id)
                .order_by(Book.sort_volume, Book.sort_number)
            )
        )
        uitgaven = list(session.scalars(select(Edition).where(Edition.series_id == series_id)))
        leesbaar = editions.readable(editions.slots(boeken, uitgaven))
        if not leesbaar:
            continue
        voortgang = {
            row.book_id: row
            for row in session.scalars(
                select(Progress).where(
                    Progress.user_id == user.id,
                    Progress.book_id.in_([b.id for b in boeken]),
                )
            )
        }
        openstaand = [
            slot
            for slot in leesbaar
            if (row := editions.best_progress(slot, voortgang)) is None
            or not (row.finished or row.percent > 0)
        ]
        if not openstaand:
            continue
        slot = openstaand[0]
        extensies = _extensions(session, [slot.chosen])
        gevonden.append(
            _item(slot.chosen, series, None, extensies.get(slot.chosen.file_id or -1))
        )

    gevonden.sort(key=lambda item: item.added_at, reverse=True)
    return gevonden[:limit]


def _recent_rail(session: Session, user: User, limit: int) -> list[HomeItemOut]:
    """Wat er nieuw binnen is, per serie één.

    Een nieuw hoofdstuk van iets wat je leest is meer nieuws dan een bestand dat
    je toevallig hebt neergezet, dus dat komt voorop. Bij een serie met een
    abonnement komen er elke ronde delen bij; zonder deze weging duwen die
    alles weg waar je echt in zit.
    """
    rijen = session.execute(
        _readable(select(Book))
        .join(Series, Series.id == Book.series_id)
        .add_columns(Series)
        .order_by(Book.added_at.desc())
        .limit(limit * 8)
    ).all()
    boeken = [book for book, _s in rijen]
    extensies = _extensions(session, boeken)

    gelezen = set(
        session.scalars(
            select(Book.series_id)
            .join(Progress, (Progress.book_id == Book.id) & (Progress.user_id == user.id))
            .distinct()
        ).all()
    )
    items = [_item(book, series, None, extensies.get(book.file_id or -1)) for book, series in rijen]
    items.sort(key=lambda item: (item.series_id not in gelezen, -item.added_at.timestamp()))
    return _one_per_series(items, limit)


@router.get("", response_model=HomeOut)
def home(
    limit: int = Query(default=_RAIL_SIZE, ge=1, le=50),
    session: Session = Depends(get_session),
) -> HomeOut:
    """De rails voor de startpagina, in de volgorde waarin je ze wilt zien."""
    user = current_user(session)

    verder = _continue_rail(session, user, limit)
    bezig = {item.series_id for item in verder}
    volgende = [item for item in _next_up_rail(session, user, limit) if item.series_id not in bezig]
    nieuw = _recent_rail(session, user, limit)

    rails = [
        HomeRailOut(key="verder", title="Verder lezen", items=verder),
        HomeRailOut(key="volgende", title="Het volgende deel", items=volgende),
        HomeRailOut(key="nieuw", title="Nieuw binnengekomen", items=nieuw),
    ]
    return HomeOut(rails=[rail for rail in rails if rail.items])
