"""Bronnen (M5).

Alles draait tegen een nagebootste MangaDex: de suite mag nooit het netwerk op,
en de antwoorden hieronder zijn overgenomen uit echte API-antwoorden zodat het
contract klopt.
"""

from __future__ import annotations

import zipfile
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.models import (
    Book,
    File,
    OriginRegion,
    OriginSource,
    Source,
    SubscriptionPolicy,
    utcnow,
)
from bookpal.sources import RateLimiter, SourceError
from bookpal.sources import service as source_service
from bookpal.sources.mangadex import MangaDexSource

MANGA_ID = "8e6b0382-49d7-4131-8f4b-2e4df8a38102"
CHAPTER_ID = "ebb7ea74-7247-4814-a831-6c661221ebb9"

MANGA_PAYLOAD = {
    "id": MANGA_ID,
    "type": "manga",
    "attributes": {
        "title": {"ja-ro": "Crayon Shin-chan"},
        "altTitles": [{"en": "Crayon Shin Chan"}],
        "description": {"en": "Een jongen van vijf."},
        "originalLanguage": "ja",
        "year": 1990,
        "status": "completed",
        "links": {"mal": "2435", "al": "32435"},
    },
}


def _chapter(ref: str, chapter: str, volume: str, pages: int = 2, **extra: object) -> dict:
    attributes = {
        "volume": volume,
        "chapter": chapter,
        "title": f"Deel {chapter}",
        "translatedLanguage": "en",
        "externalUrl": None,
        "isUnavailable": False,
        "pages": pages,
        "publishAt": "2020-05-19T17:04:12+00:00",
    }
    attributes.update(extra)
    return {"id": ref, "type": "chapter", "attributes": attributes}


def _png() -> bytes:
    """Een geldig 1x1-PNG, zodat de beeldpipeline er echt mee kan werken."""
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (2, 3), (200, 40, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def make_source(handler=None) -> MangaDexSource:
    """Een MangaDexSource die tegen een nagebootste API praat."""

    def default_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/manga":
            return httpx.Response(200, json={"result": "ok", "data": [MANGA_PAYLOAD]})
        if path == f"/manga/{MANGA_ID}":
            return httpx.Response(200, json={"result": "ok", "data": MANGA_PAYLOAD})
        if path == f"/manga/{MANGA_ID}/feed":
            return httpx.Response(
                200,
                json={
                    "result": "ok",
                    "total": 2,
                    "data": [
                        _chapter(CHAPTER_ID, "1", "1"),
                        _chapter("tweede-ref", "2", "1"),
                    ],
                },
            )
        if path.startswith("/at-home/server/"):
            return httpx.Response(
                200,
                json={
                    "result": "ok",
                    "baseUrl": "https://cdn.example.test",
                    "chapter": {
                        "hash": "abc123",
                        "data": ["1-vol.jpg", "2-vol.jpg"],
                        "dataSaver": ["1-klein.jpg", "2-klein.jpg"],
                    },
                },
            )
        if request.url.host == "cdn.example.test":
            return httpx.Response(200, content=_png())
        return httpx.Response(404, json={"result": "error"})

    transport = httpx.MockTransport(handler or default_handler)
    client = httpx.Client(transport=transport, base_url="https://api.mangadex.org")
    # Hoge snelheid: de limiter zelf wordt apart getest, hier wil je geen wachttijd.
    return MangaDexSource(client=client, rate=1000.0, at_home_rate=1000.0)


class TestRateLimiter:
    def test_allows_a_burst_then_throttles(self):
        limiter = RateLimiter(rate=1000.0, burst=3)
        for _ in range(3):
            limiter.acquire()
        assert limiter._tokens < 1.0

    def test_refuses_a_nonsensical_rate(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=0)

    def test_acquire_eventually_returns(self):
        limiter = RateLimiter(rate=200.0, burst=1)
        for _ in range(3):
            limiter.acquire()  # zou moeten wachten, niet blokkeren


class TestMangaDexSearch:
    def test_search_maps_the_contract(self):
        results = make_source().search("shin chan")
        assert len(results) == 1
        result = results[0]
        assert result.ref == MANGA_ID
        assert result.title == "Crayon Shin-chan"
        assert result.year == 1990

    def test_original_language_is_kept_for_the_origin_chain(self):
        assert make_source().search("x")[0].original_language == "ja"

    def test_tracker_ids_come_along_for_m7(self):
        assert make_source().search("x")[0].tracker_ids == {"mal": "2435", "anilist": "32435"}

    def test_detail(self):
        assert make_source().detail(MANGA_ID).title == "Crayon Shin-chan"

    def test_english_title_wins_when_present(self):
        payload = {**MANGA_PAYLOAD, "attributes": {**MANGA_PAYLOAD["attributes"]}}
        payload["attributes"]["title"] = {"ja-ro": "Romaji", "en": "Engels"}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": "ok", "data": [payload]})

        assert make_source(handler).search("x")[0].title == "Engels"

    def test_http_error_becomes_a_source_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"result": "error"})

        with pytest.raises(SourceError):
            make_source(handler).search("x")

    def test_rate_limit_is_reported_clearly(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"result": "error"})

        with pytest.raises(SourceError, match="rate limit"):
            make_source(handler).search("x")


