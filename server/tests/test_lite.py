"""BookPal Lite: server-rendered HTML zonder JavaScript, voor de Kobo-browser."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.models import Series, Translation
from bookpal.translate.base import Bubble, PageResult


class TestLiteBrowsing:
    def test_home_lists_series(self, scanned: TestClient):
        response = scanned.get("/lite")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Storm" in response.text
        assert "Tesuto" in response.text

    def test_series_lists_its_books(self, scanned: TestClient):
        series_id = next(
            item["id"]
            for item in scanned.get("/api/series").json()["items"]
            if item["title"] == "Storm"
        )
        response = scanned.get(f"/lite/series/{series_id}")
        assert response.status_code == 200
        assert response.text.count('href="/lite/books/') == 2

    def test_unknown_series_is_404(self, scanned: TestClient):
        assert scanned.get("/lite/series/9999").status_code == 404


class TestLiteReading:
    def _comic_book_id(self, client: TestClient) -> int:
        series_id = next(
            item["id"]
            for item in client.get("/api/series").json()["items"]
            if item["title"] == "Storm"
        )
        return int(client.get(f"/api/series/{series_id}").json()["books"][0]["id"])

    def test_book_redirects_to_first_unread_page(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        response = scanned.get(f"/lite/books/{book_id}", follow_redirects=False)
        assert response.status_code in (302, 307)
        assert response.headers["location"] == f"/lite/books/{book_id}/read/0"

    def test_book_resumes_at_saved_page(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        scanned.put("/api/progress", json={"book_id": book_id, "percent": 40.0})
        # Handmatig een leespositie zetten, want /lite zelf schrijft alleen /read.
        scanned.put(
            "/api/progress",
            json={"book_id": book_id, "position": {"page": 2}, "percent": 40.0},
        )
        response = scanned.get(f"/lite/books/{book_id}", follow_redirects=False)
        assert response.headers["location"] == f"/lite/books/{book_id}/read/2"

    def test_finished_book_restarts_at_page_zero(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        scanned.put(
            "/api/progress",
            json={"book_id": book_id, "position": {"page": 4}, "percent": 100.0},
        )
        response = scanned.get(f"/lite/books/{book_id}", follow_redirects=False)
        assert response.headers["location"] == f"/lite/books/{book_id}/read/0"

    def test_read_page_embeds_image_and_has_next_link(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        response = scanned.get(f"/lite/books/{book_id}/read/0")
        assert response.status_code == 200
        assert f"/api/books/{book_id}/pages/0" in response.text
        assert f"/lite/books/{book_id}/read/1" in response.text
        assert f"/lite/books/{book_id}/read/-1" not in response.text

    def test_read_page_records_progress(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        scanned.get(f"/lite/books/{book_id}/read/2")
        progress = scanned.get(f"/api/progress/{book_id}").json()
        assert progress["position"] == {"page": 2}
        assert progress["device"] == "lite"
        assert progress["percent"] == 60.0  # (2 + 1) / 5 pages

    def test_last_page_marks_finished(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        scanned.get(f"/lite/books/{book_id}/read/4")
        progress = scanned.get(f"/api/progress/{book_id}").json()
        assert progress["finished"] is True

    def test_out_of_range_page_is_404(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        assert scanned.get(f"/lite/books/{book_id}/read/99").status_code == 404

    def test_epub_offers_a_download_link_instead(self, scanned: TestClient):
        book_id = next(
            book["id"]
            for book in scanned.get("/api/books", params={"kind": "epub"}).json()["items"]
        )
        response = scanned.get(f"/lite/books/{book_id}", follow_redirects=False)
        assert response.status_code == 200
        assert f"/api/books/{book_id}/file" in response.text

    def test_epub_read_route_is_refused(self, scanned: TestClient):
        book_id = next(
            book["id"]
            for book in scanned.get("/api/books", params={"kind": "epub"}).json()["items"]
        )
        assert scanned.get(f"/lite/books/{book_id}/read/0").status_code == 409

    def test_profile_carries_across_links(self, scanned: TestClient):
        book_id = self._comic_book_id(scanned)
        response = scanned.get(f"/lite/books/{book_id}/read/0?profile=kobo-clara")
        assert "profile=kobo-clara" in response.text

    def test_unknown_profile_is_a_400(self, scanned: TestClient):
        assert scanned.get("/lite", params={"profile": "kobo-xyz"}).status_code == 400

    def test_rtl_book_gets_reversed_nav_class(self, scanned: TestClient):
        series_id = next(
            item["id"]
            for item in scanned.get("/api/series").json()["items"]
            if item["title"] == "Tesuto"
        )
        book_id = scanned.get(f"/api/series/{series_id}").json()["books"][0]["id"]
        response = scanned.get(f"/lite/books/{book_id}/read/0")
        assert 'class="nav rtl"' in response.text

    def test_titles_are_html_escaped(self, client: TestClient, session: Session):
        session.add(Series(title="<script>alert(1)</script>", sort_title="script"))
        session.commit()

        response = client.get("/lite")
        assert "<script>alert(1)</script>" not in response.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


class TestLiteTranslation:
    """De vertaallaag als losse doorzichtige PNG (M8).

    Lite heeft geen JavaScript, dus aan- en uitzetten is een gewone link en de
    laag ligt er met CSS overheen. Dat werkt in de Kobo-browser.
    """

    def _comic_book_id(self, client: TestClient) -> int:
        series_id = next(
            item["id"]
            for item in client.get("/api/series").json()["items"]
            if item["title"] == "Storm"
        )
        return int(client.get(f"/api/series/{series_id}").json()["books"][0]["id"])

    def _translate(self, session: Session, book_id: int, page: int = 0) -> None:
        session.add(
            Translation(
                book_id=book_id,
                page_index=page,
                target_lang=settings.translate_lang,
                provider="gemini",
                payload=PageResult(bubbles=[Bubble(0.1, 0.1, 0.9, 0.4, "HI", "HOI")]).to_payload(),
            )
        )
        session.commit()

    def test_no_toggle_when_the_page_is_not_translated(self, scanned: TestClient):
        """Een link naar een vertaling die niet bestaat, levert een lege laag
        en een verwarde lezer op."""
        book_id = self._comic_book_id(scanned)
        response = scanned.get(f"/lite/books/{book_id}/read/0")
        assert "vertaal=1" not in response.text
        assert "/overlay" not in response.text

    def test_a_translated_page_offers_the_toggle(self, scanned: TestClient, session: Session):
        book_id = self._comic_book_id(scanned)
        self._translate(session, book_id)
        response = scanned.get(f"/lite/books/{book_id}/read/0")
        assert "vertaal=1" in response.text
        assert "/overlay" not in response.text  # nog niet aangezet

    def test_switching_it_on_stacks_the_layer(self, scanned: TestClient, session: Session):
        book_id = self._comic_book_id(scanned)
        self._translate(session, book_id)
        response = scanned.get(f"/lite/books/{book_id}/read/0", params={"vertaal": 1})
        assert f"/api/books/{book_id}/pages/0/overlay" in response.text
        assert 'class="stack"' in response.text
        assert "Origineel" in response.text

    def test_the_setting_survives_turning_the_page(self, scanned: TestClient, session: Session):
        """Je zet het één keer aan en bladert daarna gewoon door."""
        book_id = self._comic_book_id(scanned)
        self._translate(session, book_id)
        response = scanned.get(f"/lite/books/{book_id}/read/0", params={"vertaal": 1})
        assert f"/lite/books/{book_id}/read/1?vertaal=1" in response.text

    def test_the_page_image_itself_is_not_baked(self, scanned: TestClient, session: Session):
        """De pagina blijft één gedeelde afbeelding; alleen de laag komt erbij.
        Anders staat dezelfde pagina twee keer in de cache en over de lijn."""
        book_id = self._comic_book_id(scanned)
        self._translate(session, book_id)
        response = scanned.get(f"/lite/books/{book_id}/read/0", params={"vertaal": 1})
        assert "translate=" not in response.text


class TestHidingWhatYouRead:
    """Op een Kobo scroll je niet graag langs honderd uitgelezen hoofdstukken."""

    def _reeks(self, session: Session, aantal: int, gelezen: int, naam: str = "Reeks") -> Series:
        from bookpal.db import current_user
        from bookpal.models import Book, BookKind, File, LibraryRoot, Progress

        root = LibraryRoot(name=naam, path=f"/tmp/lite-{naam}")
        session.add(root)
        session.flush()
        series = Series(title=naam, sort_title=naam.lower())
        session.add(series)
        session.flush()
        for index in range(aantal):
            bestand = File(
                library_root_id=root.id,
                path=f"/tmp/lite-{naam}/{index}.cbz",
                size=1,
                mtime=0.0,
                extension=".cbz",
            )
            session.add(bestand)
            session.flush()
            boek = Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title=f"Hoofdstuk {index + 1}",
                number=str(index + 1),
                sort_number=float(index + 1),
                page_count=10,
                file_id=bestand.id,
            )
            session.add(boek)
            session.flush()
            if index < gelezen:
                session.add(
                    Progress(
                        user_id=current_user(session).id,
                        book_id=boek.id,
                        percent=100.0,
                        finished=True,
                    )
                )
        session.commit()
        return series

    def test_the_switch_hides_finished_chapters(self, client: TestClient, session: Session):
        series = self._reeks(session, 4, gelezen=2)

        alles = client.get(f"/lite/series/{series.id}").text
        assert "Hoofdstuk 1" in alles

        verborgen = client.get(f"/lite/series/{series.id}", params={"verberg": 1}).text
        assert "Hoofdstuk 1" not in verborgen
        assert "Hoofdstuk 3" in verborgen

    def test_the_switch_stays_on_across_links(self, client: TestClient, session: Session):
        """Zonder JavaScript is de URL de enige plek waar een stand kan wonen."""
        series = self._reeks(session, 2, gelezen=1)
        pagina = client.get("/lite", params={"verberg": 1}).text
        assert f"/lite/series/{series.id}?verberg=1" in pagina

    def test_a_series_you_finished_disappears_from_the_library(
        self, client: TestClient, session: Session
    ):
        self._reeks(session, 2, gelezen=2, naam="Uit")
        self._reeks(session, 2, gelezen=1, naam="Bezig")

        verborgen = client.get("/lite", params={"verberg": 1}).text
        assert "Bezig" in verborgen
        assert ">Uit<" not in verborgen

    def test_without_the_switch_everything_is_there(self, client: TestClient, session: Session):
        self._reeks(session, 2, gelezen=2, naam="Uit")
        pagina = client.get("/lite").text
        assert "Uit" in pagina

    def test_the_switch_offers_the_way_back(self, client: TestClient, session: Session):
        self._reeks(session, 1, gelezen=0)
        aan = client.get("/lite", params={"verberg": 1}).text
        assert "Alles tonen" in aan
        uit = client.get("/lite").text
        assert "Gelezen verbergen" in uit


class TestReadingOptions:
    """Wat de Kobo wél aankan: bijsnijden en contrast, op de server gedaan."""

    def _boek(self, session: Session, client: TestClient):
        from bookpal.db import current_user  # noqa: F401 - houdt de gebruiker aan

        response = client.get("/lite")
        assert response.status_code == 200

    def test_the_options_travel_along_in_every_link(
        self, client: TestClient, scanned_series: int | None = None
    ):
        """Zonder JavaScript is de URL de enige plek waar een stand kan wonen."""
        pagina = client.get("/lite", params={"snij": 1, "contrast": 130}).text
        assert "snij=1" in pagina
        assert "contrast=130" in pagina

    def test_the_library_shows_covers(self, client: TestClient, session: Session):
        series = Series(title="Met omslag", sort_title="met omslag")
        session.add(series)
        session.commit()

        pagina = client.get("/lite").text
        assert f"/api/series/{series.id}/cover" in pagina


class TestLiteHomeAndGrid:
    """Een startpagina die je terugbrengt, en omslagen als je die wilt zien."""

    def _bezig(self, session: Session):
        from bookpal.db import current_user
        from bookpal.models import Book, BookKind, File, LibraryRoot, Progress

        root = LibraryRoot(name="R", path="/tmp/lite-home")
        session.add(root)
        session.flush()
        series = Series(title="Bezig", sort_title="bezig")
        session.add(series)
        session.flush()
        bestand = File(
            library_root_id=root.id,
            path="/tmp/lite-home/1.cbz",
            size=1,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(bestand)
        session.flush()
        boek = Book(
            series_id=series.id,
            kind=BookKind.COMIC,
            title="Hoofdstuk 1",
            number="1",
            sort_number=1.0,
            page_count=20,
            file_id=bestand.id,
        )
        session.add(boek)
        session.flush()
        session.add(
            Progress(
                user_id=current_user(session).id,
                book_id=boek.id,
                percent=35.0,
                finished=False,
                position={"page": 7},
            )
        )
        session.commit()
        return series, boek

    def test_the_home_takes_you_back_to_your_page(self, client: TestClient, session: Session):
        _series, boek = self._bezig(session)
        pagina = client.get("/lite").text
        assert "Verder lezen · pagina 8" in pagina
        assert f"/lite/books/{boek.id}/read/7" in pagina

    def test_without_progress_there_is_no_block(self, client: TestClient, session: Session):
        session.add(Series(title="Niets", sort_title="niets"))
        session.commit()
        assert 'class="hero"' not in client.get("/lite").text

    def test_a_series_can_be_shown_as_a_grid(self, client: TestClient, session: Session):
        series, _boek = self._bezig(session)

        lijst = client.get(f"/lite/series/{series.id}").text
        assert 'class="raster"' not in lijst
        assert "Als raster" in lijst

        raster = client.get(f"/lite/series/{series.id}", params={"raster": 1}).text
        assert 'class="raster"' in raster
        assert "Als lijst" in raster

    def test_the_view_choice_travels_along(self, client: TestClient, session: Session):
        """Anders val je terug in de lijst zodra je een hoofdstuk opent."""
        series, boek = self._bezig(session)
        raster = client.get(f"/lite/series/{series.id}", params={"raster": 1}).text
        assert f"/lite/books/{boek.id}?raster=1" in raster


class TestNoWebpForTheKobo:
    """De browser van een Kobo kent geen webp; dan blijft er een leeg vlak staan."""

    def test_page_images_ask_for_a_png_profile(self, client: TestClient, session: Session):
        from bookpal.images import PROFILES

        _series, boek = TestLiteHomeAndGrid()._bezig(session)
        pagina = client.get(f"/lite/books/{boek.id}/read/0").text
        import re

        for src in re.findall(r'src="(/api/books/[^"]+)"', pagina):
            assert "profile=" in src, src
            naam = src.split("profile=")[1].split("&")[0]
            assert PROFILES[naam].format != "webp", naam

    def test_covers_ask_for_a_png_profile(self, client: TestClient, session: Session):
        from bookpal.images import PROFILES

        TestLiteHomeAndGrid()._bezig(session)
        h = client.get("/lite").text
        naam = h.split("cover?profile=")[1].split('"')[0]
        assert PROFILES[naam].format != "webp"

    def test_asking_for_a_webp_profile_still_gets_you_a_picture(
        self, client: TestClient, session: Session
    ):
        """Een plaatje dat er is weegt zwaarder dan een paar kilobyte verschil."""
        _series, boek = TestLiteHomeAndGrid()._bezig(session)
        import re

        from bookpal.images import PROFILES

        pagina = client.get(f"/lite/books/{boek.id}/read/0", params={"profile": "web"}).text
        srcs = re.findall(r'src="/api/books/[^"]*profile=([^"&]+)', pagina)
        assert srcs, "er hoort een pagina-plaatje te staan"
        assert all(PROFILES[naam].format != "webp" for naam in srcs)
