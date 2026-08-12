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

import logging
from dataclasses import dataclass
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.db import current_user, get_session
from bookpal.images import PROFILES, get_profile
from bookpal.models import Book, BookKind, Progress, Series
from bookpal.translate import get_translator
from bookpal.translate import is_configured as translate_is_configured
from bookpal.translate import service as translation_service
from bookpal.translate.base import TranslationError

from . import deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lite", tags=["lite"])

_STYLE = """
/* Alles hier moet kloppen op de browser van een Kobo: QtWebKit uit ongeveer
   2012. Die kent geen flexbox — een `display: flex` valt daar terug op `block`,
   waardoor elk kaartje op een eigen regel belandt en je raster een kolom wordt.
   Daarom float en inline-block, en marges in plaats van `gap`.

   Kleiner lettertype dan de lezer zelf: in een lijst wil je zien wat je hebt,
   niet één titel per scherm. De tapdoelen blijven groot — een e-inkscherm
   reageert traag genoeg zonder dat je ook nog moet mikken. */
body { font-family: sans-serif; margin: 0; padding: 0.8em; font-size: 1em; }
h1 { font-size: 1.15em; margin: 0.2em 0 0.6em; }
ul { list-style: none; padding: 0; margin: 0; }
li { border-bottom: 1px solid #ccc; }
a { display: block; padding: 0.7em 0.2em; color: #000; text-decoration: none; }
.meta { color: #555; font-size: 0.8em; }

/* Knoppenbalk: twee of drie naast elkaar, ongeacht hoeveel het er zijn. */
.tools { margin: 0.8em 0; overflow: hidden; }
.tools a {
  float: left; box-sizing: border-box; text-align: center; border: 1px solid #888;
  padding: 0.6em 0.3em; font-size: 0.9em; margin-right: 2%;
}
.tools.twee a { width: 49%; }
.tools.twee a.laatste { margin-right: 0; }
.tools.een a { width: 100%; margin-right: 0; }

/* Omslag naast de titel. Een tabel-achtige opmaak omdat verticaal centreren
   zonder flexbox anders niet lukt. */
li a.cover-row { padding: 0.5em 0.2em; overflow: hidden; }
.cover-row img {
  width: 44px; height: 66px; float: left; margin-right: 0.7em; background: #eee;
}
.cover-row .naam { display: block; overflow: hidden; }
.bar { height: 3px; background: #ddd; margin-top: 0.3em; }
.bar span { display: block; height: 100%; background: #444; }

/* Raster: drie op een rij past op elk Kobo-scherm zonder dat de omslag te
   klein wordt om te herkennen. font-size 0 op de lijst haalt de witruimte
   tussen inline-blocks weg; de kaartjes zetten hem weer terug. */
ul.raster { font-size: 0; }
ul.raster li {
  display: inline-block; vertical-align: top; width: 31.3%; border: none;
  margin: 0 3% 0.8em 0; font-size: 1rem;
}
ul.raster li.derde { margin-right: 0; }
ul.raster a { padding: 0; }
ul.raster img { width: 100%; height: auto; background: #eee; display: block; }
ul.raster .naam {
  display: block; font-size: 0.75em; line-height: 1.2; max-height: 2.4em;
  overflow: hidden; margin-top: 0.2em;
}

/* Verder lezen: één blok bovenaan, want dat is bijna altijd wat je wilt. */
.hero { border: 1px solid #888; padding: 0.6em; margin-bottom: 1em; overflow: hidden; }
.hero img { width: 70px; height: 105px; float: left; margin-right: 0.8em; background: #eee; }
.hero .wat { overflow: hidden; }
.hero .titel { font-size: 1.05em; font-weight: bold; }
.hero a.knop { display: inline-block; border: 1px solid #444; padding: 0.5em 0.9em;
  margin-top: 0.4em; }

/* Bladeren: vorige links, volgende rechts — omgedraaid bij manga. */
.nav { margin: 1em 0; overflow: hidden; }
.nav a { display: block; width: 47%; box-sizing: border-box; text-align: center;
  border: 1px solid #888; float: left; }
.nav a.verder { float: right; }
.nav.rtl a { float: right; }
.nav.rtl a.verder { float: left; }

.page { text-align: center; }
.page img { max-width: 100%; height: auto; }
/* De vertaallaag is een doorzichtige PNG op exact dezelfde maat, dus hij hoeft
   alleen over de pagina gelegd te worden. Zonder JavaScript: aan- en uitzetten
   is een gewone link naar dezelfde pagina zonder ?vertaal. */
.stack { position: relative; display: inline-block; max-width: 100%; }
.stack .layer { position: absolute; left: 0; top: 0; width: 100%; height: 100%; }
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


@dataclass(frozen=True, slots=True)
class LiteOptions:
    """Alles wat je in Lite kunt instellen.

    Zonder JavaScript is de URL de enige plek waar een stand kan wonen, dus
    reist dit blokje mee in elke link. Dat is meteen de reden dat het één
    dataclass is en geen zes losse parameters: elke link moet ze compleet
    doorgeven, en één vergeten veld betekent dat je instelling wegvalt zodra je
    een pagina omslaat.
    """

    profile: str | None = None
    translated: bool = False
    hide_read: bool = False
    # Rakuyomi's "page crop": egale scanranden weghalen scheelt op een klein
    # scherm zomaar een kwart van het beeld.
    crop: bool = False
    # 100 is onbewerkt; hoger rekt het grijsbereik op voor bleke scans.
    contrast: int = 100
    # Omslagen naast elkaar of onder elkaar. Een raster laat een reeks zien,
    # een lijst laat titels lezen — welke je wilt hangt af van wat je zoekt.
    grid: bool = False

    def query(self, **overrides: object) -> str:
        waarden = {
            "profile": self.profile,
            "vertaal": self.translated,
            "verberg": self.hide_read,
            "snij": self.crop,
            "contrast": self.contrast,
            "raster": self.grid,
            **overrides,
        }
        parts = []
        for sleutel, waarde in waarden.items():
            if sleutel == "contrast":
                if waarde != 100:
                    parts.append(f"contrast={waarde}")
            elif isinstance(waarde, bool):
                if waarde:
                    parts.append(f"{sleutel}=1")
            elif waarde:
                parts.append(f"{sleutel}={waarde}")
        return f"?{'&'.join(parts)}" if parts else ""

    def image_query(self) -> str:
        """Alleen wat het beeld zelf verandert; de rest hoort niet in een img-src.

        Altijd mét profiel, ook als je er geen koos: zonder profiel rendert de
        server webp, en dat toont de Kobo-browser niet.
        """
        parts = [f"profile={_safe_profile(self.profile, FALLBACK_PROFILE)}"]
        if self.crop:
            parts.append("crop=true")
        if self.contrast != 100:
            parts.append(f"contrast={self.contrast}")
        return f"?{'&'.join(parts)}" if parts else ""


def _options(
    profile: str | None = ProfileParam,
    vertaal: bool = Query(default=False),
    verberg: bool = Query(default=False, description="Verberg wat je al uit hebt."),
    snij: bool = Query(default=False, description="Egale rand rond de pagina weghalen."),
    contrast: int = Query(default=100, ge=50, le=200),
    raster: bool = Query(default=False, description="Omslagen naast elkaar."),
) -> LiteOptions:
    return LiteOptions(
        profile=profile,
        translated=vertaal,
        hide_read=verberg,
        crop=snij,
        contrast=contrast,
        grid=raster,
    )


OptionsParam = Depends(_options)


#: Waar Lite op terugvalt. Png, want de browser van een Kobo kent geen webp —
#: en Lite bestaat juist voor die browser. De maat is die van een Clara; op een
#: groter scherm schaalt de browser hem op, wat minder erg is dan een leeg vlak.
FALLBACK_PROFILE = "kobo-clara"
FALLBACK_THUMB = "kobo-thumb"


def _safe_profile(profile: str | None, standaard: str) -> str:
    """Een profiel dat deze browser kan tonen.

    Lite stuurt nooit webp. Vraag je toch om een webp-profiel, dan krijg je de
    png-variant: een plaatje dat er is weegt zwaarder dan een paar kilobyte
    verschil.
    """
    if profile:
        gekozen = PROFILES.get(profile)
        if gekozen is not None and gekozen.format != "webp":
            return profile
    return standaard


def _cover_query(profile: str | None) -> str:
    """Omslagen klein en in grijstinten: de Kobo laat ze toch niet groter zien,
    en over usb of wifi scheelt het merkbaar."""
    return f"?profile={_safe_profile(profile, FALLBACK_THUMB)}"


def _qs(profile: str | None, translated: bool = False, hide_read: bool = False) -> str:
    """Kortere weg voor de plekken die alleen het profiel doorgeven."""
    return LiteOptions(profile=profile, translated=translated, hide_read=hide_read).query()


HideReadParam = Query(default=False, description="Verberg wat je al uit hebt.")


def _card(href: str, cover: str, naam: str, *, grid: bool, index: int) -> str:
    """Eén regel of één tegel, afhankelijk van de weergave.

    In het raster krijgt elke derde tegel geen rechtermarge; zonder dat past de
    derde net niet meer op de regel en zakt hij een rij omlaag.
    """
    if grid:
        rand = ' class="derde"' if index % 3 == 2 else ""
        return (
            f"<li{rand}><a href=\"{href}\">"
            f'<img src="{cover}" alt="" loading="lazy">'
            f'<span class="naam">{naam}</span></a></li>'
        )
    return (
        f'<li><a class="cover-row" href="{href}">'
        f'<img src="{cover}" alt="" loading="lazy">'
        f'<span class="naam">{naam}</span></a></li>'
    )


def _toolbar(knoppen: list[tuple[str, str]]) -> str:
    """Een rij knoppen die naast elkaar past.

    De breedte staat in een klasse en niet in flexbox: de Kobo-browser kent dat
    niet, en dan wordt elke knop een eigen regel.
    """
    if not knoppen:
        return ""
    klasse = {1: "een", 2: "twee"}.get(len(knoppen), "twee")
    regels = []
    for index, (label, href) in enumerate(knoppen):
        # De laatste zonder rechtermarge, anders valt hij van de regel af.
        rand = ' class="laatste"' if index == len(knoppen) - 1 else ""
        regels.append(f'<a{rand} href="{href}">{escape(label)}</a>')
    return f'<div class="tools {klasse}">{"".join(regels)}</div>' 

def _hide_toggle(pad: str, opts: LiteOptions) -> str:
    """De schakelaar zelf: een gewone link naar dezelfde pagina."""
    doel = f"{pad}{opts.query(verberg=not opts.hide_read)}"
    label = "Alles tonen" if opts.hide_read else "Gelezen verbergen"
    return _toolbar([(label, doel)])


@router.get("", response_class=HTMLResponse)
def lite_home(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=200),
    opts: LiteOptions = OptionsParam,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Alle series. Tabs (M3) filteren dit later; nu nog de volle lijst."""
    user = current_user(session)
    statement = select(Series)
    telling = select(func.count(Series.id))
    if opts.hide_read:
        # Een serie is "uit" als er geen enkel deel meer openstaat. Als
        # voorwaarde op de query en niet achteraf, anders klopt het paginanummer
        # niet meer.
        openstaand = (
            select(Book.series_id)
            .outerjoin(
                Progress,
                (Progress.book_id == Book.id) & (Progress.user_id == user.id),
            )
            .where((Progress.id.is_(None)) | (Progress.finished.is_(False)))
        )
        statement = statement.where(Series.id.in_(openstaand))
        telling = telling.where(Series.id.in_(openstaand))

    total = int(session.scalar(telling) or 0)
    rows = session.scalars(
        statement.order_by(Series.sort_title).offset(offset).limit(limit)
    ).all()

    items = "".join(
        _card(
            f"/lite/series/{s.id}{opts.query()}",
            f"/api/series/{s.id}/cover{_cover_query(opts.profile)}",
            escape(s.title),
            grid=opts.grid,
            index=index,
        )
        for index, s in enumerate(rows)
    )
    # De paginering plakt achter de bestaande instellingen aan.
    rest = opts.query().lstrip("?")
    profile_bit = f"&{rest}" if rest else ""
    nav = ""
    if offset > 0:
        prev_offset = max(0, offset - limit)
        href = f"/lite?offset={prev_offset}&limit={limit}{profile_bit}"
        nav += f'<a href="{href}">&laquo; Vorige</a>'
    if offset + limit < total:
        next_offset = offset + limit
        href = f"/lite?offset={next_offset}&limit={limit}{profile_bit}"
        nav += f'<a href="{href}">Volgende &raquo;</a>'

    lijst = f'<ul class="raster">{items}</ul>' if opts.grid else f"<ul>{items}</ul>"
    body = f"<h1>BookPal</h1>{_continue_block(session, opts)}"
    body += f"{_view_tools('/lite', opts)}{lijst}"
    if not rows:
        body += (
            "<p>Niets open.</p>"
            if opts.hide_read
            else "<p>Nog geen series; draai een scan.</p>"
        )
    if nav:
        body += f'<div class="nav">{nav}</div>'
    return _page("BookPal", body)