class TestMangaDexChapters:
    def test_chapters_are_sorted_and_mapped(self):
        chapters = make_source().chapters(MANGA_ID)
        assert [c.number for c in chapters] == ["1", "2"]
        assert chapters[0].page_count == 2

    def test_external_chapters_are_skipped(self):
        """Een hoofdstuk dat elders staat kunnen we niet ophalen, dus tonen we
        het ook niet als beschikbaar."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/feed"):
                return httpx.Response(
                    200,
                    json={
                        "result": "ok",
                        "total": 2,
                        "data": [
                            _chapter("extern", "1", "1", externalUrl="https://elders.test"),
                            _chapter("bruikbaar", "2", "1"),
                        ],
                    },
                )
            return httpx.Response(404, json={"result": "error"})

        chapters = make_source(handler).chapters(MANGA_ID)
        assert [c.ref for c in chapters] == ["bruikbaar"]

    def test_unavailable_chapters_are_skipped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/feed"):
                return httpx.Response(
                    200,
                    json={
                        "result": "ok",
                        "total": 1,
                        "data": [_chapter("weg", "1", "1", isUnavailable=True)],
                    },
                )
            return httpx.Response(404, json={"result": "error"})

        assert make_source(handler).chapters(MANGA_ID) == []


class TestMangaDexPages:
    def test_page_urls(self):
        urls = make_source().page_urls(CHAPTER_ID)
        assert urls == [
            "https://cdn.example.test/data/abc123/1-vol.jpg",
            "https://cdn.example.test/data/abc123/2-vol.jpg",
        ]

    def test_data_saver_uses_the_smaller_set(self):
        urls = make_source().page_urls(CHAPTER_ID, data_saver=True)
        assert urls[0] == "https://cdn.example.test/data-saver/abc123/1-klein.jpg"

    def test_download_writes_a_readable_cbz(self, tmp_path: Path):
        target = tmp_path / "hoofdstuk.cbz"
        make_source().download(CHAPTER_ID, target)
        assert target.is_file()
        with zipfile.ZipFile(target) as archive:
            assert archive.namelist() == ["001.jpg", "002.jpg"]

    def test_a_failed_download_leaves_no_half_file(self, tmp_path: Path):
        """Een half archief mag de scanner nooit als geldig tegenkomen."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/at-home/"):
                return httpx.Response(
                    200,
                    json={
                        "result": "ok",
                        "baseUrl": "https://cdn.example.test",
                        "chapter": {"hash": "h", "data": ["1.jpg"], "dataSaver": []},
                    },
                )
            return httpx.Response(503)

        target = tmp_path / "kapot.cbz"
        with pytest.raises(SourceError):
            make_source(handler).download(CHAPTER_ID, target)
        assert not target.exists()
        assert not target.with_suffix(".cbz.partial").exists()


