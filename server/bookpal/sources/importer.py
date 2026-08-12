"""Een gevolgde serie omzetten naar gewone bestanden in je eigen mappen.

Een abonnement (M5) houdt hoofdstukken als verwijzing en haalt ze tijdelijk op;
na de TTL gaat het bestand weer weg. Prima om bij te blijven, niet wat je wilt
voor een serie die je houdt. Importeren maakt er blijvende bestanden van, in de
mappenstructuur die de scanner toch al leest:

    <root>/<Serie>/<Serie> - 012 - Titel.cbz

Twee dingen die dit bewust *niet* doet:

* **Niets weggooien.** Bestanden worden verplaatst, nooit verwijderd, en een
  bestand dat er al staat wordt overgeslagen in plaats van overschreven.
* **Niet opnieuw downloaden wat er al is.** Een hoofdstuk dat al opgehaald is
  verhuist gewoon; alleen wat ontbreekt gaat de lijn over.

Na afloop wijst de bestandsrij naar de nieuwe plek, dus er is geen scan nodig om
de serie weer te kunnen lezen — en er ontstaat geen tweede exemplaar naast het
oude.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.models import Book, File, LibraryRoot, Series
from bookpal.sources.base import Source as SourceImpl
from bookpal.sources.base import SourceError
from bookpal.sources.service import download_book, safe_name

logger = logging.getLogger(__name__)


@dataclass
class ImportReport:
    moved: int = 0
    downloaded: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.moved + self.downloaded


def target_dir(root: LibraryRoot, series: Series) -> Path:
    """Eén map per serie, op naam. Zo is in de verkenner te zien wat er staat
    zonder de app erbij te halen."""
    return Path(root.path) / safe_name(series.title)


def target_name(series: Series, book: Book) -> str:
    """De bestandsnaam die de scanner het beste terugleest.

    Serie eerst, dan het nummer met nullen ervoor: zo staat een map in
    leesvolgorde in elke verkenner, ook zonder natuurlijk sorteren.
    """
    parts = [safe_name(series.title)]
    if book.volume:
        parts.append(f"v{book.volume}")
    if book.number:
        # Nullen ervoor, maar alleen als het echt een getal is; "12.5" en
        # "Extra" moeten onaangeroerd blijven.
        try:
            parts.append(f"{float(book.number):06.1f}".rstrip("0").rstrip("."))
        except ValueError:
            parts.append(safe_name(book.number, fallback="?"))
    if book.title and book.title != series.title:
        parts.append(safe_name(book.title, limit=60))
    return " - ".join(parts) + ".cbz"


def check_writable(root: LibraryRoot) -> None:
    """Vroeg en duidelijk falen als de map read-only is aangekoppeld.

    Anders zou het importeren pas bij het eerste hoofdstuk stuklopen, met een
    halve serie op schijf.
    """
    path = Path(root.path)
    if not path.is_dir():
        raise SourceError(f"de map {root.path} bestaat niet")
    probe = path / ".bookpal-schrijftest"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise SourceError(
            f"er kan niet geschreven worden in {root.path}: {exc}. "
            "Staat de map in compose.yml nog op ':ro'?"
        ) from exc


def import_series(
    session: Session,
    implementation: SourceImpl,
    series: Series,
    root: LibraryRoot,
    *,
    download_missing: bool = True,
) -> ImportReport:
    """Zet alle hoofdstukken van deze serie als bestanden in ``root``."""
    check_writable(root)
    folder = target_dir(root, series)
    folder.mkdir(parents=True, exist_ok=True)

    report = ImportReport()
    books = list(
        session.scalars(
            select(Book)
            .where(Book.series_id == series.id)
            .order_by(Book.sort_volume, Book.sort_number, Book.id)
        )
    )

    for book in books:
        destination = folder / target_name(series, book)
        try:
            if book.file_id is not None:
                if _move(session, book, destination, root):
                    report.moved += 1
                else:
                    report.skipped += 1
            elif download_missing and book.source_ref:
                download_book(session, implementation, book, temporary=False)
                if book.file_id is not None and _move(session, book, destination, root):
                    report.downloaded += 1
                else:
                    report.skipped += 1
            else:
                report.skipped += 1
            session.commit()
        except (SourceError, OSError) as exc:
            # Eén hoofdstuk dat hapert mag de rest van de serie niet stoppen.
            logger.warning("importeren %s: %s", book.title, exc)
            report.errors.append(f"{book.number or book.title}: {exc}")
            session.rollback()

    # De serie hoort nu bij deze map; de abonnementsgegevens blijven staan,
    # zodat nieuwe hoofdstukken gewoon binnen blijven komen.
    series.library_root_id = root.id
    series.folder_path = folder.name
    session.commit()
    return report


def _move(session: Session, book: Book, destination: Path, root: LibraryRoot) -> bool:
    """Verplaats het bestand en laat de bestandsrij meeverhuizen.

    Door de rij bij te werken in plaats van te vertrouwen op een scan blijft de
    koppeling boek-bestand intact en ontstaat er geen tweede exemplaar naast het
    oude.
    """
    file_row = session.get(File, book.file_id)
    if file_row is None:
        return False

    source = Path(file_row.path)
    if not source.is_file():
        return False
    if source.resolve() == destination.resolve():
        return False
    if destination.exists():
        # Nooit overschrijven: als er al iets staat is dat waarschijnlijk van
        # jou, en dan is dit hoofdstuk gewoon klaar.
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))

    stat = destination.stat()
    file_row.path = str(destination)
    file_row.library_root_id = root.id
    file_row.size = stat.st_size
    file_row.mtime = stat.st_mtime
    # Blijvend: de TTL van het vooruitlezen geldt hier niet meer voor.
    book.expires_at = None
    return True
