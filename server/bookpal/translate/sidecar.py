"""Vertalingen blijvend bewaren naast de collectie (M8).

Een vertaling kost geld — bij de beeldstanden tientallen centen per pagina. Die
mag daarom niet alleen in de database staan: een database opnieuw opbouwen (of
een scan die misgaat) zou betekenen dat je opnieuw betaalt voor werk dat al
gedaan is. Alles wat een vertaler oplevert komt hier op schijf te staan, in een
mappenstructuur die je zelf kunt lezen en kopiëren:

    <serie>/.sidecars/v03c012/p0007-nl.json            tekstvlakken
    <serie>/.sidecars/v03c012/p0007-nl-image_pro.webp  hele pagina, duur model
    <serie>/.sidecars/v03c012/p0007-kleur.webp         ingekleurd

Naast de serie in je eigen bibliotheek dus, en niet in een aparte map ergens in
een Docker-volume. Dat is waar je het zoekt als je in je bestandsbeheer staat te
kijken, net als bij ondertitels bij een videobestand. De map heet `.sidecars`
met een punt ervoor: verborgen in het dagelijks gebruik, en de scanner slaat
alles met een punt sowieso over, dus hij kan zichzelf nooit als collectie
terugvinden.

Binnen `.sidecars` staan de hoofdstukmappen zonder punt. Eén verborgen laag is
genoeg; ben je er eenmaal, dan wil je gewoon zien wat er is.

De database blijft de snelle index; de schijf is de waarheid. Bij het vertalen
wordt eerst hier gekeken, dus een bestaand bestand bespaart een aanroep.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, object_session

from bookpal.config import settings
from bookpal.models import Book, LibraryRoot, OriginRegion, Series
from bookpal.translate.modes import TranslateMode

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text: str, *, fallback: str, limit: int = 120) -> str:
    cleaned = _UNSAFE.sub("", text).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:limit].strip() or fallback


#: De verborgen map in de seriemap waar alles van ons in komt.
SIDECAR_DIRNAME = ".sidecars"


def chapter_slug(book: Book) -> str:
    """De mapnaam van één hoofdstuk.

    Met nullen ervoor, zodat een `ls` in leesvolgorde staat in plaats van
    1, 10, 2 — dezelfde reden als bij de bestandsnamen die we bij importeren
    gebruiken. Deel en hoofdstuk allebei erin als ze er zijn, want bij manga
    begint de nummering per deel vaak opnieuw.
    """
    delen = []
    if book.volume:
        delen.append(f"v{_nummer(book.volume, breedte=2)}")
    if book.number:
        delen.append(f"c{_nummer(book.number, breedte=3)}")
    if delen:
        return "".join(delen)
    # Geen nummers: dan is de titel het enige onderscheid dat je zelf herkent.
    return safe_name(book.title or "", fallback=f"boek-{book.id}", limit=60)


def _nummer(waarde: str, *, breedte: int) -> str:
    """ "12" -> "012", "12.5" -> "012.5", "Extra" -> "Extra"."""
    try:
        getal = float(waarde)
    except ValueError:
        return safe_name(waarde, fallback="x", limit=20)
    heel = int(getal)
    rest = f"{getal:g}".partition(".")[2]
    return f"{heel:0{breedte}d}" + (f".{rest}" if rest else "")


def series_home(series: Series | None, book: Book) -> Path:
    """De map waarin de `.sidecars` van deze serie komt te staan.

    Eenmaal gekozen wordt het onthouden op de serie: een serie kan verhuizen
    (van download naar je eigen map bijvoorbeeld), en dan zou een steeds
    opnieuw uitgerekend pad ineens ergens anders uitkomen — met alle betaalde
    vertalingen achter op de oude plek.
    """
    if series is None:
        return settings.sidecar_dir / f"serie-{book.series_id}"
    if series.sidecar_path:
        return Path(series.sidecar_path)

    gekozen = _pick_home(series)
    session = object_session(series)
    if session is not None:
        series.sidecar_path = str(gekozen)
        session.flush()
    return gekozen


def _pick_home(series: Series) -> Path:
    """Waar deze serie hoort, ook als er nog geen bestand van is.

    Een serie die je alleen online volgt krijgt gewoon een map in je
    bibliotheek: dan staat de vertaling klaar op de plek waar de bestanden
    komen zodra je ze importeert.
    """
    session = object_session(series)
    naam = safe_name(series.title, fallback=f"serie-{series.id}")
    if session is not None:
        root = _browsable_root(session, series)
        if root is not None:
            # Heeft de scanner al een map voor deze serie gevonden, dan is dat
            # de map — ook als hij anders heet dan de serietitel.
            if series.folder_path:
                return Path(root.path) / series.folder_path
            return Path(root.path) / naam
    return settings.sidecar_dir / naam


def _browsable_root(session: Session, series: Series) -> LibraryRoot | None:
    """Een root waar jij zelf in kunt kijken.

    De downloadmap telt niet mee: die is cache, staat in een Docker-volume en
    wordt opgeruimd. Sidecars die daarin verdwijnen zijn betaald werk kwijt.
    """
    from sqlalchemy import select

    eigen = (
        session.get(LibraryRoot, series.library_root_id)
        if series.library_root_id is not None
        else None
    )
    if eigen is not None and not _is_cache(eigen):
        return eigen

    roots = [
        root
        for root in session.scalars(select(LibraryRoot).where(LibraryRoot.enabled)).all()
        if not _is_cache(root)
    ]
    if not roots:
        return None
    # Op naam raden is niet mooi, maar het gaat om één verborgen map: bij een
    # verkeerde gok staat hij naast de verkeerde collectie, niet zoek.
    voorkeur = "manga" if series.origin_region == OriginRegion.JAPAN else "strip"
    for root in roots:
        if voorkeur in root.name.lower() or voorkeur in root.path.lower():
            return root
    return roots[0]


def _is_cache(root: LibraryRoot) -> bool:
    try:
        return Path(root.path).resolve() == settings.download_dir.resolve()
    except OSError:
        return False


def chapter_dir(series: Series | None, book: Book) -> Path:
    """Waar alles van dit ene hoofdstuk staat."""
    return series_home(series, book) / SIDECAR_DIRNAME / chapter_slug(book)


def page_stem(page_index: int) -> str:
    # Nullen ervoor zodat een `ls` in leesvolgorde staat.
    return f"p{page_index:04d}"


def json_path(series: Series | None, book: Book, page_index: int, lang: str) -> Path:
    return chapter_dir(series, book) / f"{page_stem(page_index)}-{lang}.json"


def image_path(
    series: Series | None, book: Book, page_index: int, lang: str, mode: TranslateMode
) -> Path:
    return chapter_dir(series, book) / f"{page_stem(page_index)}-{lang}-{mode.value}.webp"


def variant_path(series: Series | None, book: Book, page_index: int, variant: str) -> Path:
    """Een bewerking van de pagina die geen vertaling is, zoals inkleuren.

    Apart van ``image_path`` omdat er geen taal aan te pas komt — en omdat het
    niet met een vertaling hoort te concurreren om dezelfde plek.
    """
    return chapter_dir(series, book) / f"{page_stem(page_index)}-{variant}.webp"


def _write(path: Path, data: bytes) -> None:
    """Via een tijdelijk bestand: een half geschreven vertaling die als
    'bestaat al' wordt gezien, is erger dan geen vertaling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{threading.get_ident()}.tmp")
    temp.write_bytes(data)
    temp.replace(path)


