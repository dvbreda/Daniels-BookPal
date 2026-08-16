"""Een compleet vertaald of ingekleurd hoofdstuk als eigen editie (M9).

Tot nu toe was een vertaling of inkleuring alleen zichtbaar ín de lezer: de
overlay komt live over de originele pagina's heen, en wie geen BookPal gebruikt
ziet er niets van. Dat is zonde van werk dat per pagina tientallen centen kost.
Zodra een heel hoofdstuk compleet is, verdient het een plek als gewoon
leesbaar bestand naast de serie — net als Monty Dons epub-edities, waar je ook
gewoon kiest welke versie je leest.

Drie soorten, onafhankelijk van elkaar compleet:

* ``VERTAALD``        elke pagina hertekend mét vertaling (de dure beeldstand)
* ``KLEUR``            elke pagina ingekleurd, originele tekst
* ``KLEUR_VERTAALD``   elke pagina ingekleurd én vertaald

Geen nieuwe samenstelling: dit pakt precies de bestanden die er al liggen
(``image_path`` en ``variant_path`` uit de sidecar) en rijgt ze aan elkaar. Er
wordt dus nooit voor deze stap zelf betaald — het is de al betaalde vertaling
alsnog leesbaar maken buiten BookPal om.

De uitgave die hierbij hoort staat achteraan in de voorkeur (net als een
nieuw abonnement): hij verschijnt vanzelf zodra een hoofdstuk compleet is,
maar wordt nooit ongevraagd je standaardkeuze. Wil je 'm als eerste keus
lezen, zet hem dan zelf naar boven in de editielijst.
"""

from __future__ import annotations

import enum
import logging
import zipfile
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.library import editions
from bookpal.models import Book, BookKind, Edition, File, LibraryRoot, OriginRegion, Series
from bookpal.translate import sidecar
from bookpal.translate.modes import TranslateMode
from bookpal.translate.service import COLOUR_VARIANT, colour_variant

logger = logging.getLogger(__name__)


class ExportKind(enum.StrEnum):
    VERTAALD = "vertaald"
    KLEUR = "kleur"
    KLEUR_VERTAALD = "kleur_vertaald"


_SUFFIX = {
    ExportKind.VERTAALD: "{lang}",
    ExportKind.KLEUR: "col",
    ExportKind.KLEUR_VERTAALD: "col.{lang}",
}

_NAAM = {
    ExportKind.VERTAALD: "Vertaald ({LANG})",
    ExportKind.KLEUR: "Ingekleurd",
    ExportKind.KLEUR_VERTAALD: "Ingekleurd + vertaald ({LANG})",
}


def export_key(kind: ExportKind, lang: str) -> str:
    """De sleutel waarop dezelfde editie wordt teruggevonden.

    ``KLEUR`` heeft geen taal in de sleutel: het lijnwerk en de originele tekst
    blijven erin staan, dus twee taalinstellingen leveren hetzelfde bestand op
    en horen dus dezelfde editie te zijn.
    """
    return kind.value if kind is ExportKind.KLEUR else f"{kind.value}:{lang}"


def _vertaalde_pagina(series: Series | None, book: Book, index: int, lang: str) -> Path | None:
    """De beste hertekende plaat voor deze pagina — pro boven fast, als beide er zijn."""
    pro = sidecar.image_path(series, book, index, lang, TranslateMode.IMAGE_PRO)
    if pro.is_file():
        return pro
    fast = sidecar.image_path(series, book, index, lang, TranslateMode.IMAGE_FAST)
    return fast if fast.is_file() else None


def _kleur_pagina(series: Series | None, book: Book, index: int) -> Path | None:
    pad = sidecar.variant_path(series, book, index, COLOUR_VARIANT)
    return pad if pad.is_file() else None


def _kleur_vertaald_pagina(series: Series | None, book: Book, index: int, lang: str) -> Path | None:
    pad = sidecar.variant_path(series, book, index, colour_variant(lang))
    return pad if pad.is_file() else None