@router.get("/series/{series_id}", response_class=HTMLResponse)
def lite_series(
    series_id: int,
    opts: LiteOptions = OptionsParam,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    series = deps.get_series(session, series_id)
    user = current_user(session)
    books = list(series.books)
    progress = deps.progress_for(session, user, [b.id for b in books])
    if opts.hide_read:
        books = [
            book
            for book in books
            if not ((row := progress.get(book.id)) is not None and row.finished)
        ]

    rows: list[str] = []
    for book in books:
        prog = progress.get(book.id)
        # Zonder het deel is de volgorde niet te volgen zodra hoofdstukken
        # per deel opnieuw beginnen te tellen (elk deel heeft een "1").
        prefix = f"{book.volume}.{book.number}" if book.volume else book.number
        label = book.title if not prefix else f"{prefix} — {book.title}"
        meta = ""
        if prog is not None:
            state = "uitgelezen" if prog.finished else f"{prog.percent:.0f}%"
            balk = (
                f'<div class="bar"><span style="width:{prog.percent:.0f}%"></span></div>'
                if not prog.finished
                else ""
            )
            meta = f'<div class="meta">{escape(state)}</div>{balk}'
        rows.append(
            _card(
                f"/lite/books/{book.id}{opts.query()}",
                f"/api/books/{book.id}/cover{_cover_query(opts.profile)}",
                f"{escape(label)}{meta}",
                grid=opts.grid,
                index=len(rows),
            )
        )

    lijst = f'<ul class="raster">{"".join(rows)}</ul>' if opts.grid else f"<ul>{''.join(rows)}</ul>"
    body = (
        f'<a class="back" href="/lite{opts.query()}">&laquo; Bibliotheek</a>'
        f"<h1>{escape(series.title)}</h1>"
        f"{_view_tools(f'/lite/series/{series.id}', opts)}"
        f"{lijst}"
    )
    if not rows:
        body += "<p>Niets open in deze serie.</p>"
    return _page(series.title, body)


@router.get("/books/{book_id}", response_model=None)
def lite_book(
    book_id: int,
    opts: LiteOptions = OptionsParam,
    session: Session = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    book = deps.get_book(session, book_id)

    if book.kind is not BookKind.COMIC:
        series = session.get(Series, book.series_id)
        body = (
            f'<a class="back" href="/lite/series/{book.series_id}{opts.query()}">&laquo; '
            f"{escape(series.title) if series else 'Terug'}</a>"
            f"<h1>{escape(book.title)}</h1>"
            "<p>Dit is geen strip — Lite leest alleen pagina's als plaatje. "
            f'<a href="/api/books/{book.id}/file">Bestand downloaden</a>.</p>'
        )
        return _page(book.title, body)

    user = current_user(session)
    prog = deps.progress_for(session, user, [book.id]).get(book.id)
    start_page = int(prog.position.get("page", 0)) if prog is not None and not prog.finished else 0
    query = opts.query()
    target = f"/lite/books/{book.id}/read/{start_page}"
    return RedirectResponse(target + query)


@router.get("/books/{book_id}/read/{page}", response_class=HTMLResponse)
def lite_read(
    book_id: int,
    page: int,
    opts: LiteOptions = OptionsParam,
    maak: bool = Query(default=False, description="Vertaal deze pagina nu."),
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
        series_id=book.series_id,
        position={"page": page},
        percent=round((page + 1) / book.page_count * 100, 1),
        device="lite",
        finished=finished,
    )

    # De leeslinks houden alle instellingen vast, zodat je ze één keer zet en
    # daarna gewoon doorbladert.
    query = opts.query()
    img_query = opts.image_query()
    img_src = f"/api/books/{book.id}/pages/{page}{img_query}"

    nav_class = "nav rtl" if book.right_to_left else "nav"
    links = []
    if page > 0:
        links.append(f'<a href="/lite/books/{book.id}/read/{page - 1}{query}">&laquo; Vorige</a>')
    if page < book.page_count - 1:
        links.append(
            f'<a class="verder" href="/lite/books/{book.id}/read/{page + 1}{query}">'
            "Volgende &raquo;</a>"
        )

    # Alleen aanbieden als er iets te tonen valt: een link naar een vertaling
    # die nog niet bestaat, levert een lege laag en een verwarde lezer op.
    has_translation = (
        translation_service.find(session, book.id, page, settings.translate_lang, "gemini")
        is not None
    )
    # Nog niet vertaald maar je vraagt erom: dan nú vertalen. Dat duurt een paar
    # tellen en dat is precies waarom het een aparte link is en niet iets wat
    # vanzelf gebeurt zodra je een pagina opent.
    if maak and not has_translation and translate_is_configured():
        translator = get_translator()
        try:
            translation_service.translate_page(
                session, translator, book, page, target_lang=settings.translate_lang
            )
            has_translation = True
        except TranslationError as exc:
            logger.warning("vertalen van %s p%s: %s", book.id, page, exc)
        finally:
            translator.close()

    layer = ""
    toggle = ""
    if has_translation:
        if opts.translated:
            layer = (
                f'<img class="layer" src="/api/books/{book.id}/pages/{page}/overlay'
                f'{img_query}" alt="vertaling">'
            )
            toggle = (
                f'<a href="/lite/books/{book.id}/read/{page}'
                f'{opts.query(vertaal=False)}">Origineel</a>'
            )
        else:
            toggle = (
                f'<a href="/lite/books/{book.id}/read/{page}'
                f'{opts.query(vertaal=True)}">Vertaling</a>'
            )
    elif translate_is_configured():
        toggle = (
            f'<a href="/lite/books/{book.id}/read/{page}'
            f'{opts.query(vertaal=True, maak=True)}">Vertaal deze pagina</a>'
        )

    back_href = f"/lite/series/{book.series_id}{query}"
    body = (
        f'<a class="back" href="{back_href}">&laquo; {escape(book.title)}</a>'
        f'<div class="{nav_class}">{"".join(links)}</div>'
        f'<div class="page"><span class="stack">'
        f'<img src="{img_src}" alt="pagina {page + 1}">{layer}</span>'
        f"<div class=\"meta\">pagina {page + 1} / {book.page_count}{' · ' if toggle else ''}"
        f"{toggle}</div></div>"
        f'<div class="{nav_class}">{"".join(links)}</div>'
        f"{_reading_tools(book.id, page, opts)}"
    )
    return _page(f"{book.title} — {page + 1}/{book.page_count}", body)


def _reading_tools(book_id: int, page: int, opts: LiteOptions) -> str:
    """De leesopties, als gewone links.

    Wat de Kobo wél aankan en waar hij baat bij heeft: een egale scanrand
    weghalen scheelt op een klein scherm zomaar een kwart van het beeld, en meer
    contrast maakt een bleke scan op e-ink pas leesbaar. Beide gebeuren op de
    server, dus het apparaat hoeft alleen het resultaat te tonen.
    """
    basis = f"/lite/books/{book_id}/read/{page}"
    knoppen = [
        (
            "Bijsnijden: " + ("aan" if opts.crop else "uit"),
            basis + opts.query(snij=not opts.crop),
        )
    ]
    volgend_contrast = {100: 130, 130: 160, 160: 100}.get(opts.contrast, 100)
    knoppen.append(
        (
            f"Contrast: {opts.contrast}%",
            basis + opts.query(contrast=volgend_contrast),
        )
    )
    regels = "".join(f'<a href="{href}">{escape(label)}</a>' for label, href in knoppen)
    return f'<div class="tools">{regels}</div>'


def _view_tools(basis: str, opts: LiteOptions) -> str:
    """Raster of lijst, en het verbergen van wat je uit hebt.

    Twee knoppen naast elkaar in plaats van twee balken onder elkaar: op een
    Kobo is verticale ruimte het schaarse goed.
    """
    return _toolbar(
        [
            (
                "Als lijst" if opts.grid else "Als raster",
                f"{basis}{opts.query(raster=not opts.grid)}",
            ),
            (
                "Alles tonen" if opts.hide_read else "Gelezen verbergen",
                f"{basis}{opts.query(verberg=not opts.hide_read)}",
            ),
        ]
    )


def _continue_block(session: Session, opts: LiteOptions) -> str:
    """Waar je gebleven was, bovenaan de startpagina.

    Dezelfde gedachte als in de web-app: het enige wat je bij het openen bijna
    altijd wilt is terug naar je pagina, en op een e-reader met een trage
    verversing telt elke tik die je niet hoeft te doen dubbel.
    """
    user = current_user(session)
    rij = session.execute(
        select(Progress, Book, Series)
        .join(Book, Book.id == Progress.book_id)
        .join(Series, Series.id == Book.series_id)
        .where(
            Progress.user_id == user.id,
            Progress.finished.is_(False),
            Book.file_id.isnot(None),
        )
        .order_by(Progress.updated_at.desc())
        .limit(1)
    ).first()
    if rij is None:
        return ""

    progress, book, series = rij
    positie = progress.position if isinstance(progress.position, dict) else {}
    pagina = positie.get("page")
    pagina = pagina if isinstance(pagina, int) and pagina >= 0 else 0
    doel = f"/lite/books/{book.id}/read/{pagina}{opts.query()}"

    return (
        '<div class="hero">'
        f'<img src="/api/books/{book.id}/cover{_cover_query(opts.profile)}" alt="">'
        '<div class="wat">'
        f'<div class="titel">{escape(series.title)}</div>'
        f'<div class="meta">{escape(book.title)} · {progress.percent:.0f}%</div>'
        f'<div class="bar"><span style="width:{progress.percent:.0f}%"></span></div>'
        f'<a class="knop" href="{doel}">Verder lezen · pagina {pagina + 1}</a>'
        "</div></div>"
    )