class TestServiceLayer:
    def _source_row(self, session: Session) -> Source:
        row = Source(type="mangadex", name="MangaDex")
        session.add(row)
        session.flush()
        return row

    def test_subscribe_creates_series_and_chapters(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        series, subscription, added = source_service.subscribe(
            session, source_row, make_source(), MANGA_ID
        )
        assert series.title == "Crayon Shin-chan"
        assert added == 2
        assert subscription.policy is SubscriptionPolicy.READAHEAD

        books = session.query(Book).filter_by(series_id=series.id).all()
        assert len(books) == 2
        # Boeken van een bron hebben nog geen bestand — dat is het hele punt.
        assert all(book.file_id is None for book in books)
        assert all(book.source_ref for book in books)

    def test_subscribe_sets_origin_from_the_source(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        assert series.origin_region.value == "japan"
        assert series.origin_source.value == "online"

    def test_subscribe_brings_tracker_ids_for_m7(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        assert series.tracker_ids["mal"] == "2435"

    def test_subscribing_twice_adds_nothing(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        _, _, added = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        assert added == 0

    def test_manual_origin_survives_a_source_refresh(self, session: Session, temp_settings: Path):
        """Dezelfde belofte als bij een rescan: jouw keuze wint."""
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        series.origin_region = OriginRegion.EUROPE
        series.origin_source = OriginSource.MANUAL
        session.flush()

        source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        assert series.origin_region is OriginRegion.EUROPE
        assert series.origin_source is OriginSource.MANUAL

    def test_download_attaches_a_file_to_the_book(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        book = session.query(Book).filter_by(series_id=series.id).first()
        assert book is not None

        source_service.download_book(session, make_source(), book)
        assert book.file_id is not None
        assert book.expires_at is None
        file_row = session.get(File, book.file_id)
        assert file_row is not None
        assert Path(file_row.path).is_file()

    def test_a_second_download_is_a_no_op(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        book = session.query(Book).filter_by(series_id=series.id).first()
        assert book is not None
        source_service.download_book(session, make_source(), book)
        first_file_id = book.file_id

        source_service.download_book(session, make_source(), book)
        assert book.file_id == first_file_id

    def test_a_vanished_file_is_fetched_again(self, session: Session, temp_settings: Path):
        """Een file_id in de database bewijst niet dat het bestand er nog is —
        een opgeruimd volume mag een hoofdstuk niet onherstelbaar maken."""
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        book = session.query(Book).filter_by(series_id=series.id).first()
        assert book is not None
        source_service.download_book(session, make_source(), book)

        file_row = session.get(File, book.file_id)
        assert file_row is not None
        path = Path(file_row.path)
        path.unlink()

        source_service.download_book(session, make_source(), book)
        assert path.is_file()

    def test_temporary_download_gets_an_expiry(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        book = session.query(Book).filter_by(series_id=series.id).first()
        assert book is not None

        source_service.download_book(session, make_source(), book, temporary=True, ttl_days=7)
        assert book.expires_at is not None

    def test_expiring_removes_the_file_but_keeps_the_book(
        self, session: Session, temp_settings: Path
    ):
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        book = session.query(Book).filter_by(series_id=series.id).first()
        assert book is not None
        source_service.download_book(session, make_source(), book, temporary=True, ttl_days=1)
        file_row = session.get(File, book.file_id)
        assert file_row is not None
        path = Path(file_row.path)
        assert path.is_file()

        removed = source_service.expire_downloads(session, now=utcnow() + timedelta(days=2))
        assert removed == 1
        assert not path.exists()
        # Het hoofdstuk blijft bestaan; alleen het bestand is weg.
        assert session.get(Book, book.id) is not None
        assert book.file_id is None
        assert book.source_ref is not None

    def test_downloads_land_in_the_download_root(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        book = session.query(Book).filter_by(series_id=series.id).first()
        assert book is not None
        source_service.download_book(session, make_source(), book)

        file_row = session.get(File, book.file_id)
        assert file_row is not None
        assert str(settings.download_dir.resolve()) in file_row.path


class TestSafeName:
    def test_strips_characters_that_break_a_filesystem(self):
        assert "/" not in source_service.safe_name("Vol 1/2: test")
        assert ":" not in source_service.safe_name("Vol 1/2: test")

    def test_falls_back_when_nothing_is_left(self):
        assert source_service.safe_name("///") == "zonder-titel"

    def test_shortens_very_long_titles(self):
        assert len(source_service.safe_name("x" * 500)) <= 120


class TestSourcesApi:
    def test_types_lists_what_this_build_knows(self, client):
        assert "mangadex" in client.get("/api/sources/types").json()

    def test_create_and_list(self, client):
        created = client.post("/api/sources", json={"type": "mangadex", "name": "MangaDex"})
        assert created.status_code == 201
        assert [s["name"] for s in client.get("/api/sources").json()] == ["MangaDex"]

    def test_unknown_type_is_rejected(self, client):
        response = client.post("/api/sources", json={"type": "verzonnen", "name": "X"})
        assert response.status_code == 400

    def test_search_on_unknown_source_is_404(self, client):
        assert client.get("/api/sources/999/search", params={"q": "x"}).status_code == 404

    def test_download_on_a_local_book_is_refused(self, scanned):
        book_id = scanned.get("/api/books").json()["items"][0]["id"]
        response = scanned.post(f"/api/sources/books/{book_id}/download", json={})
        assert response.status_code == 409
        assert "bron" in response.json()["detail"]

    def test_expire_endpoint_runs(self, client):
        assert client.post("/api/sources/downloads/expire").json() == {"removed": 0}
