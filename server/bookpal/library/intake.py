"""Losse bestanden je bibliotheek in halen.

Voor wat er buiten je mappen belandt: een download in je browsermap, iets uit
Dropbox, een cbz die je van iemand kreeg. In plaats van zelf slepen en hernoemen
kijk je hier wat er staat en zet je het in één keer op de goede plek.

Het uitgangspunt is hetzelfde als bij het importeren van een gevolgde serie:
niets overschrijven, niets weggooien. Een bestand dat er al staat wordt
overgeslagen, en verplaatsen gebeurt pas nadat de doelmap schrijfbaar is
gebleken.
"""

from __future__ import annotations

import logging
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from bookpal.formats import SUPPORTED_EXTENSIONS
from bookpal.metadata.filename import parse_filename
from bookpal.models import LibraryRoot
from bookpal.sources.base import SourceError
from bookpal.sources.importer import check_writable
from bookpal.sources.service import safe_name

logger = logging.getLogger(__name__)

# Mappen waar losse bestanden vandaan kunnen komen. Instelbaar, want waar je
# downloads belanden verschilt per NAS en per persoon.
DEFAULT_SOURCES = ("/intake",)

# Rommel die naast een download staat en niet meegenomen hoeft te worden.
_SKIP_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}

# Ruim voor een dik album, krap genoeg dat een misklik niet je schijf vult.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

# Wat er in een bestandsnaam mag blijven staan. De naam komt van een client en
# mag dus geen pad zijn en geen shell-tekens bevatten.
_UNSAFE_IN_NAME = re.compile(r"[^A-Za-z0-9 ._()\[\]-]+")


#: Losse pagina's, zoals ze uit een browser komen. Geen `.gif`: dat is bij een
#: opgeslagen webpagina vrijwel altijd een knopje of een scheidingslijn.
PAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".avif"})

#: Minder plaatjes dan dit is geen hoofdstuk maar een omslag, een banner of
#: een setje pictogrammen dat naast een download belandde.
MIN_PAGES_IN_FOLDER = 3


@dataclass(frozen=True, slots=True)
class Candidate:
    """Iets dat geïmporteerd kan worden: een bestand, of een map met pagina's."""

    path: str
    name: str
    size: int
    # Wat de bestandsnaam prijsgeeft; puur als voorstel voor de doelmap.
    series: str | None = None
    number: str | None = None
    # Een map met losse plaatjes erin, die bij het importeren tot één cbz
    # wordt samengevoegd. Zo hoort een hoofdstuk dat je pagina voor pagina
    # hebt opgeslagen er hetzelfde uit te zien als een gedownloade cbz.
    pages: int = 0

    @property
    def is_folder(self) -> bool:
        return self.pages > 0


@dataclass
class IntakeReport:
    moved: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _page_files(folder: Path) -> list[Path]:
    """De losse pagina's in deze map, in leesvolgorde.

    Niet recursief: een map mét een submap is een verzameling hoofdstukken en
    geen hoofdstuk. Sorteren gebeurt op nummer waar dat kan, want een browser
    slaat op als `1.jpg … 10.jpg` en dan zet alfabetisch de tien vóór de twee.
    """
    pagina_s = [
        pad
        for pad in folder.iterdir()
        if pad.is_file()
        and pad.suffix.lower() in PAGE_EXTENSIONS
        and pad.name.lower() not in _SKIP_NAMES
        and not pad.name.startswith(".")
    ]

    def sleutel(pad: Path) -> tuple[int, float, str]:
        cijfers = re.findall(r"\d+", pad.stem)
        if cijfers:
            return (0, float(cijfers[-1]), pad.name.lower())
        return (1, 0.0, pad.name.lower())

    return sorted(pagina_s, key=sleutel)