def _paginas(series: Series | None, book: Book, kind: ExportKind, lang: str) -> list[Path] | None:
    """Alle paginabestanden voor deze editie, of ``None`` als er eentje ontbreekt."""
    if not book.page_count:
        return None
    paden: list[Path] = []
    for index in range(book.page_count):
        pad = _pagina(series, book, kind, index, lang)
        if pad is None:
            return None
        paden.append(pad)
    return paden


def _pagina(
    series: Series | None, book: Book, kind: ExportKind, index: int, lang: str
) -> Path | None:
    if kind is ExportKind.VERTAALD:
        return _vertaalde_pagina(series, book, index, lang)
    if kind is ExportKind.KLEUR:
        return _kleur_pagina(series, book, index)
    return _kleur_vertaald_pagina(series, book, index, lang)


def compleet(session: Session, book: Book, kind: ExportKind, *, lang: str | None = None) -> bool:
    """Staat elke pagina van dit hoofdstuk klaar voor deze editie?"""
    series = session.get(Series, book.series_id) if book.series_id else None
    return _paginas(series, book, kind, lang or settings.translate_lang) is not None


def _root_id_for(session: Session, pad: Path) -> int | None:
    """Bij welke ``LibraryRoot`` dit pad hoort — de langste match wint."""
    beste: LibraryRoot | None = None
    for root in session.scalars(select(LibraryRoot).where(LibraryRoot.enabled)):
        try:
            binnen = pad.is_relative_to(Path(root.path))
        except OSError:
            continue
        if binnen and (beste is None or len(root.path) > len(beste.path)):
            beste = root
    return beste.id if beste is not None else None


def _basisnaam(book: Book) -> str:
    if book.file is not None:
        return Path(book.file.path).stem
    return sidecar.safe_name(book.title or "", fallback=f"boek-{book.id}")


def _comicinfo(series: Series, book: Book, lang: str) -> bytes:
    """Genoeg om na een herbouwde database in dezelfde aflevering te vallen.

    Alleen ``Series``, ``Number`` en ``Volume`` doen er echt toe: dat is wat
    `slot_of` gebruikt om een deel bij zijn aflevering te zoeken. De rest is
    voor wie dit bestand in een andere lezer opent.
    """
    delen = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        f"<Series>{escape(series.title)}</Series>",
    ]
    if book.number:
        delen.append(f"<Number>{escape(book.number)}</Number>")
    if book.volume:
        delen.append(f"<Volume>{escape(book.volume)}</Volume>")
    delen.append(f"<LanguageISO>{escape(lang)}</LanguageISO>")
    if series.origin_region is OriginRegion.JAPAN:
        delen.append("<Manga>Yes</Manga>")
    delen.append("</ComicInfo>")
    return "".join(delen).encode("utf-8")


