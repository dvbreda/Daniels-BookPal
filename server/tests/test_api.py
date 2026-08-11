from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from bookpal.models import Series
from tests.fixtures import make_cbz


class TestHealth:
    def test_health(self, client: TestClient):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["books"] == 0

    def test_profiles_include_kobo(self, client: TestClient):
        names = {item["name"] for item in client.get("/api/profiles").json()}
        assert "web" in names
        assert "kobo-clara" in names
        kobo = next(p for p in client.get("/api/profiles").json() if p["name"] == "kobo-clara")
        assert kobo["grayscale"] is True
        assert kobo["max_width"] == 1072


class TestLibraries:
    def test_create_and_list(self, client: TestClient, library: Path):
        created = client.post("/api/libraries", json={"name": "Collectie", "path": str(library)})
        assert created.status_code == 201
        assert created.json()["name"] == "Collectie"
        assert len(client.get("/api/libraries").json()) == 1

    def test_rejects_missing_directory(self, client: TestClient, tmp_path: Path):
        response = client.post(
            "/api/libraries", json={"name": "Weg", "path": str(tmp_path / "nergens")}
        )
        assert response.status_code == 400

    def test_rejects_duplicate(self, client: TestClient, library: Path):
        payload = {"name": "Collectie", "path": str(library)}
        client.post("/api/libraries", json=payload)
        assert client.post("/api/libraries", json=payload).status_code == 409

    def test_scan_counts_and_is_idempotent(self, client: TestClient, library: Path):
        root_id = client.post("/api/libraries", json={"name": "C", "path": str(library)}).json()[
            "id"
        ]

        first = client.post(f"/api/libraries/{root_id}/scan").json()
        second = client.post(f"/api/libraries/{root_id}/scan").json()

        assert first["added"] == 5
        assert second["added"] == 0
        assert second["unchanged"] == 5

    def test_scan_of_unmounted_root_returns_409(self, client: TestClient, tmp_path: Path):
        root = tmp_path / "share"
        root.mkdir()
        for index in range(6):
            make_cbz(root / f"Reeks {index:02d}.cbz", pages=1)
        root_id = client.post("/api/libraries", json={"name": "S", "path": str(root)}).json()["id"]
        client.post(f"/api/libraries/{root_id}/scan")

        for path in root.glob("*.cbz"):
            path.unlink()

        response = client.post(f"/api/libraries/{root_id}/scan")
        assert response.status_code == 409
        assert "mount" in response.json()["detail"]
        # En de bibliotheek staat er nog.
        assert client.get("/api/health").json()["books"] == 6

    def test_delete_root_removes_its_content(self, scanned: TestClient):
        root_id = scanned.get("/api/libraries").json()[0]["id"]
        assert scanned.delete(f"/api/libraries/{root_id}").status_code == 204
        assert scanned.get("/api/health").json()["series"] == 0


