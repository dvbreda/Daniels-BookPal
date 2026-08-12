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
import shutil
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass(frozen=True, slots=True)
class Candidate:
    """Een bestand dat geïmporteerd kan worden."""

    path: str
    name: str
    size: int
    # Wat de bestandsnaam prijsgeeft; puur als voorstel voor de doelmap.
    series: str | None = None
    number: str | None = None


@dataclass
class IntakeReport:
    moved: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def scan(folders: list[str]) -> list[Candidate]:
    """Wat er in deze mappen staat dat BookPal zou kunnen lezen.

    Recursief, want een download is vaak een map met hoofdstukken erin.
    """
    found: list[Candidate] = []
    for folder in folders:
        base = Path(folder)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.name.lower() in _SKIP_NAMES or path.name.startswith("."):
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
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
    "Candidate",
    "IntakeReport",
    "SourceError",
    "check_sources",
    "import_files",
    "scan",
    "unwritable",
]
