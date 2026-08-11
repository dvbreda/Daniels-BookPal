"""BookPal Lite: server-rendered HTML voor de Kobo-browser.

Laag A uit de architectuur (docs/architectuur.md, ontwerp 3) — geen
JavaScript, want de Kobo-browser is een oude QtWebKit die een moderne
React-build niet draait. Een pagina omslaan is gewoon een link (een GET), dus
de server registreert de voortgang zonder dat er ook maar één regel
JavaScript nodig is.

Alleen comics: epub/pdf hebben geen vaste pagina's om als plaatje te
serveren (zie ``/api/books/{id}/pages``), en de Kobo-eigen lezer voor die
formaten is Laag C (``bookpal-kobo``, M9/M10).
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.db import current_user, get_session
from bookpal.images import get_profile
from bookpal.models import BookKind, Series

from . import deps

router = APIRouter(prefix="/lite", tags=["lite"])

_STYLE = """
body { font-family: sans-serif; margin: 0; padding: 1em; font-size: 1.2em; }
h1 { font-size: 1.3em; }
ul { list-style: none; padding: 0; margin: 0; }
li { border-bottom: 1px solid #ccc; }
a { display: block; padding: 0.9em 0.2em; color: #000; text-decoration: none; }
.meta { color: #555; font-size: 0.85em; }
.nav { display: flex; justify-content: space-between; margin: 1em 0; }
.nav.rtl { flex-direction: row-reverse; }
.nav a { flex: 1; text-align: center; border: 1px solid #888; margin: 0 0.3em; }
.page { text-align: center; }
.page img { max-width: 100%; height: auto; }
.back { display: inline-block; margin-bottom: 0.5em; }
"""


def _page(title: str, body: str) -> HTMLResponse:
    html = (
        "<!doctype html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f"<style>{_STYLE}</style>"
        f"</head><body>{body}</body></html>"
    )
    return HTMLResponse(html)


def _profile_param(
    profile: str | None = Query(
        default=None, description="Bv. 'kobo-clara'; blijft over links heen."
    ),
) -> str | None:
    if profile is None:
        return None
    try:
        get_profile(profile)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"onbekend beeldprofiel: {profile}") from None
    return profile


ProfileParam = Depends(_profile_param)


def _qs(profile: str | None) -> str:
    return f"?profile={profile}" if profile else ""


@router.get("", response_class=HTMLResponse)
def lite_home(
    profile: str | None = ProfileParam,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=200),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Alle series. Tabs (M3) filteren dit later; nu nog de volle lijst."""
    total = int(session.scalar(select(func.count(Series.id))) or 0)
    rows = session.scalars(
        select(Series).order_by(Series.sort_title).offset(offset).limit(limit)
    ).all()

    items = "".join(
        f'<li><a href="/lite/series/{s.id}{_qs(profile)}">{escape(s.title)}</a></li>' for s in rows
    )
    profile_bit = f"&profile={profile}" if profile else ""
    nav = ""
    if offset > 0:
        prev_offset = max(0, offset - limit)
        href = f"/lite?offset={prev_offset}&limit={limit}{profile_bit}"
        nav += f'<a href="{href}">&laquo; Vorige</a>'
    if offset + limit < total:
        next_offset = offset + limit
        href = f"/lite?offset={next_offset}&limit={limit}{profile_bit}"
        nav += f'<a href="{href}">Volgende &raquo;</a>'

    body = f"<h1>BookPal</h1><ul>{items}</ul>"
    if nav:
        body += f'<div class="nav">{nav}</div>'
    return _page("BookPal", body)


@router.get("/series/{series_id}", response_class=HTMLResponse)
def lite_series(
    series_id: int,
    profile: str | None = ProfileParam,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    series = deps.get_series(session, series_id)
    user = current_user(session)
    books = list(series.books)
    progress = deps.progress_for(session, user, [b.id for b in books])

    rows = []
    for book in books:
        prog = progress.get(book.id)
        label = book.title if not book.number else f"{book.number} — {book.title}"
        meta = ""
        if prog is not None:
            state = "uitgelezen" if prog.finished else f"{prog.percent:.0f}%"
            meta = f'<div class="meta">{escape(state)}</div>'
        rows.append(
            f'<li><a href="/lite/books/{book.id}{_qs(profile)}">{escape(label)}{meta}</a></li>'
        )

    body = (
        f'<a class="back" href="/lite{_qs(profile)}">&laquo; Bibliotheek</a>'
        f"<h1>{escape(series.title)}</h1><ul>{''.join(rows)}</ul>"
    )
    return _page(series.title, body)


@router.get("/books/{book_id}", response_model=None)
def lite_book(
    book_id: int,
    profile: str | None = ProfileParam,
    session: Session = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    book = deps.get_book(session, book_id)

    if book.kind is not BookKind.COMIC:
        series = session.get(Series, book.series_id)
        body = (
            f'<a class="back" href="/lite/series/{book.series_id}{_qs(profile)}">&laquo; '
            f"{escape(series.title) if series else 'Terug'}</a>"
            f"<h1>{escape(book.title)}</h1>"
            "<p>Dit is geen strip — Lite leest alleen pagina's als plaatje. "
            f'<a href="/api/books/{book.id}/file">Bestand downloaden</a>.</p>'
        )
        return _page(book.title, body)

    user = current_user(session)
    prog = deps.progress_for(session, user, [book.id]).get(book.id)
    start_page = int(prog.position.get("page", 0)) if prog is not None and not prog.finished else 0
    query = _qs(profile)
    target = f"/lite/books/{book.id}/read/{start_page}"
    return RedirectResponse(target + query)


@router.get("/books/{book_id}/read/{page}", response_class=HTMLResponse)
def lite_read(
    book_id: int,
    page: int,
    profile: str | None = ProfileParam,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    book = deps.get_book(session, book_id)
    if book.kind is not BookKind.COMIC:
        raise HTTPException(status_code=409, detail="Lite leest alleen strips als plaatje")
    if book.page_count is None or not (0 <= page < book.page_count):
        raise HTTPException(status_code=404, detail="pagina bestaat niet")

    user = current_user(session)
    finished = page >= book.page_count - 1
    deps.upsert_progress(
        session,
        user,
        book.id,
        position={"page": page},
        percent=round((page + 1) / book.page_count * 100, 1),
        device="lite",
        finished=finished,
    )

    query = _qs(profile)
    img_src = f"/api/books/{book.id}/pages/{page}{query}"

    nav_class = "nav rtl" if book.right_to_left else "nav"
    links = []
    if page > 0:
        links.append(f'<a href="/lite/books/{book.id}/read/{page - 1}{query}">&laquo; Vorige</a>')
    else:
        links.append("<span></span>")
    if page < book.page_count - 1:
        links.append(f'<a href="/lite/books/{book.id}/read/{page + 1}{query}">Volgende &raquo;</a>')
    else:
        links.append("<span></span>")

    back_href = f"/lite/series/{book.series_id}{query}"
    body = (
        f'<a class="back" href="{back_href}">&laquo; {escape(book.title)}</a>'
        f'<div class="{nav_class}">{"".join(links)}</div>'
        f'<div class="page"><img src="{img_src}" alt="pagina {page + 1}">'
        f"<div class=\"meta\">pagina {page + 1} / {book.page_count}</div></div>"
        f'<div class="{nav_class}">{"".join(links)}</div>'
    )
    return _page(f"{book.title} — {page + 1}/{book.page_count}", body)