class TestSeries:
    def test_list_with_counts(self, scanned: TestClient):
        body = scanned.get("/api/series").json()
        assert body["total"] == 4  # Storm, Tesuto, Een Testboek, Een Testdocument
        storm = next(item for item in body["items"] if item["title"] == "Storm")
        assert storm["book_count"] == 2
        assert storm["publisher"] == "Dupuis"

    def test_origin_is_derived(self, scanned: TestClient):
        items = {item["title"]: item for item in scanned.get("/api/series").json()["items"]}
        assert items["Storm"]["origin_region"] == "europe"
        assert items["Tesuto"]["origin_region"] == "japan"
        # Een Nederlandstalige epub is géén bewijs van Europese herkomst: dat is
        # de taal van deze uitgave, niet van het origineel.
        assert items["Een Testboek"]["origin_region"] == "unknown"

    def test_filter_by_region(self, scanned: TestClient):
        """De eigenlijke eis: strips uit Europa los van manga uit Japan."""
        europe = scanned.get("/api/series", params={"region": "europe"}).json()
        japan = scanned.get("/api/series", params={"region": "japan"}).json()
        assert [item["title"] for item in europe["items"]] == ["Storm"]
        assert [item["title"] for item in japan["items"]] == ["Tesuto"]

    def test_filter_by_kind(self, scanned: TestClient):
        epubs = scanned.get("/api/series", params={"kind": "epub"}).json()
        assert [item["title"] for item in epubs["items"]] == ["Een Testboek"]

    def test_search(self, scanned: TestClient):
        found = scanned.get("/api/series", params={"search": "tesu"}).json()
        assert found["total"] == 1

    def test_pagination(self, scanned: TestClient):
        page = scanned.get("/api/series", params={"limit": 2, "offset": 0}).json()
        assert len(page["items"]) == 2
        assert page["total"] == 4

    def test_detail_lists_books_in_order(self, scanned: TestClient):
        series_id = next(
            item["id"]
            for item in scanned.get("/api/series").json()["items"]
            if item["title"] == "Storm"
        )
        detail = scanned.get(f"/api/series/{series_id}").json()
        assert [book["number"] for book in detail["books"]] == ["1", "2"]
        assert detail["books"][0]["has_file"] is True
        assert detail["books"][0]["extension"] == ".cbz"

    def test_manual_origin_sticks_through_a_rescan(self, scanned: TestClient):
        series_id = next(
            item["id"]
            for item in scanned.get("/api/series").json()["items"]
            if item["title"] == "Tesuto"
        )
        patched = scanned.patch(
            f"/api/series/{series_id}/origin",
            json={"origin_region": "europe", "origin_country": "be"},
        )
        assert patched.status_code == 200
        assert patched.json()["origin_source"] == "manual"

        root_id = scanned.get("/api/libraries").json()[0]["id"]
        scanned.post(f"/api/libraries/{root_id}/scan", params={"force": True})

        after = scanned.get(f"/api/series/{series_id}").json()
        assert after["origin_region"] == "europe"
        assert after["origin_source"] == "manual"

    def test_unknown_series(self, scanned: TestClient):
        assert scanned.get("/api/series/9999").status_code == 404


