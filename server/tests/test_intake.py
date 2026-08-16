"""Losse bestanden importeren (downloads, Dropbox).

Twee dingen staan hier centraal: er mag niets overschreven worden, en het
endpoint mag geen willekeurig bestand op de NAS kunnen verplaatsen.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.library import intake
from bookpal.library.intake import import_files, scan
from bookpal.sources.base import SourceError
from tests.conftest import make_root


def _bestand(folder: Path, naam: str, inhoud: bytes = b"cbz") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / naam
    path.write_bytes(inhoud)
    return path


class TestScan:
    def test_it_finds_readable_files(self, tmp_path: Path):
        _bestand(tmp_path / "in", "Storm 01.cbz")
        _bestand(tmp_path / "in", "Een boek.epub")
        gevonden = scan([str(tmp_path / "in")])
        assert {c.name for c in gevonden} == {"Storm 01.cbz", "Een boek.epub"}

    def test_it_looks_in_subfolders(self, tmp_path: Path):
        """Een download is vaak een map met hoofdstukken erin."""
        _bestand(tmp_path / "in" / "Storm", "01.cbz")
        assert len(scan([str(tmp_path / "in")])) == 1

    def test_it_skips_files_it_cannot_read(self, tmp_path: Path):
        _bestand(tmp_path / "in", "notities.txt")
        _bestand(tmp_path / "in", "thumbs.db")
        _bestand(tmp_path / "in", ".verborgen.cbz")
        assert scan([str(tmp_path / "in")]) == []

    def test_a_missing_folder_is_not_an_error(self, tmp_path: Path):
        assert scan([str(tmp_path / "bestaat-niet")]) == []

    def test_the_filename_is_parsed_as_a_suggestion(self, tmp_path: Path):
        _bestand(tmp_path / "in", "Storm 12.cbz")
        kandidaat = scan([str(tmp_path / "in")])[0]
        assert kandidaat.series == "Storm"
        assert kandidaat.number == "12"


class TestImport:
    def test_files_move_into_the_library(self, session: Session, tmp_path: Path):
        bron = _bestand(tmp_path / "in", "Storm 01.cbz")
        root = make_root(session, tmp_path / "strips", name="Strips")
        Path(root.path).mkdir(parents=True, exist_ok=True)

        report = import_files(session, [str(bron)], root, allowed=[str(tmp_path / "in")])

        assert report.moved == 1
        assert (Path(root.path) / "Storm 01.cbz").is_file()
        assert not bron.exists()

    def test_it_can_put_them_in_a_subfolder(self, session: Session, tmp_path: Path):
        bron = _bestand(tmp_path / "in", "Storm 01.cbz")
        root = make_root(session, tmp_path / "strips", name="Strips")
        Path(root.path).mkdir(parents=True, exist_ok=True)

        import_files(session, [str(bron)], root, folder="Storm", allowed=[str(tmp_path / "in")])
        assert (Path(root.path) / "Storm" / "Storm 01.cbz").is_file()

    def test_an_existing_file_is_never_overwritten(self, session: Session, tmp_path: Path):
        bron = _bestand(tmp_path / "in", "Storm 01.cbz", b"nieuw")
        root = make_root(session, tmp_path / "strips", name="Strips")
        Path(root.path).mkdir(parents=True, exist_ok=True)
        bestaand = Path(root.path) / "Storm 01.cbz"
        bestaand.write_bytes(b"van mij")

        report = import_files(session, [str(bron)], root, allowed=[str(tmp_path / "in")])

        assert report.moved == 0
        assert report.skipped == 1
        assert bestaand.read_bytes() == b"van mij"
        assert bron.exists()  # en het origineel staat er nog

    def test_a_file_outside_the_allowed_folders_is_refused(self, session: Session, tmp_path: Path):
        """Zonder die grens is dit een endpoint waarmee elk bestand op de NAS
        te verplaatsen is."""
        elders = _bestand(tmp_path / "ergens-anders", "geheim.cbz")
        root = make_root(session, tmp_path / "strips", name="Strips")
        Path(root.path).mkdir(parents=True, exist_ok=True)

        report = import_files(session, [str(elders)], root, allowed=[str(tmp_path / "in")])

        assert report.moved == 0
        assert "niet in een toegestane map" in report.errors[0]
        assert elders.exists()

    def test_a_path_traversal_attempt_is_refused(self, session: Session, tmp_path: Path):
        """../ mag niet buiten de toegestane map wijzen."""
        elders = _bestand(tmp_path / "ergens-anders", "geheim.cbz")
        (tmp_path / "in").mkdir(parents=True, exist_ok=True)
        root = make_root(session, tmp_path / "strips", name="Strips")
        Path(root.path).mkdir(parents=True, exist_ok=True)

        sluipweg = str(tmp_path / "in" / ".." / "ergens-anders" / "geheim.cbz")
        report = import_files(session, [sluipweg], root, allowed=[str(tmp_path / "in")])

        assert report.moved == 0
        assert elders.exists()

    def test_a_read_only_target_fails_before_moving_anything(
        self, session: Session, tmp_path: Path
    ):
        bron = _bestand(tmp_path / "in", "Storm 01.cbz")
        folder = tmp_path / "alleenlezen"
        folder.mkdir()
        folder.chmod(0o500)
        root = make_root(session, folder, name="RO")

        try:
            with pytest.raises(SourceError):
                import_files(session, [str(bron)], root, allowed=[str(tmp_path / "in")])
            assert bron.exists()
        finally:
            folder.chmod(0o700)

    def test_a_vanished_file_is_reported_not_fatal(self, session: Session, tmp_path: Path):
        (tmp_path / "in").mkdir(parents=True, exist_ok=True)
        root = make_root(session, tmp_path / "strips", name="Strips")
        Path(root.path).mkdir(parents=True, exist_ok=True)

        report = import_files(
            session,
            [str(tmp_path / "in" / "weg.cbz")],
            root,
            allowed=[str(tmp_path / "in")],
        )
        assert report.moved == 0
        assert "bestaat niet meer" in report.errors[0]


class TestApi:
    def test_the_scan_reports_which_folders_exist(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _bestand(tmp_path / "in", "Storm 01.cbz")
        monkeypatch.setattr(settings, "intake_dirs", [str(tmp_path / "in"), str(tmp_path / "weg")])

        body = client.get("/api/intake").json()
        assert body["folders"] == [str(tmp_path / "in")]
        assert [f["name"] for f in body["files"]] == ["Storm 01.cbz"]

    def test_importing_to_an_unknown_root_is_a_404(self, client: TestClient):
        response = client.post("/api/intake/import", json={"paths": [], "root_id": 9999})
        assert response.status_code == 404


class TestUpload:
    """Een bestand van je telefoon naar de NAS."""

    def _intake(self, tmp_path: Path, monkeypatch) -> Path:
        folder = tmp_path / "intake"
        folder.mkdir()
        monkeypatch.setattr(settings, "intake_dirs", [str(folder)])
        return folder

    def test_a_cbz_lands_in_the_intake_folder(
        self, client: TestClient, tmp_path: Path, monkeypatch
    ):
        folder = self._intake(tmp_path, monkeypatch)
        response = client.post(
            "/api/intake/upload",
            files={"file": ("Storm 03.cbz", b"PK\x03\x04nep", "application/octet-stream")},
        )
        assert response.status_code == 200
        assert (folder / "Storm 03.cbz").is_file()

    def test_a_path_in_the_name_cannot_escape(
        self, client: TestClient, tmp_path: Path, monkeypatch
    ):
        """De naam komt van de client en is dus niet te vertrouwen."""
        folder = self._intake(tmp_path, monkeypatch)
        response = client.post(
            "/api/intake/upload",
            files={"file": ("../../ontsnapt.cbz", b"data", "application/octet-stream")},
        )
        assert response.status_code == 200
        assert not (tmp_path.parent / "ontsnapt.cbz").exists()
        assert list(folder.glob("*.cbz")) != []
        assert all(bestand.parent == folder for bestand in folder.glob("*.cbz"))

    def test_something_unreadable_is_refused(self, client: TestClient, tmp_path: Path, monkeypatch):
        self._intake(tmp_path, monkeypatch)
        response = client.post(
            "/api/intake/upload",
            files={"file": ("script.sh", b"#!/bin/sh", "application/octet-stream")},
        )
        assert response.status_code == 409

    def test_an_existing_file_is_not_overwritten(
        self, client: TestClient, tmp_path: Path, monkeypatch
    ):
        folder = self._intake(tmp_path, monkeypatch)
        (folder / "Storm 03.cbz").write_bytes(b"van jou")

        response = client.post(
            "/api/intake/upload",
            files={"file": ("Storm 03.cbz", b"nieuw", "application/octet-stream")},
        )
        assert response.status_code == 409
        assert (folder / "Storm 03.cbz").read_bytes() == b"van jou"

    def test_too_big_is_refused_and_leaves_nothing_behind(self, tmp_path: Path):
        import io

        folder = tmp_path / "intake"
        with pytest.raises(SourceError):
            intake.receive_upload(io.BytesIO(b"x" * 5000), "groot.cbz", folder, max_bytes=1000)
        assert list(folder.iterdir()) == []


class TestPaginamappen:
    """Een hoofdstuk dat je zelf pagina voor pagina hebt opgeslagen.

    Een browser levert losse jpg's; die horen er na het importeren hetzelfde
    uit te zien als een gedownloade cbz, anders herkent de scanner ze niet als
    hoofdstuk.
    """

    def _map_met(self, basis: Path, naam: str, namen: list[str]) -> Path:
        map_ = basis / naam
        map_.mkdir(parents=True, exist_ok=True)
        for bestand in namen:
            (map_ / bestand).write_bytes(b"x" * 32)
        return map_

    def test_a_folder_of_pages_is_offered_as_one_chapter(self, tmp_path: Path):
        self._map_met(tmp_path, "Hirayasumi c012", ["1.jpg", "2.jpg", "3.jpg"])
        kandidaten = intake.scan([str(tmp_path)])
        assert len(kandidaten) == 1
        assert kandidaten[0].is_folder
        assert kandidaten[0].pages == 3
        assert kandidaten[0].name == "Hirayasumi c012.cbz"

    def test_a_couple_of_stray_images_is_not_a_chapter(self, tmp_path: Path):
        """Een omslag of twee knopjes naast een download horen er niet in."""
        self._map_met(tmp_path, "rommel", ["logo.png", "banner.jpg"])
        assert intake.scan([str(tmp_path)]) == []

    def test_pages_are_ordered_by_number_and_not_alphabetically(self, tmp_path: Path):
        """Een browser slaat op als 1.jpg … 10.jpg, en alfabetisch komt de
        tien dan vóór de twee."""
        map_ = self._map_met(tmp_path, "hoofdstuk", ["1.jpg", "2.jpg", "9.jpg", "10.jpg", "11.jpg"])
        volgorde = [pad.name for pad in intake._page_files(map_)]
        assert volgorde == ["1.jpg", "2.jpg", "9.jpg", "10.jpg", "11.jpg"]

    def test_importing_makes_a_real_cbz(self, session: Session, tmp_path: Path):
        bron = tmp_path / "intake"
        self._map_met(bron, "Hirayasumi c012", ["1.jpg", "2.jpg", "3.jpg"])
        doel = tmp_path / "bibliotheek"
        doel.mkdir()
        root = make_root(session, doel, name="Strips")

        verslag = intake.import_files(
            session, [str(bron / "Hirayasumi c012")], root, allowed=[str(bron)]
        )
        assert verslag.moved == 1
        gemaakt = doel / "Hirayasumi c012.cbz"
        assert gemaakt.is_file()
        with zipfile.ZipFile(gemaakt) as archief:
            assert archief.namelist() == ["0001.jpg", "0002.jpg", "0003.jpg"]

    def test_the_pages_are_only_removed_after_the_archive_exists(
        self, session: Session, tmp_path: Path
    ):
        """Gaat het schrijven mis, dan heb je je opgeslagen pagina's nog."""
        bron = tmp_path / "intake"
        map_ = self._map_met(bron, "Hirayasumi c013", ["1.jpg", "2.jpg", "3.jpg"])
        doel = tmp_path / "bibliotheek"
        doel.mkdir()
        root = make_root(session, doel, name="Strips")

        intake.import_files(session, [str(map_)], root, allowed=[str(bron)])
        assert not map_.exists()  # gelukt, dus opgeruimd
        assert (doel / "Hirayasumi c013.cbz").is_file()

    def test_an_existing_chapter_is_never_overwritten(self, session: Session, tmp_path: Path):
        bron = tmp_path / "intake"
        map_ = self._map_met(bron, "Hirayasumi c014", ["1.jpg", "2.jpg", "3.jpg"])
        doel = tmp_path / "bibliotheek"
        doel.mkdir()
        (doel / "Hirayasumi c014.cbz").write_bytes(b"van mij")
        root = make_root(session, doel, name="Strips")

        verslag = intake.import_files(session, [str(map_)], root, allowed=[str(bron)])
        assert verslag.skipped == 1
        assert (doel / "Hirayasumi c014.cbz").read_bytes() == b"van mij"
        assert map_.exists()  # en je pagina's staan er nog

    def test_a_folder_outside_the_allowed_area_is_refused(self, session: Session, tmp_path: Path):
        elders = tmp_path / "elders"
        self._map_met(elders, "geheim", ["1.jpg", "2.jpg", "3.jpg"])
        doel = tmp_path / "bibliotheek"
        doel.mkdir()
        root = make_root(session, doel, name="Strips")

        verslag = intake.import_files(
            session, [str(elders / "geheim")], root, allowed=[str(tmp_path / "intake")]
        )
        assert verslag.moved == 0
        assert verslag.errors