def _bouw_cbz(paden: list[Path], *, series: Series, book: Book, lang: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for index, pad in enumerate(paden):
            archive.writestr(f"{index:04d}{pad.suffix}", pad.read_bytes())
        archive.writestr("ComicInfo.xml", _comicinfo(series, book, lang))
    return buffer.getvalue()


def _gevonden_editie_boek(session: Session, edition: Edition, book: Book) -> Book | None:
    """Het eerder geëxporteerde deel van déze aflevering binnen deze editie."""
    sleutel = editions.slot_of(book)
    for kandidaat in session.scalars(select(Book).where(Book.edition_id == edition.id)):
        if editions.slot_of(kandidaat) == sleutel:
            return kandidaat
    return None


def exporteer(
    session: Session, book: Book, kind: ExportKind, *, lang: str | None = None
) -> Book | None:
    """Bouw de cbz en registreer 'm als editie.

    Niets doen — en ``None`` teruggeven — als het hoofdstuk voor deze soort nog
    niet compleet is, als de serie geen eigen map heeft (alleen online
    gevolgd), of als er al een actuele editie ligt. "Actueel" is: geen enkele
    bronpagina is ná de laatste export nog veranderd.
    """
    taal = lang or settings.translate_lang
    series = session.get(Series, book.series_id)
    if series is None:
        return None

    paden = _paginas(series, book, kind, taal)
    if paden is None:
        return None

    home = sidecar.series_home(series, book)
    if not home.is_dir():
        # Een serie die alleen online gevolgd wordt heeft nog geen echte map;
        # daar kan geen leesbaar bestand naast staan totdat er iets
        # geïmporteerd is.
        return None

    sleutel = export_key(kind, taal)
    edition = session.scalar(
        select(Edition).where(Edition.series_id == series.id, Edition.export_key == sleutel)
    )
    bestaand = _gevonden_editie_boek(session, edition, book) if edition is not None else None

    recentste_bron = max(pad.stat().st_mtime for pad in paden)
    if bestaand is not None and bestaand.file is not None and bestaand.file.mtime >= recentste_bron:
        return bestaand

    doelnaam = f"{_basisnaam(book)}.{_SUFFIX[kind].format(lang=taal)}.cbz"
    doel = home / doelnaam
    data = _bouw_cbz(paden, series=series, book=book, lang=taal)
    # Via een tijdelijk bestand: een half geschreven editie mag de scanner
    # nooit als geldig archief tegenkomen.
    tijdelijk = doel.with_suffix(doel.suffix + ".partial")
    tijdelijk.write_bytes(data)
    tijdelijk.replace(doel)
    stat = doel.stat()

    if edition is None:
        edition = editions.for_export(
            session, series, export_key=sleutel, name=_NAAM[kind].format(LANG=taal.upper())
        )

    file_row = session.scalar(select(File).where(File.path == str(doel)))
    if file_row is None:
        file_row = File(
            library_root_id=_root_id_for(session, doel),
            path=str(doel),
            size=stat.st_size,
            mtime=stat.st_mtime,
            extension=".cbz",
        )
        session.add(file_row)
    else:
        file_row.size = stat.st_size
        file_row.mtime = stat.st_mtime
        file_row.missing = False
    session.flush()

    editie_boek = bestaand or Book(series_id=series.id, kind=BookKind.COMIC, title=book.title)
    editie_boek.series_id = series.id
    editie_boek.kind = BookKind.COMIC
    editie_boek.title = book.title
    editie_boek.number = book.number
    editie_boek.sort_number = book.sort_number
    editie_boek.volume = book.volume
    editie_boek.sort_volume = book.sort_volume
    editie_boek.right_to_left = book.right_to_left
    editie_boek.title_locked = True
    editie_boek.edition_id = edition.id
    editie_boek.file_id = file_row.id
    editie_boek.page_count = len(paden)
    session.add(editie_boek)
    session.flush()
    logger.info(
        "editie %s aangemaakt voor boek %s: %s (%s pagina's)", sleutel, book.id, doel, len(paden)
    )
    return editie_boek


def probeer_alle(session: Session, book: Book) -> list[Book]:
    """Na elke voltooide pagina: kijk of er nu een editie compleet is.

    Loopt over alle drie de soorten, want de een kan af zijn zonder de ander —
    tekst en kleur lopen los van elkaar. Een schrijffout wordt alleen gelogd:
    dit is opruimwerk ná het betaalde werk, en mag het antwoord aan de lezer
    niet laten mislukken.
    """
    gemaakt: list[Book] = []
    for kind in ExportKind:
        try:
            resultaat = exporteer(session, book, kind)
        except OSError as exc:
            logger.warning("editie (%s) voor boek %s niet weggeschreven: %s", kind, book.id, exc)
            continue
        if resultaat is not None:
            gemaakt.append(resultaat)
    return gemaakt


__all__ = ["ExportKind", "compleet", "export_key", "exporteer", "probeer_alle"]
