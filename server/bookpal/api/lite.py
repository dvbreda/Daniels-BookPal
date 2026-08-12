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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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

/* Lijst: omslag links, titel ernaast. Float in plaats van flexbox, en
   `overflow: hidden` op de regel zodat hij om de gefloate omslag heen sluit. */
ul.lijst a { padding: 0.5em 0.2em; overflow: hidden; }
ul.lijst img {
  width: 44px; height: 66px; float: left; margin-right: 0.7em; background: #eee;
}
ul.lijst .naam { display: block; overflow: hidden; }
.bar { height: 3px; background: #ddd; margin-top: 0.3em; }
.bar span { display: block; height: 100%; background: #444; }

/* Raster: drie op een rij past op elk Kobo-scherm zonder dat de omslag te
   klein wordt om te herkennen. font-size 0 op de lijst haalt de witruimte
   tussen inline-blocks weg; de kaartjes zetten hem weer terug.

   Exact dezelfde html als de lijst — alleen deze klasse verschilt. Daardoor is
   omschakelen één klasse omzetten in plaats van een nieuwe pagina ophalen. */
ul.raster { font-size: 0; }
ul.raster li {
  display: inline-block; vertical-align: top; width: 31.3%; border: none;
  margin: 0 3% 0.8em 0; font-size: 1rem;
}
ul.raster li.derde { margin-right: 0; }
ul.raster a { padding: 0; }
ul.raster img { width: 100%; height: auto; background: #eee; display: block; float: none;
  margin-right: 0; }
ul.raster .naam {
  display: block; font-size: 0.75em; line-height: 1.2; max-height: 2.4em;
  overflow: hidden; margin-top: 0.2em;
}

/* Uitgelezen verbergen doet de stijl, niet de server: dan kan het schakelen
   zonder de pagina opnieuw op te halen, en werkt het zonder JavaScript nog
   steeds — de klasse staat er dan meteen op. */
ul.verbergen li.uit { display: none; }

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


#: Een extraatje, geen fundament. Elke knop is en blijft een gewone link die
#: het zonder dit script ook doet; wat hier gebeurt is dat de pagina niet
#: opnieuw opgehaald hoeft te worden. Op e-ink scheelt dat een volle
#: schermverversing, en dat is precies waar het traag voelt.
#:
#: Strikt ES5: de browser van een Kobo is QtWebKit uit ongeveer 2012. Geen
#: pijlfuncties, geen let, geen template-strings, geen classList — één
#: onbekend woord en het hele blok doet niets meer.
_SCRIPT = """
(function () {
  var lijst = document.getElementById("lijst");
  if (!lijst) { return; }

  function heeft(el, klasse) {
    return (" " + el.className + " ").indexOf(" " + klasse + " ") > -1;
  }
  function zet(el, klasse, aan) {
    if (aan === heeft(el, klasse)) { return; }
    if (aan) {
      el.className = el.className + " " + klasse;
    } else {
      el.className = (" " + el.className + " ")
        .split(" " + klasse + " ").join(" ")
        .replace(/^\\s+|\\s+$/g, "");
    }
  }
  function koppel(id, aanKlasse, uitKlasse, aanTekst, uitTekst, koekje) {
    var knop = document.getElementById(id);
    if (!knop) { return; }
    knop.onclick = function () {
      var aan = !heeft(lijst, aanKlasse);
      zet(lijst, aanKlasse, aan);
      if (uitKlasse) { zet(lijst, uitKlasse, !aan); }
      knop.innerHTML = aan ? aanTekst : uitTekst;
      // De URL meeschuiven, zodat verversen of een link delen dezelfde stand
      // geeft. Kan de browser dat niet, dan blijft alleen de weergave over.
      if (koekje) {
        document.cookie = koekje + "=" + (aan ? "1" : "0") + ";path=/;max-age=31536000";
      }
      if (window.history && window.history.replaceState) {
        var vorige = window.location.href;
        window.history.replaceState(null, "", knop.href);
        knop.href = vorige;
      }
      return false;
    };
  }

  koppel("knop-raster", "raster", "lijst", "Als lijst", "Als raster", "bookpal_raster");
  koppel(
    "knop-verberg", "verbergen", null, "Alles tonen", "Gelezen verbergen", "bookpal_verberg"
  );
})();
"""


def _page(title: str, body: str, opts: LiteOptions | None = None) -> HTMLResponse:
    html = (
        "<!doctype html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f"<style>{_STYLE}</style>"
        f"</head><body>{body}"
        # Onderaan, na de inhoud: dan staat de lijst er al als het script
        # draait, en hoeft er niet op een gebeurtenis gewacht te worden.
        f"<script>{_SCRIPT}</script>"
        "</body></html>"
    )
    response = HTMLResponse(html)
    if opts is not None:
        # Onthouden wat je koos, zodat de volgende pagina hem meeneemt zonder
        # dat elke link hem hoeft te dragen.
        response.set_cookie(COOKIE_GRID, "1" if opts.grid else "0", max_age=COOKIE_MAX_AGE)
        response.set_cookie(COOKIE_HIDE, "1" if opts.hide_read else "0", max_age=COOKIE_MAX_AGE)
    return response


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

    def reading_query(self) -> str:
        """Alleen wat over het lezen gaat, niet over de weergave.

        Raster en verbergen zitten in een cookie: dat zijn voorkeuren en geen
        eigenschappen van een link. Zonder deze scheiding zou het scriptje na
        het omschakelen ook nog elke link in de lijst moeten herschrijven.
        """
        return self.query(raster=False, verberg=False)

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


#: Waarin de weergavekeuze wordt onthouden. Een jaar, want dit is een
#: voorkeur en geen sessie.
COOKIE_GRID = "bookpal_raster"
COOKIE_HIDE = "bookpal_verberg"
COOKIE_MAX_AGE = 365 * 24 * 3600


def _options(
    request: Request,
    profile: str | None = ProfileParam,
    vertaal: bool = Query(default=False),
    verberg: bool | None = Query(default=None, description="Verberg wat je al uit hebt."),
    snij: bool = Query(default=False, description="Egale rand rond de pagina weghalen."),
    contrast: int = Query(default=100, ge=50, le=200),
    raster: bool | None = Query(default=None, description="Omslagen naast elkaar."),
) -> LiteOptions:
    """De instellingen voor deze pagina.

    Wat in de URL staat wint; staat het er niet, dan geldt wat je de vorige keer
    koos. Zo hoeft niet elke link in de lijst je weergavekeuze mee te dragen.
    """

    def uit_cookie(naam: str) -> bool:
        return request.cookies.get(naam) == "1"

    return LiteOptions(
        profile=profile,
        translated=vertaal,
        hide_read=uit_cookie(COOKIE_HIDE) if verberg is None else verberg,
        crop=snij,
        contrast=contrast,
        grid=uit_cookie(COOKIE_GRID) if raster is None else raster,
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


def _list(items: str, opts: LiteOptions) -> str:
    """De lijst zelf, met de klassen die de weergave bepalen."""
    klassen = ["raster" if opts.grid else "lijst"]
    if opts.hide_read:
        klassen.append("verbergen")
    return f'<ul id="lijst" class="{" ".join(klassen)}">{items}</ul>'


def _card(href: str, cover: str, naam: str, *, index: int, done: bool = False) -> str:
    """Eén regel én één tegel: dezelfde html, de stijl maakt het verschil.

    Dat het in beide weergaven identiek is, is het hele punt: dan kan het
    schakelen tussen lijst en raster een klasse omzetten in plaats van de pagina
    opnieuw op te halen. Op e-ink scheelt dat een volle schermverversing.

    Elke derde krijgt een merkteken: in het raster valt de rechtermarge daar weg,
    anders past hij net niet meer op de regel.
    """
    klassen = []
    if index % 3 == 2:
        klassen.append("derde")
    if done:
        klassen.append("uit")
    rand = f' class="{" ".join(klassen)}"' if klassen else ""
    return (
        f"<li{rand}><a href=\"{href}\">"
        f'<img src="{cover}" alt="" loading="lazy">'
        f'<span class="naam">{naam}</span></a></li>'
    )


def _toolbar(knoppen: list[tuple[str, str, str | None]]) -> str:
    """Een rij knoppen die naast elkaar past.

    De breedte staat in een klasse en niet in flexbox: de Kobo-browser kent dat
    niet, en dan wordt elke knop een eigen regel. Het derde veld is een id, zodat
    het scriptje de knop kan vinden die hij zonder herladen kan afhandelen.
    """
    if not knoppen:
        return ""
    klasse = {1: "een", 2: "twee"}.get(len(knoppen), "twee")
    regels = []
    for index, (label, href, knop_id) in enumerate(knoppen):
        # De laatste zonder rechtermarge, anders valt hij van de regel af.
        rand = ' class="laatste"' if index == len(knoppen) - 1 else ""
        merk = f' id="{knop_id}"' if knop_id else ""
        regels.append(f'<a{merk}{rand} href="{href}">{escape(label)}</a>')
    return f'<div class="tools {klasse}">{"".join(regels)}</div>' 

def _hide_toggle(pad: str, opts: LiteOptions) -> str:
    """De schakelaar zelf: een gewone link naar dezelfde pagina."""
    doel = f"{pad}{opts.query(verberg=not opts.hide_read)}"
    label = "Alles tonen" if opts.hide_read else "Gelezen verbergen"
    return _toolbar([(label, doel, "knop-verberg")])


@router.get("", response_class=HTMLResponse)
def lite_home(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=200),
    opts: LiteOptions = OptionsParam,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Alle series. Tabs (M3) filteren dit later; nu nog de volle lijst."""
    user = current_user(session)
    # Een serie is "uit" als er geen enkel deel meer openstaat. We filteren hem
    # niet weg maar merken hem: dan kan het verbergen een klasse omzetten in
    # plaats van de pagina opnieuw op te halen, en klopt de paginering ook nog.
    openstaand = set(
        session.scalars(
            select(Book.series_id)
            .outerjoin(
                Progress,
                (Progress.book_id == Book.id) & (Progress.user_id == user.id),
            )
            .where((Progress.id.is_(None)) | (Progress.finished.is_(False)))
        ).all()
    )
    # Een serie zonder boeken heb je niet uit; die heeft alleen niets. Zonder
    # dit onderscheid verdwijnt een lege serie zodra je uitgelezen verbergt, en
    # dan zoek je je scheel naar waar hij gebleven is.
    met_boeken = set(session.scalars(select(Book.series_id).distinct()).all())

    total = int(session.scalar(select(func.count(Series.id))) or 0)
    rows = session.scalars(
        select(Series).order_by(Series.sort_title).offset(offset).limit(limit)
    ).all()

    items = "".join(
        _card(
            f"/lite/series/{s.id}{opts.reading_query()}",
            f"/api/series/{s.id}/cover{_cover_query(opts.profile)}",
            escape(s.title),
            index=index,
            done=s.id in met_boeken and s.id not in openstaand,
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

    body = f"<h1>BookPal</h1>{_continue_block(session, opts)}"
    body += f"{_view_tools('/lite', opts)}{_list(items, opts)}"
    if not rows:
        body += (
            "<p>Niets open.</p>"
            if opts.hide_read
            else "<p>Nog geen series; draai een scan.</p>"
        )
    if nav:
        body += f'<div class="nav">{nav}</div>'
    return _page("BookPal", body, opts)


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
                f"/lite/books/{book.id}{opts.reading_query()}",
                f"/api/books/{book.id}/cover{_cover_query(opts.profile)}",
                f"{escape(label)}{meta}",
                index=len(rows),
                done=prog is not None and prog.finished,
            )
        )

    body = (
        f'<a class="back" href="/lite{opts.query()}">&laquo; Bibliotheek</a>'
        f"<h1>{escape(series.title)}</h1>"
        f"{_view_tools(f'/lite/series/{series.id}', opts)}"
        f"{_list(''.join(rows), opts)}"
    )
    if not rows:
        body += "<p>Niets open in deze serie.</p>"
    return _page(series.title, body, opts)


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
    knoppen: list[tuple[str, str, str | None]] = [
        (
            "Bijsnijden: " + ("aan" if opts.crop else "uit"),
            basis + opts.query(snij=not opts.crop),
            None,
        )
    ]
    volgend_contrast = {100: 130, 130: 160, 160: 100}.get(opts.contrast, 100)
    knoppen.append(
        (
            f"Contrast: {opts.contrast}%",
            basis + opts.query(contrast=volgend_contrast),
            None,
        )
    )
    return _toolbar(knoppen)


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
                "knop-raster",
            ),
            (
                "Alles tonen" if opts.hide_read else "Gelezen verbergen",
                f"{basis}{opts.query(verberg=not opts.hide_read)}",
                "knop-verberg",
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
