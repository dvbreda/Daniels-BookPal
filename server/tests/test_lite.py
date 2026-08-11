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
        assert f'/api/books/{book_id}/pages/0' in response.text
        assert f'/lite/books/{book_id}/read/1' in response.text
        assert f'/lite/books/{book_id}/read/-1' not in response.text

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
                payload=PageResult(
                    bubbles=[Bubble(0.1, 0.1, 0.9, 0.4, "HI", "HOI")]
                ).to_payload(),
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
        assert f'/api/books/{book_id}/pages/0/overlay' in response.text
        assert 'class="stack"' in response.text
        assert "Origineel" in response.text

    def test_the_setting_survives_turning_the_page(self, scanned: TestClient, session: Session):
        """Je zet het één keer aan en bladert daarna gewoon door."""
        book_id = self._comic_book_id(scanned)
        self._translate(session, book_id)
        response = scanned.get(f"/lite/books/{book_id}/read/0", params={"vertaal": 1})
        assert f'/lite/books/{book_id}/read/1?vertaal=1' in response.text

    def test_the_page_image_itself_is_not_baked(self, scanned: TestClient, session: Session):
        """De pagina blijft één gedeelde afbeelding; alleen de laag komt erbij.
        Anders staat dezelfde pagina twee keer in de cache en over de lijn."""
        book_id = self._comic_book_id(scanned)
        self._translate(session, book_id)
        response = scanned.get(f"/lite/books/{book_id}/read/0", params={"vertaal": 1})
        assert "translate=" not in response.text
