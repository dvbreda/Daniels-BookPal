"""De bibliotheekscanner.

Incrementeel van opzet: een bestand waarvan grootte en mtime niet veranderd
zijn wordt niet eens geopend. Dat is het verschil tussen een rescan van seconden
en één van een half uur op een collectie van duizenden bestanden.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.formats import FORMAT_KINDS, SUPPORTED_EXTENSIONS, detect_format, open_book
from bookpal.formats.base import BookMetadata
from bookpal.library import editions, sidecars
from bookpal.metadata import (
    ParsedName,
    from_embedded,
    from_root_default,
    normalise_number,
    parse_filename,
    resolve,
    sort_title,
)
from bookpal.metadata.origin import Origin
from bookpal.metadata.titles import normalise as normalise_title
from bookpal.models import Book, BookKind, File, LibraryRoot, OriginRegion, Series, utcnow

logger = logging.getLogger(__name__)

# Hoeveel bytes er in de vinger-afdruk gaan. Een volledige hash van een cbz van
# een halve gigabyte kost meer dan hij oplevert; kop plus grootte is genoeg om
# duplicaten te herkennen.
HASH_BYTES = 65536

# Als een root ineens leeg lijkt terwijl er nog zoveel bestanden in de database
# staan, gaan we ervan uit dat de mount weg is in plaats van dat de collectie
# verdwenen is.
EMPTY_ROOT_GUARD = 5


class ScanAborted(Exception):
    """De root is onbereikbaar of verdacht leeg — we raken de database niet aan."""


@dataclass(slots=True)
class ScanResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


def partial_hash(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    digest.update(str(size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(HASH_BYTES))
    return digest.hexdigest()


def iter_book_files(root_path: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if any(part.startswith(".") or part == "__MACOSX" for part in path.parts):
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            found.append(path)
    return found


#: Vanaf welk deel van de bestanden in een map hun mapnaam moeten dragen
#: voordat die map de reeks is. Hoog genoeg dat een categoriemap ("boeken",
#: "sci-fi") er niet doorheen glipt, laag genoeg dat één afwijkend bestand de
#: herkenning niet omgooit.
_MAPNAAM_DREMPEL = 0.6


#: Wat tussen haakjes staat is een aanduiding en geen deel van de naam:
#: "Gardeners World (UK)" is dezelfde reeks als wat er in de bestanden staat.
#: Zonder dit viel die map door de drempel omdat "uk" nergens in de
#: bestandsnamen voorkomt.
_HAAKJES = re.compile(r"[(\[{][^)\]}]*[)\]}]")


def _normaliseer(tekst: str, *, is_mapnaam: bool = False) -> str:
    if is_mapnaam:
        tekst = _HAAKJES.sub(" ", tekst)
    return re.sub(r"[^a-z0-9]", "", tekst.lower())


@lru_cache(maxsize=256)
def _map_is_reeks(map_: Path, naam: str) -> bool:
    """Dragen de meeste bestanden in deze map de mapnaam?

    Zo herken je een reeks zonder dat iemand het hoeft in te stellen: de
    zestien Lego-catalogi heten allemaal `1989-LEGO-Catalog-...` en staan in
    een map "Lego", dus die map ís de reeks. Een categoriemap valt er vanzelf
    buiten — in "boeken" staan titels die niets met het woord boeken te maken
    hebben.

    Gecached per map: dit wordt voor elk bestand in dezelfde map gevraagd, en
    dan is één keer kijken genoeg.
    """
    sleutel = _normaliseer(naam, is_mapnaam=True)
    if len(sleutel) < 3:
        return False
    try:
        bestanden = [p for p in map_.rglob("*") if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return False
    if len(bestanden) < 2:
        return False
    raak = sum(1 for p in bestanden if sleutel in _normaliseer(p.stem))
    return raak / len(bestanden) >= _MAPNAAM_DREMPEL


def _jaargang_uit_pad(path: Path, root_path: Path) -> str | None:
    """Een tussenmap die alleen een nummer is: de jaargang.

    Alleen de diepste, en alleen als er meer dan één maplaag is — anders zou
    een reeks die toevallig "2000" heet zichzelf als deel opgeven.
    """
    try:
        delen = path.parent.relative_to(root_path).parts
    except ValueError:
        return None
    if len(delen) < 2:
        return None
    for stuk in reversed(delen[1:]):
        if stuk.isdigit():
            return str(int(stuk))
    return None


def _bovenste_map(path: Path, root_path: Path) -> str | None:
    """De eerste map onder de wortel, of niets als het bestand er los in ligt.

    De bóvenste en niet de directe map, want drukwerk staat vaak een laag
    dieper: `Power Unlimited 30 jaar/jaargangen/17/188.PDF`. De directe map is
    daar de jaargang (17) en de reeksnaam staat twee niveaus hoger — nemen we
    de directe map, dan krijg je zeventien series die "1" tot "17" heten.
    """
    try:
        deel = path.parent.relative_to(root_path)
    except ValueError:
        return None
    return deel.parts[0] if deel.parts else None


def _series_title(meta: BookMetadata, path: Path, root_path: Path, kind: BookKind) -> str:
    """De serie waar dit bestand bij hoort, van sterk naar zwak signaal.

    Expliciete metadata wint altijd. Daarna loopt het uiteen per soort, en dat
    verschil is wezenlijk:

    * **Strips** — een eigen submap betekent een serie. Wie zijn bestanden in
      ``Crayon Shin-Chan/`` zet, zegt daarmee dat het één reeks is; hetzelfde
      uitgangspunt als Komga en Kavita. De bestandsnaam is hier het zwakste
      signaal, want de titel staat er lang niet altijd vooraan:
      ``Vol.15 Ch.005.002 - Part 002 - ... - Crayon Shin-chan.cbz`` levert bij
      ontleden per hoofdstuk een eigen "serie" op, en één map wordt tachtig
      reeksen.
    * **Boeken** — een map is daar juist meestal een categorie ("boeken",
      "sci-fi") en niet een reeks. Een epub of pdf is in zijn eentje een boek,
      dus de eigen titel gaat vóór de map.
    """
    if meta.series:
        return meta.series.strip()

    parent = path.parent
    in_subfolder = parent != root_path

    if kind is BookKind.COMIC:
        if in_subfolder:
            return parent.name
        parsed = parse_filename(path.stem)
        return parsed.series or path.stem

    # Draagt vrijwel alles in de map de mapnaam, dan is die map de reeks —
    # ook als het bestand zelf een naam heeft. Zo vallen de zestien
    # Lego-catalogi onder één reeks in plaats van elk hun eigen, zonder dat
    # iemand dat hoeft in te stellen.
    bovenste = _bovenste_map(path, root_path)
    if bovenste and _map_is_reeks(root_path / bovenste, bovenste):
        return bovenste

    # Boeken: eigen titel eerst, map als laatste redmiddel.
    if meta.title:
        return meta.title.strip()
    parsed = parse_filename(path.stem, folder=_bovenste_map(path, root_path))
    if parsed.series:
        return parsed.series
    if in_subfolder:
        return parent.name
    return path.stem


def _get_or_create_series(
    session: Session, root: LibraryRoot, title: str, folder: Path | None
) -> Series:
    existing = session.scalar(
        select(Series).where(Series.library_root_id == root.id, Series.title == title)
    )
    if existing is not None:
        return existing
    series = Series(
        title=title,
        sort_title=sort_title(title),
        library_root_id=root.id,
        folder_path=str(folder) if folder else None,
    )
    session.add(series)
    session.flush()
    return series


def _apply_origin(series: Series, meta: BookMetadata, root: LibraryRoot, kind: BookKind) -> None:
    """Werk de herkomst bij volgens de keten uit ``metadata.origin``.

    Een handmatige keuze blijft staan doordat ``resolve`` de huidige waarde als
    kandidaat meeneemt met zijn eigen rangorde.
    """
    current = Origin(
        language=series.origin_language,
        country=series.origin_country,
        region=series.origin_region,
        source=series.origin_source,
    )
    embedded = from_embedded(
        publisher=meta.publisher or meta.raw.get("Publisher"),
        language=meta.language or meta.raw.get("LanguageISO"),
        manga_flag=meta.raw.get("Manga"),
        weak_language_ok=kind is BookKind.COMIC,
    )
    root_default = from_root_default(root.default_origin_language, root.default_origin_region)
    best = resolve(embedded, root_default, current=current)
    series.origin_language = best.language
    series.origin_country = best.country
    series.origin_region = best.region
    series.origin_source = best.source


def _index_file(session: Session, root: LibraryRoot, path: Path, file_row: File) -> None:
    """Lees het bestand uit en werk Series en Book bij."""
    fmt = detect_format(path)
    if fmt is None:
        raise ValueError(f"onbekend formaat: {path.name}")

    with open_book(path, fmt) as book_file:
        meta = book_file.metadata()
        page_count = book_file.page_count()

    root_path = Path(root.path)
    # De mapnaam meegeven als het bestand in een submap staat. Alleen dán kan
    # `parse_filename` terugvallen op de map voor een naam die zelf niets meer
    # is dan een nummer — `Power Unlimited 30 jaar/001.PDF`. Zonder dit werd
    # "001" de serienaam en kreeg je net zoveel series als afleveringen.
    map_naam = path.parent.name if path.parent != root_path else None
    parsed = parse_filename(path.stem, folder=map_naam)
    series_title = _series_title(meta, path, root_path, FORMAT_KINDS[fmt])
    folder = path.parent.relative_to(root_path) if path.parent != root_path else None
    series = _get_or_create_series(session, root, series_title, folder)

    if meta.publisher and not series.publisher:
        series.publisher = meta.publisher
    if meta.tags:
        series.tags = list(dict.fromkeys([*series.tags, *meta.tags]))
    if meta.authors:
        # Samenvoegen in plaats van overschrijven: een serie heeft vaak een
        # tekenaar naast een schrijver, en die staan zelden in hetzelfde deel.
        # dict.fromkeys houdt de volgorde aan waarin ze langskomen.
        series.authors = list(dict.fromkeys([*series.authors, *meta.authors]))
    if meta.summary and not series.summary:
        series.summary = meta.summary
    _apply_origin(series, meta, root, FORMAT_KINDS[fmt])

    number = meta.number or parsed.number
    book = session.scalar(select(Book).where(Book.file_id == file_row.id))
    if book is None:
        book = Book(series_id=series.id, file_id=file_row.id, kind=FORMAT_KINDS[fmt], title="")
        session.add(book)

    if book.source_ref is not None:
        # Dit hoofdstuk komt van een abonnement (M5) en is daar al ingedeeld en
        # benoemd. De scanner weet hier minder dan de bron: de bestandsnaam van
        # een download zegt niets over volgorde of titel, en het boek staat in
        # de serie van het abonnement. Alleen wat de scanner écht als enige
        # weet — dat het bestand er is en hoeveel pagina's het heeft — mag hij
        # bijwerken. Zonder deze uitzondering trok elke scan zulke hoofdstukken
        # uit hun abonnement en in een serie die op de mapnaam was verzonnen.
        book.page_count = page_count
        session.flush()
        return

    book.series_id = series.id
    book.kind = FORMAT_KINDS[fmt]

    # De sidecar naast het bestand wint van wat de bestandsnaam suggereert: hij
    # is er gekomen doordat iemand — jij of een bron — het beter wist. Staat er
    # niets, dan schrijven we wat we nu weten alsnog weg, zodat het een
    # herinstallatie overleeft.
    zijkant = sidecars.read(path)
    uit_sidecar = zijkant.title(settings.translate_lang) if zijkant else None
    if uit_sidecar:
        book.title = uit_sidecar
        book.title_locked = True
    elif not book.title_locked:
        book.title = _chapter_title(meta, parsed, path, series, number)
    if zijkant is not None and zijkant.cover_page is not None:
        book.cover_page_index = zijkant.cover_page

    book.number = number
    book.sort_number = normalise_number(number)
    # De jaargang uit de mapnaam als er verder geen deel bekend is. Bij
    # drukwerk staat die als losse laag in het pad — `.../jaargangen/17/188.PDF`
    # is nummer 188 in jaargang 17 — en dat is echte informatie: zonder deze
    # regel staan achttien jaargangen door elkaar op alleen het nummer.
    book.volume = meta.volume or parsed.volume or _jaargang_uit_pad(path, root_path)
    book.sort_volume = normalise_number(book.volume)
    book.page_count = page_count
    # Manga leest van rechts naar links; het ComicInfo-veld is de enige plek
    # waar dat expliciet in staat.
    book.right_to_left = meta.right_to_left or series.origin_region is OriginRegion.JAPAN
    # Je eigen bestanden vormen samen één uitgave. Dat is pas zichtbaar zodra
    # er een tweede bij komt — een online bron of een tweede druk — maar het
    # moet er wel vanaf het begin staan, anders valt er later niets te ordenen.
    if book.edition_id is None:
        book.edition_id = editions.for_local_files(session, series).id
    session.flush()

    if zijkant is None:
        _write_sidecar(path, book, series, herkomst="filename")


def _write_sidecar(path: Path, book: Book, series: Series, *, herkomst: str) -> None:
    """Leg naast het bestand vast wat we van dit boek weten.

    Alleen aanvullen: wat er al staat met een zwaardere herkomst blijft staan.
    Zo overschrijft een scan nooit een titel die jij hebt ingetypt.
    """
    zijkant = sidecars.read(path) or sidecars.Sidecar()
    veranderd = zijkant.set_title(book.title, herkomst=herkomst)
    if zijkant.series != series.title:
        zijkant.series = series.title
        veranderd = True
    if zijkant.number != book.number or zijkant.volume != book.volume:
        zijkant.number = book.number
        zijkant.volume = book.volume
        veranderd = True
    if series.authors and zijkant.authors != list(series.authors):
        zijkant.authors = list(series.authors)
        veranderd = True
    if book.cover_page_index is not None and zijkant.cover_page != book.cover_page_index:
        zijkant.cover_page = book.cover_page_index
        zijkant.origin["cover_page"] = herkomst
        veranderd = True
    if veranderd:
        sidecars.write(path, zijkant)


def _chapter_title(
    meta: BookMetadata, parsed: ParsedName, path: Path, series: Series, number: str | None
) -> str:
    """Hoe dit hoofdstuk heet.

    Wat het bestand zelf zegt wint, dan wat de naam prijsgeeft. Met één
    uitzondering: veel scanlations heten "Reeks Chapter 01 - Tekenaar.cbz", en
    dan houdt de parser de tekenaar voor een titel. Elk hoofdstuk heet dan naar
    dezelfde persoon, wat nergens op slaat en de hele lijst onleesbaar maakt.
    """
    kandidaat = meta.title or parsed.title
    if kandidaat and _is_author(kandidaat, series):
        kandidaat = None
    if kandidaat:
        return kandidaat
    return f"Hoofdstuk {number}" if number else path.stem


def _is_author(kandidaat: str, series: Series) -> bool:
    """Is dit de naam van de maker in plaats van een titel?

    Genormaliseerd vergeleken, want dezelfde persoon heet in de bestandsnaam
    "Yarō Abe" en bij de bron "Abe Yarou" — en dan nog omgedraaid ook.
    """
    doel = normalise_title(kandidaat)
    if not doel:
        return False
    for auteur in series.authors or []:
        genormaliseerd = normalise_title(auteur)
        if not genormaliseerd:
            continue
        if genormaliseerd == doel:
            return True
        # Voor- en achternaam omgedraaid telt ook: "Abe Yarou" naast "Yarou Abe".
        delen = sorted(normalise_title(deel) for deel in auteur.split())
        if delen and delen == sorted(normalise_title(deel) for deel in kandidaat.split()):
            return True
    return False


def scan_root(session: Session, root: LibraryRoot, *, force: bool = False) -> ScanResult:
    """Scan één library-root.

    ``force`` negeert de mtime-controle en leest elk bestand opnieuw uit.
    """
    result = ScanResult()
    root_path = Path(root.path)
    if not root_path.is_dir():
        raise ScanAborted(f"library-root {root.path!r} is niet bereikbaar")

    known_count = session.scalar(select(File.id).where(File.library_root_id == root.id).limit(1))
    on_disk = iter_book_files(root_path)
    if not on_disk and known_count is not None:
        existing_total = len(
            session.scalars(select(File.id).where(File.library_root_id == root.id)).all()
        )
        if existing_total >= EMPTY_ROOT_GUARD:
            # Vrijwel zeker een niet-gemounte NAS-share. Niets verwijderen.
            raise ScanAborted(
                f"library-root {root.path!r} is leeg terwijl er {existing_total} bestanden "
                "bekend zijn — mount waarschijnlijk niet beschikbaar, scan afgebroken"
            )

    existing_files = {
        row.path: row
        for row in session.scalars(select(File).where(File.library_root_id == root.id))
    }
    seen: set[str] = set()

    for path in on_disk:
        key = str(path)
        seen.add(key)
        try:
            stat = path.stat()
        except OSError as exc:
            result.errors.append(f"{path.name}: {exc}")
            continue

        file_row = existing_files.get(key)
        unchanged = (
            file_row is not None
            and not force
            and not file_row.missing
            and file_row.size == stat.st_size
            and abs(file_row.mtime - stat.st_mtime) < 0.001
        )
        if unchanged:
            result.unchanged += 1
            continue

        is_new = file_row is None
        if file_row is None:
            file_row = File(
                library_root_id=root.id,
                path=key,
                size=stat.st_size,
                mtime=stat.st_mtime,
                extension=path.suffix.lower(),
            )
            session.add(file_row)
        else:
            file_row.size = stat.st_size
            file_row.mtime = stat.st_mtime
            file_row.extension = path.suffix.lower()
            file_row.missing = False
        session.flush()

        try:
            file_row.content_hash = partial_hash(path, stat.st_size)
            _index_file(session, root, path, file_row)
        except Exception as exc:  # één kapot bestand mag de scan niet stoppen
            logger.warning("kon %s niet indexeren: %s", path, exc)
            result.errors.append(f"{path.name}: {exc}")
            session.flush()
            continue

        if is_new:
            result.added += 1
        else:
            result.updated += 1

    for path_str, file_row in existing_files.items():
        if path_str in seen:
            continue
        session.delete(file_row)
        result.removed += 1

    session.flush()
    _prune(session, root)
    root.last_scan_at = utcnow()
    session.flush()
    return result


def _prune(session: Session, root: LibraryRoot) -> None:
    """Ruim boeken op zonder bestand én zonder bron, en daarna lege series.

    Een geabonneerd hoofdstuk (``source_ref``) blijft staan als de tijdelijke
    download verdwijnt — dat is precies het punt van readahead.
    """
    orphan_books = session.scalars(
        select(Book)
        .join(Series, Book.series_id == Series.id)
        .where(
            Series.library_root_id == root.id,
            Book.file_id.is_(None),
            Book.source_ref.is_(None),
        )
    ).all()
    for book in orphan_books:
        session.delete(book)
    session.flush()

    empty_series = session.scalars(
        select(Series).where(Series.library_root_id == root.id, ~Series.books.any())
    ).all()
    for series in empty_series:
        session.delete(series)
    session.flush()


def scan_all(session: Session, *, force: bool = False) -> dict[str, ScanResult]:
    results: dict[str, ScanResult] = {}
    for root in session.scalars(select(LibraryRoot).where(LibraryRoot.enabled.is_(True))):
        try:
            results[root.name] = scan_root(session, root, force=force)
        except ScanAborted as exc:
            failed = ScanResult()
            failed.errors.append(str(exc))
            results[root.name] = failed
    return results
