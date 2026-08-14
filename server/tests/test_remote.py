"""Een deellink ophalen (Dropbox, een losse download).

De nadruk ligt op waar de server heen mag: hij haalt de link op vanáf de NAS,
dus van binnen je eigen netwerk. Zonder controle is dit een manier om via
BookPal bij je router of je andere containers te komen.
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from bookpal.library import remote


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _cbz(pages: int = 1) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archief:
        for index in range(pages):
            archief.writestr(f"{index:03d}.jpg", b"nep")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _allow_hosts(monkeypatch: pytest.MonkeyPatch):
    """Doe alsof elke hostnaam naar een publiek adres wijst.

    De controle zelf wordt apart getest; hier gaat het om wat er daarna gebeurt.
    """
    monkeypatch.setattr(
        remote.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )


class TestWhereTheServerMayGo:
    def test_a_link_to_your_own_network_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr(
            remote.socket,
            "getaddrinfo",
            lambda *args, **kwargs: [(2, 1, 6, "", ("192.168.1.1", 443))],
        )
        with pytest.raises(remote.RemoteError, match="eigen netwerk"):
            remote.download("https://binnen.example/iets.cbz", tmp_path)

    def test_localhost_is_refused(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr(
            remote.socket,
            "getaddrinfo",
            lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
        )
        with pytest.raises(remote.RemoteError, match="eigen netwerk"):
            remote.download("https://localhost.example/iets.cbz", tmp_path)

    def test_plain_http_is_refused(self, tmp_path: Path):
        with pytest.raises(remote.RemoteError, match="https"):
            remote.download("http://example.com/iets.cbz", tmp_path)

    def test_a_redirect_into_your_network_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """Eén controle vooraf is niet genoeg; de laatste hop telt."""
        adressen = iter(
            [
                [(2, 1, 6, "", ("93.184.216.34", 443))],
                [(2, 1, 6, "", ("10.0.0.5", 443))],
            ]
        )
        monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: next(adressen))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://intern.example/geheim"})

        with pytest.raises(remote.RemoteError, match="eigen netwerk"):
            remote.download("https://buiten.example/iets.cbz", tmp_path, client=_client(handler))


class TestDropboxLinks:
    def test_a_preview_link_becomes_a_download_link(self):
        omgezet = remote.normalise_url("https://www.dropbox.com/scl/fo/abc/map?rlkey=x&dl=0")
        assert "dl=1" in omgezet
        assert "dl=0" not in omgezet
        assert "rlkey=x" in omgezet

    def test_a_link_without_dl_gets_one(self):
        assert "dl=1" in remote.normalise_url("https://www.dropbox.com/s/abc/Storm.cbz")

    def test_other_hosts_are_left_alone(self):
        url = "https://example.com/iets.cbz?a=1"
        assert remote.normalise_url(url) == url


class TestWhatComesIn:
    def test_a_single_file_is_saved_under_its_own_name(self, tmp_path: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_cbz())

        report = remote.download(
            "https://example.com/Storm 03.cbz", tmp_path, client=_client(handler)
        )
        assert (tmp_path / "Storm 03.cbz").is_file()
        assert len(report.saved) == 1

    def test_a_shared_folder_arrives_as_a_zip_and_is_unpacked(self, tmp_path: Path):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archief:
            archief.writestr("map/Storm 01.cbz", _cbz())
            archief.writestr("map/Storm 02.cbz", _cbz())
            archief.writestr("map/leesmij.txt", b"niets voor ons")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=buffer.getvalue())

        report = remote.download(
            "https://www.dropbox.com/scl/fo/abc/Strips.zip", tmp_path, client=_client(handler)
        )
        assert sorted(Path(item).name for item in report.saved) == ["Storm 01.cbz", "Storm 02.cbz"]
        assert not (tmp_path / "leesmij.txt").exists()

    def test_a_zip_of_loose_images_is_treated_as_one_chapter(self, tmp_path: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_cbz(pages=3))

        remote.download("https://example.com/Hoofdstuk 5.zip", tmp_path, client=_client(handler))
        assert (tmp_path / "Hoofdstuk 5.cbz").is_file()

    def test_a_path_inside_the_zip_cannot_escape(self, tmp_path: Path):
        """Een zip mag paden bevatten als ../../ergens/anders."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archief:
            archief.writestr("../../ontsnapt.cbz", _cbz())
            archief.writestr("normaal.cbz", _cbz())

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=buffer.getvalue())

        doel = tmp_path / "in"
        remote.download("https://example.com/map.zip", doel, client=_client(handler))
        assert not (tmp_path.parent / "ontsnapt.cbz").exists()
        assert all(bestand.parent == doel for bestand in doel.rglob("*.cbz"))

    def test_an_existing_file_is_never_overwritten(self, tmp_path: Path):
        (tmp_path / "Storm 03.cbz").write_bytes(b"van jou")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_cbz())

        report = remote.download(
            "https://example.com/Storm 03.cbz", tmp_path, client=_client(handler)
        )
        assert report.skipped == 1
        assert (tmp_path / "Storm 03.cbz").read_bytes() == b"van jou"

    def test_an_html_page_is_not_a_comic(self, tmp_path: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>inloggen</html>")

        with pytest.raises(remote.RemoteError):
            remote.download("https://example.com/pagina.html", tmp_path, client=_client(handler))

    def test_too_big_leaves_nothing_behind(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(remote, "MAX_BYTES", 100)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 5000)

        with pytest.raises(remote.RemoteError, match="groter"):
            remote.download("https://example.com/groot.cbz", tmp_path, client=_client(handler))
        assert list(tmp_path.iterdir()) == []

    def test_a_server_error_is_reported_as_such(self, tmp_path: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        with pytest.raises(remote.RemoteError, match="404"):
            remote.download("https://example.com/weg.cbz", tmp_path, client=_client(handler))

    def test_an_epub_is_left_whole(self, tmp_path: Path):
        """Een epub is ook een zip; uitpakken zou het boek slopen."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archief:
            archief.writestr("mimetype", b"application/epub+zip")
            archief.writestr("OEBPS/content.opf", b"<package/>")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=buffer.getvalue())

        remote.download("https://example.com/Down to Earth.epub", tmp_path, client=_client(handler))
        with zipfile.ZipFile(tmp_path / "Down to Earth.epub") as opnieuw:
            assert "mimetype" in opnieuw.namelist()

    def test_a_cbz_is_left_whole(self, tmp_path: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_cbz(pages=4))

        remote.download("https://example.com/H5.cbz", tmp_path, client=_client(handler))
        with zipfile.ZipFile(tmp_path / "H5.cbz") as opnieuw:
            assert len(opnieuw.namelist()) == 4


class TestFetchingInTheBackground:
    """Een gedeelde map is zomaar een gigabyte.

    Daar in het verzoek zelf op wachten is minutenlang een browser die niets
    zegt, en dat is niet te onderscheiden van "er gebeurt niets".
    """

    def _wacht(self, timeout: float = 5.0):
        from bookpal.library import fetchjob

        eind = time.monotonic() + timeout
        while time.monotonic() < eind:
            job = fetchjob.status()
            if job is not None and not job.running:
                return job
            time.sleep(0.02)
        raise AssertionError("de klus liep niet af")

    def test_it_answers_before_the_download_is_done(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from bookpal.config import settings
        from bookpal.library import fetchjob

        fetchjob.reset()
        folder = tmp_path / "intake"
        folder.mkdir()
        monkeypatch.setattr(settings, "intake_dirs", [str(folder)])
        monkeypatch.setattr(fetchjob.remote, "download", lambda *a, **k: _traag(*a, **k))

        body = client.post("/api/intake/fetch", json={"url": "https://x.test/map.zip"}).json()
        assert body["state"] == "bezig", "meteen antwoord, niet pas als alles binnen is"
        self._wacht()

    def test_the_status_says_how_far_it_is(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from bookpal.config import settings
        from bookpal.library import fetchjob, remote

        fetchjob.reset()
        folder = tmp_path / "intake"
        folder.mkdir()
        monkeypatch.setattr(settings, "intake_dirs", [str(folder)])

        def nep(url, doel, *, client=None, on_progress=None):
            if on_progress:
                on_progress(500, 1000)
            return remote.FetchReport(saved=["a.cbz"])

        monkeypatch.setattr(fetchjob.remote, "download", nep)

        client.post("/api/intake/fetch", json={"url": "https://x.test/map.zip"})
        self._wacht()

        stand = client.get("/api/intake/fetch").json()
        assert stand["state"] == "klaar"
        assert stand["bytes_done"] == 500
        assert stand["bytes_total"] == 1000
        assert stand["saved"] == ["a.cbz"]

    def test_a_failure_is_reported_and_not_swallowed(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from bookpal.config import settings
        from bookpal.library import fetchjob, remote

        fetchjob.reset()
        folder = tmp_path / "intake"
        folder.mkdir()
        monkeypatch.setattr(settings, "intake_dirs", [str(folder)])

        def stuk(*args, **kwargs):
            raise remote.RemoteError("de server gaf 404")

        monkeypatch.setattr(fetchjob.remote, "download", stuk)

        client.post("/api/intake/fetch", json={"url": "https://x.test/weg.zip"})
        self._wacht()

        stand = client.get("/api/intake/fetch").json()
        assert stand["state"] == "mislukt"
        assert "404" in stand["errors"][0]

    def test_a_second_one_is_refused_while_the_first_runs(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Twee downloads tegelijk maken het alleen trager en de melding vager."""
        from bookpal.config import settings
        from bookpal.library import fetchjob

        fetchjob.reset()
        folder = tmp_path / "intake"
        folder.mkdir()
        monkeypatch.setattr(settings, "intake_dirs", [str(folder)])
        monkeypatch.setattr(fetchjob.remote, "download", lambda *a, **k: _traag(*a, **k))

        client.post("/api/intake/fetch", json={"url": "https://x.test/een.zip"})
        tweede = client.post("/api/intake/fetch", json={"url": "https://x.test/twee.zip"})
        assert tweede.status_code == 409
        self._wacht()

    def test_a_subfolder_is_used(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from bookpal.config import settings
        from bookpal.library import fetchjob, remote

        fetchjob.reset()
        folder = tmp_path / "intake"
        folder.mkdir()
        monkeypatch.setattr(settings, "intake_dirs", [str(folder)])

        gezien: list[Path] = []

        def nep(url, doel, *, client=None, on_progress=None):
            gezien.append(doel)
            return remote.FetchReport()

        monkeypatch.setattr(fetchjob.remote, "download", nep)

        client.post(
            "/api/intake/fetch", json={"url": "https://x.test/map.zip", "folder": "Dirk Jan"}
        )
        self._wacht()
        assert gezien and gezien[0].name == "Dirk Jan"


def _traag(url, doel, *, client=None, on_progress=None):
    from bookpal.library import remote

    time.sleep(0.1)
    return remote.FetchReport()