def is_writable() -> bool:
    """Kan er daadwerkelijk bewaard worden?

    Niet vanzelfsprekend: de map komt uit een volume, en als die verkeerd
    aangekoppeld staat is hij van root terwijl de server als een gewone
    gebruiker draait. Het schrijven zelf faalt zacht — een mislukte sidecar mag
    een gelukte vertaling niet ongedaan maken — en juist daarom moet dit ergens
    zichtbaar zijn in plaats van alleen in een logregel.
    """
    probe = settings.sidecar_dir / ".schrijftest"
    try:
        settings.sidecar_dir.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return False
    return True


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Een kapot bestand mag het lezen niet blokkeren; we maken 'm gewoon
        # opnieuw aan.
        logger.warning("sidecar %s is onleesbaar; wordt genegeerd", path)
        return None
    return loaded if isinstance(loaded, dict) else None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        _write(path, json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError as exc:
        # Niet kunnen bewaren is vervelend maar niet fataal: de vertaling zelf
        # is al gelukt en staat in de database.
        logger.warning("sidecar %s niet kunnen schrijven: %s", path, exc)


def read_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        logger.warning("sidecar %s niet kunnen lezen: %s", path, exc)
        return None


def write_bytes(path: Path, data: bytes) -> None:
    try:
        _write(path, data)
    except OSError as exc:
        logger.warning("sidecar %s niet kunnen schrijven: %s", path, exc)


# -- eenmalige verhuizing ------------------------------------------------

#: Onder deze sleutel staat dat de verhuizing al gedaan is.
MOVED_KEY = "sidecars.verhuisd"


def legacy_chapter_dir(series: Series | None, book: Book) -> Path:
    """Waar de sidecars van dit hoofdstuk vroeger stonden.

    Alleen nog nodig om ze op te halen: één centrale map met alle series
    erin, op naam van serie en hoofdstuklabel.
    """
    series_name = safe_name(series.title if series else "", fallback=f"serie-{book.series_id}")
    label = " ".join(part for part in (book.number, book.title) if part).strip()
    chapter = safe_name(label, fallback=f"boek-{book.id}")
    return settings.sidecar_dir / series_name / chapter


def move_legacy(session: Session) -> int:
    """Zet oude sidecars naast hun serie. Geeft terug hoeveel bestanden er zijn
    verhuisd.

    Verplaatsen en niet kopiëren, zodat er geen twee waarheden ontstaan — maar
    wél bestand voor bestand en zonder overschrijven: staat er op de nieuwe plek
    al iets, dan is dat nieuwer en wint het.

    Met ``shutil.move`` en niet ``Path.replace``: de oude map zit in een
    Docker-volume en de nieuwe in een aangekoppelde NAS-map, en dat zijn
    verschillende apparaten. Hernoemen kan daar niet overheen; kopiëren en
    weggooien wel.
    """
    from sqlalchemy import select

    from bookpal.models import Setting

    if session.get(Setting, MOVED_KEY) is not None:
        return 0

    verhuisd = 0
    mislukt = 0
    for book in session.scalars(select(Book)).all():
        series = session.get(Series, book.series_id)
        oud = legacy_chapter_dir(series, book)
        if not oud.is_dir():
            continue
        nieuw = chapter_dir(series, book)
        try:
            nieuw.mkdir(parents=True, exist_ok=True)
            for item in oud.iterdir():
                if not item.is_file():
                    continue
                doel = nieuw / item.name
                if doel.exists():
                    item.unlink()
                    continue
                shutil.move(str(item), str(doel))
                verhuisd += 1
            # Alleen als hij leeg is; anders blijft er iets staan dat we niet
            # begrijpen, en dat gooi je niet weg.
            oud.rmdir()
        except OSError as exc:
            logger.warning("sidecars van boek %s niet verhuisd: %s", book.id, exc)
            mislukt += 1
            continue

    verhuisd += _recover_orphans(session)

    if mislukt:
        # Niet afvinken: wat er niet mee kwam is betaald werk, en een volgende
        # start hoort het opnieuw te proberen in plaats van het te vergeten.
        logger.warning("%s hoofdstukken niet verhuisd; volgende keer opnieuw", mislukt)
    else:
        session.add(Setting(key=MOVED_KEY, value={"bestanden": verhuisd}))
        session.commit()
    if verhuisd:
        logger.info("%s sidecar-bestanden naast hun serie gezet", verhuisd)
    return verhuisd


def _recover_orphans(session: Session) -> int:
    """Oude mappen waarvan de naam niet meer klopt alsnog thuisbrengen.

    Hoofdstukken zijn onderweg hernoemd — "39 Yarō Abe" heet nu "Hoofdstuk 39",
    en een serie heette toen "One Piece (Official Colored)". Die mappen waren
    ook in de oude indeling al onvindbaar, want er werd altijd op de huidige
    titel gezocht. Het nummer vooraan de mapnaam is genoeg om ze terug te
    vinden, en daar staat betaald werk in.
    """
    from sqlalchemy import select

    if not settings.sidecar_dir.is_dir():
        return 0

    series_all = list(session.scalars(select(Series)).all())
    hersteld = 0
    for series_dir in sorted(settings.sidecar_dir.iterdir()):
        if not series_dir.is_dir():
            continue
        series = _match_series(series_dir.name, series_all)
        if series is None:
            continue
        boeken = list(session.scalars(select(Book).where(Book.series_id == series.id)).all())
        for chapter_dir_old in sorted(series_dir.iterdir()):
            if not chapter_dir_old.is_dir():
                continue
            book = _match_book(chapter_dir_old.name, boeken)
            if book is None:
                continue
            doel = chapter_dir(series, book)
            try:
                doel.mkdir(parents=True, exist_ok=True)
                for item in chapter_dir_old.iterdir():
                    if not item.is_file():
                        continue
                    bestemming = doel / item.name
                    if bestemming.exists():
                        item.unlink()
                        continue
                    shutil.move(str(item), str(bestemming))
                    hersteld += 1
                chapter_dir_old.rmdir()
            except OSError as exc:
                logger.warning("wees %s niet verhuisd: %s", chapter_dir_old.name, exc)
    return hersteld


def _match_series(folder: str, series_all: list[Series]) -> Series | None:
    """De serie bij een oude mapnaam.

    Ook als er een uitgave achter stond: "One Piece (Official Colored)" is de
    map van "One Piece". De langste naam die past wint, zodat "One Piece" niet
    de map van een andere serie inpikt die er toevallig mee begint.
    """
    # Hoofdletters negeren: dezelfde serie heette ooit "Crayon Shin-chan" en
    # nu "Crayon Shin-Chan", en dat is geen reden om een map te laten staan.
    naald = folder.casefold()
    passend = [
        series
        for series in series_all
        if naald == safe_name(series.title, fallback="").casefold()
        or naald.startswith(safe_name(series.title, fallback="").casefold() + " ")
    ]
    if not passend:
        return None
    return max(passend, key=lambda series: len(series.title))


def _match_book(folder: str, boeken: list[Book]) -> Book | None:
    """Het hoofdstuk bij een oude mapnaam, op het nummer dat er vooraan staat."""
    kop = folder.split(" ", 1)[0]
    try:
        nummer = float(kop)
    except ValueError:
        return None
    for book in boeken:
        if book.number is None:
            continue
        try:
            if float(book.number) == nummer:
                return book
        except ValueError:
            continue
    return None