def scan(folders: list[str]) -> list[Candidate]:
    """Wat er in deze mappen staat dat BookPal zou kunnen lezen.

    Recursief, want een download is vaak een map met hoofdstukken erin.

    Naast losse bestanden telt een map met genoeg plaatjes erin ook mee: dat
    is een hoofdstuk dat je zelf pagina voor pagina hebt opgeslagen, en dat
    hoort er na het importeren hetzelfde uit te zien als een gedownloade cbz.
    """
    found: list[Candidate] = []
    for folder in folders:
        base = Path(folder)
        if not base.is_dir():
            continue

        for map_ in sorted(base.rglob("*")):
            if not map_.is_dir() or map_.name.startswith("."):
                continue
            pagina_s = _page_files(map_)
            if len(pagina_s) < MIN_PAGES_IN_FOLDER:
                continue
            parsed = parse_filename(map_.name)
            found.append(
                Candidate(
                    path=str(map_),
                    name=f"{map_.name}.cbz",
                    size=sum(pad.stat().st_size for pad in pagina_s),
                    series=parsed.series or None,
                    number=parsed.number,
                    pages=len(pagina_s),
                )
            )

        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.name.lower() in _SKIP_NAMES or path.name.startswith("."):
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            # Niet nog eens los aanbieden wat al als hoofdstukmap meetelt.
            in_map = any(
                kandidaat.is_folder and _within(path, Path(kandidaat.path)) for kandidaat in found
            )
            if in_map:
                continue
            parsed = parse_filename(path.stem)
            found.append(
                Candidate(
                    path=str(path),
                    name=path.name,
                    size=path.stat().st_size,
                    series=parsed.series or None,
                    number=parsed.number,
                )
            )
    return found


def import_files(
    session: Session,
    paths: list[str],
    root: LibraryRoot,
    *,
    folder: str | None = None,
    allowed: list[str] | None = None,
) -> IntakeReport:
    """Verplaats deze bestanden naar ``root``, eventueel in een submap.

    ``allowed`` begrenst waar bestanden vandaan mogen komen: zonder die grens
    zou een pad uit een verzoek elk bestand op de NAS kunnen verplaatsen.
    """
    check_writable(root)
    doel = Path(root.path)
    if folder:
        doel = doel / safe_name(folder)
    doel.mkdir(parents=True, exist_ok=True)

    toegestaan = [Path(item).resolve() for item in (allowed or DEFAULT_SOURCES)]
    report = IntakeReport()

    for raw in paths:
        source = Path(raw)
        try:
            resolved = source.resolve()
            # Alleen uit de aangewezen mappen. Anders is dit een endpoint
            # waarmee elk bestand op de NAS te verplaatsen is.
            if not any(_within(resolved, base) for base in toegestaan):
                report.errors.append(f"{source.name}: staat niet in een toegestane map")
                continue
            if resolved.is_dir():
                if _bundel_map(resolved, doel, report):
                    report.moved += 1
                continue

            if not resolved.is_file():
                report.errors.append(f"{source.name}: bestaat niet meer")
                continue

            destination = doel / source.name
            if destination.exists():
                # Nooit overschrijven: wat er staat is waarschijnlijk van jou.
                report.skipped += 1
                continue

            shutil.move(str(resolved), str(destination))
            report.moved += 1
        except OSError as exc:
            logger.warning("importeren %s: %s", source, exc)
            report.errors.append(f"{source.name}: {exc}")

    return report