class TestPages:
    def _comic_book_id(self, client: TestClient) -> int:
        series_id = next(
            item["id"]
            for item in client.get("/api/series").json()["items"]
            if item["title"] == "Storm"
        )
        return int(client.get(f"/api/series/{series_id}").json()["books"][0]["id"])

    def test_page_is_webp_by_default(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        response = scanned.get(f"/api/books/{book_id}/pages/0")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
        assert response.headers["X-BookPal-Cache"] == "miss"

    def test_second_request_is_a_cache_hit(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        scanned.get(f"/api/books/{book_id}/pages/0")
        again = scanned.get(f"/api/books/{book_id}/pages/0")
        assert again.headers["X-BookPal-Cache"] == "hit"

    def test_kobo_profile_returns_grayscale_png(self, scanned: TestClient):
        """Dit is de spil voor de Kobo: het apparaat hoeft alleen te blitten."""
        book_id = self._comic_book_id(scanned)
        response = scanned.get(f"/api/books/{book_id}/pages/0", params={"profile": "kobo-clara"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        image = Image.open(BytesIO(response.content))
        assert image.mode == "L"
        assert image.width <= 1072

    def test_unknown_profile_is_a_400(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        response = scanned.get(f"/api/books/{book_id}/pages/0", params={"profile": "kobo-xyz"})
        assert response.status_code == 400

    def test_page_out_of_range(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        assert scanned.get(f"/api/books/{book_id}/pages/99").status_code == 404

    def test_negative_page(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        assert scanned.get(f"/api/books/{book_id}/pages/-1").status_code == 400

    def test_epub_pages_are_refused_with_an_explanation(self, scanned: TestClient):
        book_id = next(
            book["id"]
            for book in scanned.get("/api/books", params={"kind": "epub"}).json()["items"]
        )
        response = scanned.get(f"/api/books/{book_id}/pages/0")
        assert response.status_code == 409
        assert "epub" in response.json()["detail"]

    def test_pdf_pages_render(self, scanned: TestClient):
        book_id = next(
            book["id"] for book in scanned.get("/api/books", params={"kind": "pdf"}).json()["items"]
        )
        response = scanned.get(f"/api/books/{book_id}/pages/1")
        assert response.status_code == 200

    def test_cover(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        response = scanned.get(f"/api/books/{book_id}/cover", params={"profile": "thumb"})
        assert response.status_code == 200
        assert Image.open(BytesIO(response.content)).width <= 320

    def test_epub_cover_works(self, scanned: TestClient):
        book_id = next(
            book["id"]
            for book in scanned.get("/api/books", params={"kind": "epub"}).json()["items"]
        )
        assert scanned.get(f"/api/books/{book_id}/cover").status_code == 200

    def test_file_has_a_real_media_type(self, scanned: TestClient):
        """Clients bepalen het formaat mede op het mediatype; octet-stream
        zegt niets."""
        epub_id = next(
            book["id"]
            for book in scanned.get("/api/books", params={"kind": "epub"}).json()["items"]
        )
        response = scanned.get(f"/api/books/{epub_id}/file")
        assert response.headers["content-type"] == "application/epub+zip"

        comic_id = self._comic_book_id(scanned)
        comic = scanned.get(f"/api/books/{comic_id}/file")
        assert comic.headers["content-type"] == "application/vnd.comicbook+zip"

    def test_original_file_download(self, scanned: TestClient):
        book_id = next(
            book["id"]
            for book in scanned.get("/api/books", params={"kind": "epub"}).json()["items"]
        )
        response = scanned.get(f"/api/books/{book_id}/file")
        assert response.status_code == 200
        assert response.content.startswith(b"PK")

    def test_missing_file_is_reported_clearly(self, scanned: TestClient, library: Path):
        book_id = self._comic_book_id(scanned)
        (library / "strips" / "Storm 01.cbz").unlink()
        response = scanned.get(f"/api/books/{book_id}/pages/0")
        assert response.status_code == 410
        assert "scan" in response.json()["detail"]


class TestSeriesCover:
    """Precedence: handmatige pagina > bron-omslag > pagina 1 van het eerste
    boek. 'Storm 01.cbz' heeft 5 pagina's (zie fixtures.py)."""

    def _storm_series_id(self, client: TestClient) -> int:
        return next(
            item["id"]
            for item in client.get("/api/series").json()["items"]
            if item["title"] == "Storm"
        )

    def test_defaults_to_page_one_of_the_first_book(self, scanned: TestClient):
        series_id = self._storm_series_id(scanned)
        book_id = int(scanned.get(f"/api/series/{series_id}").json()["books"][0]["id"])

        series_cover = scanned.get(f"/api/series/{series_id}/cover")
        book_page = scanned.get(f"/api/books/{book_id}/pages/0")
        assert series_cover.status_code == 200
        assert series_cover.content == book_page.content

    def test_set_cover_page_changes_the_result(self, scanned: TestClient):
        series_id = self._storm_series_id(scanned)
        book_id = int(scanned.get(f"/api/series/{series_id}").json()["books"][0]["id"])

        patched = scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": 2})
        assert patched.status_code == 200
        assert patched.json()["cover_page_index"] == 2

        series_cover = scanned.get(f"/api/series/{series_id}/cover")
        page_two = scanned.get(f"/api/books/{book_id}/pages/2")
        page_zero = scanned.get(f"/api/books/{book_id}/pages/0")
        assert series_cover.content == page_two.content
        assert series_cover.content != page_zero.content

    def test_cover_page_also_applies_to_the_books_in_the_series(self, scanned: TestClient):
        """Bij scanlations zit de reclame op pagina 1 van élk hoofdstuk, dus de
        keuze moet ook de deel-kaartjes vullen — niet alleen de serie-omslag."""
        series_id = self._storm_series_id(scanned)
        books = scanned.get(f"/api/series/{series_id}").json()["books"]
        scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": 2})

        for book in books:
            cover = scanned.get(f"/api/books/{book['id']}/cover")
            page_two = scanned.get(f"/api/books/{book['id']}/pages/2")
            assert cover.status_code == 200
            assert cover.content == page_two.content

    def test_a_shorter_volume_falls_back_to_its_own_cover(self, scanned: TestClient):
        """Storm 02 heeft maar 3 pagina's; een keuze van pagina 4 bestaat daar
        niet en mag geen 404 op het kaartje opleveren."""
        series_id = self._storm_series_id(scanned)
        books = scanned.get(f"/api/series/{series_id}").json()["books"]
        short = next(b for b in books if b["page_count"] == 3)
        scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": 4})

        cover = scanned.get(f"/api/books/{short['id']}/cover")
        assert cover.status_code == 200
        assert cover.content == scanned.get(f"/api/books/{short['id']}/pages/0").content

    def test_clearing_restores_the_default_book_covers(self, scanned: TestClient):
        series_id = self._storm_series_id(scanned)
        book_id = int(scanned.get(f"/api/series/{series_id}").json()["books"][0]["id"])
        scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": 2})
        scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": None})

        cover = scanned.get(f"/api/books/{book_id}/cover")
        assert cover.content == scanned.get(f"/api/books/{book_id}/pages/0").content

    def test_out_of_range_page_is_rejected(self, scanned: TestClient):
        series_id = self._storm_series_id(scanned)
        response = scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": 99})
        assert response.status_code == 400

    def test_negative_page_is_rejected_by_validation(self, scanned: TestClient):
        series_id = self._storm_series_id(scanned)
        response = scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": -1})
        assert response.status_code == 422

    def test_epub_series_cannot_set_a_cover_page(self, scanned: TestClient):
        series_id = next(
            item["id"]
            for item in scanned.get("/api/series").json()["items"]
            if item["title"] == "Een Testboek"
        )
        response = scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": 1})
        assert response.status_code == 409

    def test_clearing_falls_back_to_the_default(self, scanned: TestClient):
        series_id = self._storm_series_id(scanned)
        scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": 2})
        cleared = scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": None})
        assert cleared.json()["cover_page_index"] is None

        book_id = int(scanned.get(f"/api/series/{series_id}").json()["books"][0]["id"])
        series_cover = scanned.get(f"/api/series/{series_id}/cover")
        page_zero = scanned.get(f"/api/books/{book_id}/pages/0")
        assert series_cover.content == page_zero.content

    def test_cover_page_wins_over_a_previously_attached_source_cover(
        self, scanned: TestClient, session
    ):
        series_id = self._storm_series_id(scanned)
        series = session.get(Series, series_id)
        series.cover_url = "https://example.test/never-fetched.jpg"
        session.commit()

        scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": 1})
        book_id = int(scanned.get(f"/api/series/{series_id}").json()["books"][0]["id"])
        series_cover = scanned.get(f"/api/series/{series_id}/cover")
        page_one = scanned.get(f"/api/books/{book_id}/pages/1")
        assert series_cover.content == page_one.content

    def test_clearing_reveals_the_source_cover_again(
        self, scanned: TestClient, session, monkeypatch
    ):
        """cover_url wordt niet weggegooid door een paginakeuze — alleen
        overschaduwd. Terugzetten op de standaardkeuze maakt hem weer zichtbaar."""
        def fake_get(url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(200, content=_solid_png(), request=httpx.Request("GET", url))

        monkeypatch.setattr("bookpal.images.pipeline.httpx.get", fake_get)

        series_id = self._storm_series_id(scanned)
        series = session.get(Series, series_id)
        series.cover_url = "https://example.test/echte-omslag.jpg"
        session.commit()

        scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": 1})
        book_id = int(scanned.get(f"/api/series/{series_id}").json()["books"][0]["id"])
        with_page = scanned.get(f"/api/series/{series_id}/cover")
        page_one = scanned.get(f"/api/books/{book_id}/pages/1")
        assert with_page.content == page_one.content  # de pagina wint nog

        scanned.patch(f"/api/series/{series_id}/cover-page", json={"page_index": None})
        after_clearing = scanned.get(f"/api/series/{series_id}/cover")
        # Herbewerkt door de eigen beeldpipeline (webp), dus niet byte-voor-byte
        # gelijk aan de bron-PNG — wel duidelijk niet meer 'pagina 1'.
        assert after_clearing.content != page_one.content
        assert after_clearing.headers["content-type"] == "image/webp"


def _solid_png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class TestBookDetail:
    def test_detail_has_series_title_and_rtl(self, scanned: TestClient):
        series_id = next(
            item["id"]
            for item in scanned.get("/api/series").json()["items"]
            if item["title"] == "Tesuto"
        )
        book_id = scanned.get(f"/api/series/{series_id}").json()["books"][0]["id"]
        detail = scanned.get(f"/api/books/{book_id}").json()
        assert detail["series_title"] == "Tesuto"
        # Manga leest van rechts naar links.
        assert detail["right_to_left"] is True

    def test_epub_detail_has_toc(self, scanned: TestClient):
        book_id = next(
            book["id"]
            for book in scanned.get("/api/books", params={"kind": "epub"}).json()["items"]
        )
        detail = scanned.get(f"/api/books/{book_id}").json()
        assert [entry["title"] for entry in detail["toc"]] == [
            "Hoofdstuk 1",
            "Hoofdstuk 2",
            "Hoofdstuk 3",
        ]


class TestProgress:
    def _book_id(self, client: TestClient) -> int:
        return int(client.get("/api/books").json()["items"][0]["id"])

    def test_put_and_get(self, scanned: TestClient):
        book_id = self._book_id(scanned)
        response = scanned.put(
            "/api/progress",
            json={"book_id": book_id, "position": {"page": 3}, "percent": 60.0, "device": "web"},
        )
        assert response.status_code == 200
        assert response.json()["position"] == {"page": 3}

        fetched = scanned.get(f"/api/progress/{book_id}").json()
        assert fetched["percent"] == 60.0
        assert fetched["device"] == "web"

    def test_last_writer_wins_across_devices(self, scanned: TestClient):
        """Web zet pagina 3, daarna zet de Kobo pagina 10 — die laatste geldt."""
        book_id = self._book_id(scanned)
        scanned.put(
            "/api/progress",
            json={"book_id": book_id, "position": {"page": 3}, "percent": 30.0, "device": "web"},
        )
        scanned.put(
            "/api/progress",
            json={"book_id": book_id, "position": {"page": 10}, "percent": 90.0, "device": "kobo"},
        )
        current = scanned.get(f"/api/progress/{book_id}").json()
        assert current["position"] == {"page": 10}
        assert current["device"] == "kobo"

    def test_hundred_percent_marks_finished(self, scanned: TestClient):
        book_id = self._book_id(scanned)
        body = scanned.put("/api/progress", json={"book_id": book_id, "percent": 100.0}).json()
        assert body["finished"] is True

    def test_progress_shows_up_on_the_book(self, scanned: TestClient):
        book_id = self._book_id(scanned)
        scanned.put("/api/progress", json={"book_id": book_id, "percent": 42.0})
        book = scanned.get(f"/api/books/{book_id}").json()
        assert book["progress"]["percent"] == 42.0

    def test_continue_reading_list(self, scanned: TestClient):
        books = scanned.get("/api/books").json()["items"]
        scanned.put("/api/progress", json={"book_id": books[0]["id"], "percent": 20.0})
        scanned.put("/api/progress", json={"book_id": books[1]["id"], "percent": 100.0})

        unfinished = scanned.get("/api/progress").json()
        assert len(unfinished) == 1
        assert unfinished[0]["percent"] == 20.0

        everything = scanned.get("/api/progress", params={"unfinished_only": False}).json()
        assert len(everything) == 2

    def test_unknown_book(self, scanned: TestClient):
        assert (
            scanned.put("/api/progress", json={"book_id": 999, "percent": 10.0}).status_code == 404
        )

    def test_no_progress_yet(self, scanned: TestClient):
        assert scanned.get(f"/api/progress/{self._book_id(scanned)}").status_code == 404

    def test_delete(self, scanned: TestClient):
        book_id = self._book_id(scanned)
        scanned.put("/api/progress", json={"book_id": book_id, "percent": 50.0})
        assert scanned.delete(f"/api/progress/{book_id}").status_code == 204
        assert scanned.get(f"/api/progress/{book_id}").status_code == 404

    def test_percent_out_of_range_is_rejected(self, scanned: TestClient):
        book_id = self._book_id(scanned)
        assert (
            scanned.put("/api/progress", json={"book_id": book_id, "percent": 150.0}).status_code
            == 422
        )