def _bundel_map(bron: Path, doel: Path, report: IntakeReport) -> bool:
    """Een map met losse pagina's als één cbz wegschrijven.

    De pagina's krijgen een nieuw nummer met nullen ervoor. De naam waaronder
    ze binnenkwamen doet er niet toe — een browser slaat op als `3.jpg` of als
    een lange hash — maar de vólgorde wel, en die is hier al bepaald door
    `_page_files`.

    Via een tijdelijk bestand, net als bij een download: een half geschreven
    archief mag de scanner nooit als geldig hoofdstuk tegenkomen.
    """
    pagina_s = _page_files(bron)
    if len(pagina_s) < MIN_PAGES_IN_FOLDER:
        report.errors.append(f"{bron.name}: te weinig pagina's om een hoofdstuk te zijn")
        return False

    bestemming = doel / f"{safe_name(bron.name)}.cbz"
    if bestemming.exists():
        report.skipped += 1
        return False

    tijdelijk = bestemming.with_suffix(".cbz.partial")
    try:
        with zipfile.ZipFile(tijdelijk, "w", zipfile.ZIP_STORED) as archief:
            for nummer, pagina in enumerate(pagina_s, start=1):
                archief.write(pagina, f"{nummer:04d}{pagina.suffix.lower()}")
        tijdelijk.replace(bestemming)
    except OSError as exc:
        tijdelijk.unlink(missing_ok=True)
        report.errors.append(f"{bron.name}: {exc}")
        return False

    # Pas opruimen als het archief er staat: gaat er iets mis, dan heb je je
    # opgeslagen pagina's nog.
    shutil.rmtree(bron, ignore_errors=True)
    return True


def _within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def check_sources(folders: list[str]) -> list[str]:
    """Welke van deze mappen bestaan er daadwerkelijk?"""
    return [folder for folder in folders if Path(folder).is_dir()]


def unwritable(folders: list[str]) -> list[str]:
    """Mappen die bestaan maar waaruit niets verplaatst kan worden.

    Het gangbare geval: Docker maakt een ontbrekende bind-map aan als root,
    terwijl de server als gewone gebruiker draait. Verplaatsen vereist
    schrijfrecht op de map, niet op het bestand — dat merk je anders pas bij
    het eerste bestand, en dan als een kale permission denied.
    """
    slecht: list[str] = []
    for folder in folders:
        path = Path(folder)
        if not path.is_dir():
            continue
        probe = path / ".bookpal-schrijftest"
        try:
            probe.write_bytes(b"")
            probe.unlink()
        except OSError:
            slecht.append(folder)
    return slecht


__all__ = [
    "MAX_UPLOAD_BYTES",
    "Candidate",
    "IntakeReport",
    "SourceError",
    "check_sources",
    "import_files",
    "receive_upload",
    "scan",
    "unwritable",
]


def receive_upload(
    stream: BinaryIO, filename: str, folder: Path, *, max_bytes: int = MAX_UPLOAD_BYTES
) -> Path:
    """Neem een geüpload bestand aan en zet het in ``folder``.

    Voor het geval dat je iets op je telefoon hebt staan en het op de NAS wilt
    hebben. De naam komt van de client en is dus niet te vertrouwen: alleen het
    laatste stuk telt, en paden erin worden onschadelijk gemaakt. Er wordt
    geschreven naar een tijdelijke naam, zodat een afgebroken upload nooit als
    geldig bestand blijft liggen.
    """
    veilig = _UNSAFE_IN_NAME.sub("_", Path(filename).name).strip(" .")
    if not veilig:
        raise SourceError("dit bestand heeft geen bruikbare naam")
    if Path(veilig).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise SourceError(f"{veilig} is geen formaat dat BookPal kan lezen")

    folder.mkdir(parents=True, exist_ok=True)
    doel = folder / veilig
    if doel.exists():
        raise SourceError(f"{veilig} staat er al")

    tijdelijk = folder / f".{veilig}.binnenkomend"
    geschreven = 0
    try:
        with tijdelijk.open("wb") as uit:
            while blok := stream.read(1024 * 1024):
                geschreven += len(blok)
                if geschreven > max_bytes:
                    raise SourceError("dit bestand is groter dan BookPal aanneemt")
                uit.write(blok)
        if geschreven == 0:
            raise SourceError("er kwam niets binnen")
        tijdelijk.replace(doel)
    finally:
        tijdelijk.unlink(missing_ok=True)
    return doel
