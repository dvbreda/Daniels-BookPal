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
    BookKind,
    File,
    OriginRegion,
    OriginSource,
    Progress,
    Series,
    Source,
    SubscriptionPolicy,
    utcnow,
)
from bookpal.sources import ChapterInfo, RateLimiter, SourceError, mangadex
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
    "relationships": [
        {
            "id": "cover-rel-id",
            "type": "cover_art",
            "attributes": {"fileName": "e0e1c1d1.jpg"},
        }
    ],
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

    def test_cover_url_is_the_official_cover_not_page_one(self):
        """Bij scanlaties staat er vaak een credits-pagina van de
        vertaalgroep over de echte omslag heen; de bron heeft de schone
        versie apart."""
        cover = make_source().search("x")[0].cover_url
        assert cover == f"{mangadex.COVERS_BASE}/{MANGA_ID}/e0e1c1d1.jpg.512.jpg"

    def test_no_cover_url_when_the_bron_has_none(self):
        payload = {**MANGA_PAYLOAD, "relationships": []}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": "ok", "data": [payload]})

        assert make_source(handler).search("x")[0].cover_url is None

    def test_detail(self):
        result = make_source().detail(MANGA_ID)
        assert result.title == "Crayon Shin-chan"
        assert result.cover_url == f"{mangadex.COVERS_BASE}/{MANGA_ID}/e0e1c1d1.jpg.512.jpg"

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

    def test_subscribe_sets_the_official_cover(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        assert series.cover_url == f"{mangadex.COVERS_BASE}/{MANGA_ID}/e0e1c1d1.jpg.512.jpg"

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

    def test_a_scan_does_not_steal_a_downloaded_chapter(
        self, session: Session, temp_settings: Path
    ):
        """De scanner komt gedownloade hoofdstukken tegen in de downloadmap.
        Die horen bij hun abonnement te blijven, niet in een serie te belanden
        die op de mapnaam is verzonnen."""
        from bookpal.library.scanner import scan_root

        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        book = session.query(Book).filter_by(series_id=series.id).first()
        assert book is not None
        source_service.download_book(session, make_source(), book)
        original_title = book.title

        root = source_service.download_root(session)
        scan_root(session, root, force=True)
        session.flush()

        assert book.series_id == series.id
        assert book.title == original_title
        assert book.source_ref is not None
        # Wat de scanner wél mag bijwerken.
        assert book.page_count == 2

    def test_downloads_land_in_the_download_root(self, session: Session, temp_settings: Path):
        source_row = self._source_row(session)
        series, _, _ = source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        book = session.query(Book).filter_by(series_id=series.id).first()
        assert book is not None
        source_service.download_book(session, make_source(), book)

        file_row = session.get(File, book.file_id)
        assert file_row is not None
        assert str(settings.download_dir.resolve()) in file_row.path


class TestPickBestChapters:
    """Dezelfde aflevering kan meerdere keren voorkomen, vertaald door
    verschillende groepen. Nummer, volume en paginatelling zijn dan gelijk."""

    def _chapter(self, ref: str, number: str, group: str, **extra) -> ChapterInfo:
        return ChapterInfo(
            ref=ref,
            number=number,
            volume="1",
            title=f"Deel {number}",
            language="en",
            group_id=group,
            **extra,
        )

    def test_without_duplicates_nothing_changes(self):
        chapters = [
            self._chapter("a", "1", "groep-x"),
            self._chapter("b", "2", "groep-x"),
        ]
        assert source_service.pick_best_chapters(chapters) == chapters

    def test_the_group_that_did_the_most_wins(self):
        """Consistentie: liever één vertaling dan een mengelmoes."""
        chapters = [
            self._chapter("a1", "1", "vlijtig"),
            self._chapter("b1", "1", "eenmalig"),
            self._chapter("a2", "2", "vlijtig"),
            self._chapter("a3", "3", "vlijtig"),
        ]
        gekozen = source_service.pick_best_chapters(chapters)
        assert [c.ref for c in gekozen] == ["a1", "a2", "a3"]

    def test_falls_back_where_the_main_group_has_nothing(self):
        chapters = [
            self._chapter("a1", "1", "vlijtig"),
            self._chapter("a2", "2", "vlijtig"),
            self._chapter("b3", "3", "eenmalig"),
        ]
        gekozen = source_service.pick_best_chapters(chapters)
        assert [c.ref for c in gekozen] == ["a1", "a2", "b3"]

    def test_newest_upload_breaks_a_tie(self):
        chapters = [
            self._chapter("oud", "1", "groep-a", published_at="2020-01-01T00:00:00+00:00"),
            self._chapter("nieuw", "1", "groep-b", published_at="2024-01-01T00:00:00+00:00"),
        ]
        assert [c.ref for c in source_service.pick_best_chapters(chapters)] == ["nieuw"]

    def test_the_choice_is_stable(self):
        """Een tweede ronde mag niet ineens de andere kiezen; dan zou een
        download telkens verspringen."""
        chapters = [
            self._chapter("zzz", "1", "groep-a"),
            self._chapter("aaa", "1", "groep-b"),
        ]
        eerste = source_service.pick_best_chapters(chapters)
        tweede = source_service.pick_best_chapters(list(reversed(chapters)))
        assert [c.ref for c in eerste] == [c.ref for c in tweede]

    def test_a_preferred_group_beats_the_bigger_one(self):
        """"De meeste hoofdstukken" is niet hetzelfde als "de mooiste
        vertaling"; die keuze hoort bij de lezer."""
        chapters = [
            self._chapter("a1", "1", "vlijtig"),
            self._chapter("b1", "1", "mooier"),
            self._chapter("a2", "2", "vlijtig"),
            self._chapter("a3", "3", "vlijtig"),
        ]
        gekozen = source_service.pick_best_chapters(chapters, preferred_group_id="mooier")
        assert [c.ref for c in gekozen] == ["b1", "a2", "a3"]

    def test_the_preference_only_applies_where_that_group_delivered(self):
        chapters = [
            self._chapter("a1", "1", "vlijtig"),
            self._chapter("b1", "1", "mooier"),
            self._chapter("a2", "2", "vlijtig"),
        ]
        gekozen = source_service.pick_best_chapters(chapters, preferred_group_id="mooier")
        # Deel 2 heeft "mooier" niet gedaan; dan blijft de ander staan.
        assert [c.ref for c in gekozen] == ["b1", "a2"]

    def test_an_unknown_preference_falls_back_to_automatic(self):
        chapters = [
            self._chapter("a1", "1", "vlijtig"),
            self._chapter("b1", "1", "eenmalig"),
            self._chapter("a2", "2", "vlijtig"),
        ]
        gekozen = source_service.pick_best_chapters(chapters, preferred_group_id="bestaat-niet")
        assert [c.ref for c in gekozen] == ["a1", "a2"]


class TestGroupSummary:
    def test_lists_groups_with_their_share(self):
        chapters = [
            ChapterInfo(
                ref="a", number="1", volume="1", title=None, language="en",
                group_id="g1", group_name="Vlijtig",
            ),
            ChapterInfo(
                ref="b", number="2", volume="1", title=None, language="en",
                group_id="g1", group_name="Vlijtig",
            ),
            ChapterInfo(
                ref="c", number="1", volume="1", title=None, language="en",
                group_id="g2", group_name="Mooier",
            ),
        ]
        samenvatting = source_service.group_summary(chapters)
        assert samenvatting == [
            {"id": "g1", "name": "Vlijtig", "chapters": 2},
            {"id": "g2", "name": "Mooier", "chapters": 1},
        ]

    def test_chapters_without_a_group_are_skipped(self):
        chapters = [ChapterInfo(ref="a", number="1", volume="1", title=None, language="en")]
        assert source_service.group_summary(chapters) == []


class TestPickBestChaptersMore:
    def _chapter(self, ref: str, number: str, group: str, **extra) -> ChapterInfo:
        return ChapterInfo(
            ref=ref, number=number, volume="1", title=None, language="en", group_id=group, **extra
        )

    def test_volume_is_part_of_the_identity(self):
        """Hoofdstuk 1 van deel 1 is niet hetzelfde als hoofdstuk 1 van deel 2."""
        chapters = [
            ChapterInfo(ref="a", number="1", volume="1", title=None, language="en"),
            ChapterInfo(ref="b", number="1", volume="2", title=None, language="en"),
        ]
        assert len(source_service.pick_best_chapters(chapters)) == 2


class TestSubscriptionPreferenceApi:
    def _subscribed(self, client):
        client.post("/api/sources", json={"type": "mangadex", "name": "MangaDex"})
        return client

    def test_by_series_is_404_without_a_subscription(self, scanned):
        assert scanned.get("/api/sources/subscriptions/by-series/1").status_code == 404

    def test_patching_an_unknown_subscription_is_404(self, client):
        response = client.patch("/api/sources/subscriptions/999", json={"readahead_n": 5})
        assert response.status_code == 404


class TestSyncDeduplication:
    def _series(self, session: Session) -> Series:
        series = Series(title="Reeks", sort_title="reeks")
        session.add(series)
        session.flush()
        return series

    def test_books_sort_by_volume_then_chapter(self, session: Session):
        """Chapter 1 bestaat in elk deel; zonder sort_volume komen die naast
        elkaar te staan in de volgorde waarin de bron ze toevallig teruggaf."""
        series = self._series(session)
        chapters = [
            ChapterInfo(ref="a", number="1", volume="10", title=None, language="en"),
            ChapterInfo(ref="b", number="1", volume="2", title=None, language="en"),
            ChapterInfo(ref="c", number="2", volume="2", title=None, language="en"),
        ]
        source_service.sync_chapters(session, series, chapters)
        volgorde = [(book.volume, book.number) for book in series.books]
        assert volgorde == [("2", "1"), ("2", "2"), ("10", "1")]

    def test_duplicates_never_become_books(self, session: Session):
        series = self._series(session)
        chapters = [
            ChapterInfo(ref="a", number="1", volume="1", title="A", language="en", group_id="x"),
            ChapterInfo(ref="b", number="1", volume="1", title="B", language="en", group_id="y"),
        ]
        added, _ = source_service.sync_chapters(session, series, chapters)
        assert added == 1

    def test_an_earlier_duplicate_is_cleaned_up(self, session: Session):
        series = self._series(session)
        beide = [
            ChapterInfo(ref="a", number="1", volume="1", title="A", language="en", group_id="x"),
            ChapterInfo(ref="b", number="1", volume="1", title="B", language="en", group_id="y"),
        ]
        # Doe alsof een eerdere versie ze allebei had aangemaakt.
        for chapter in beide:
            session.add(
                Book(
                    series_id=series.id,
                    kind=BookKind.COMIC,
                    title=chapter.title or "",
                    number=chapter.number,
                    volume=chapter.volume,
                    source_ref=chapter.ref,
                )
            )
        session.flush()

        source_service.sync_chapters(session, series, beide)
        overgebleven = session.query(Book).filter_by(series_id=series.id).all()
        assert len(overgebleven) == 1

    def test_a_downloaded_duplicate_is_kept(self, session: Session, temp_settings: Path):
        """Opruimen mag nooit iets weghalen wat je al hebt staan."""
        from bookpal.models import LibraryRoot

        series = self._series(session)
        root = LibraryRoot(name="R", path="/tmp/r-dedupe")
        session.add(root)
        session.flush()
        file_row = File(
            library_root_id=root.id, path="/tmp/r-dedupe/a.cbz", size=1, mtime=0.0, extension=".cbz"
        )
        session.add(file_row)
        session.flush()

        verliezer = Book(
            series_id=series.id,
            kind=BookKind.COMIC,
            title="Verliezer",
            number="1",
            volume="1",
            source_ref="verliezer",
            file_id=file_row.id,
        )
        session.add(verliezer)
        session.flush()

        source_service.sync_chapters(
            session,
            series,
            [
                ChapterInfo(
                    ref="winnaar", number="1", volume="1", title="W", language="en", group_id="x"
                )
            ],
        )
        assert session.get(Book, verliezer.id) is not None

    def test_a_duplicate_you_started_reading_is_kept(self, session: Session):
        from bookpal.db import current_user

        series = self._series(session)
        gelezen = Book(
            series_id=series.id,
            kind=BookKind.COMIC,
            title="Gelezen",
            number="1",
            volume="1",
            source_ref="gelezen",
        )
        session.add(gelezen)
        session.flush()
        session.add(
            Progress(user_id=current_user(session).id, book_id=gelezen.id, percent=30.0)
        )
        session.flush()

        source_service.sync_chapters(
            session,
            series,
            [
                ChapterInfo(
                    ref="winnaar", number="1", volume="1", title="W", language="en", group_id="x"
                )
            ],
        )
        assert session.get(Book, gelezen.id) is not None


class TestChapterPath:
    def test_two_translations_of_one_chapter_get_different_paths(self, session: Session):
        """Een bron kan meerdere vertalingen van hetzelfde hoofdstuk hebben.
        Zonder onderscheid claimen die hetzelfde bestand, en Book.file_id is
        uniek — dan loopt de tweede download stuk op de database."""
        from bookpal.models import BookKind, Series

        series = Series(title="Oishinbo", sort_title="oishinbo")
        session.add(series)
        session.flush()

        eerste = Book(
            series_id=series.id,
            kind=BookKind.COMIC,
            title="Tofu & Water",
            volume="1",
            number="1",
            source_ref="aaaaaaaa-1111-2222-3333-444444444444",
        )
        tweede = Book(
            series_id=series.id,
            kind=BookKind.COMIC,
            title="Tofu and Water",
            volume="1",
            number="1",
            source_ref="bbbbbbbb-5555-6666-7777-888888888888",
        )
        session.add_all([eerste, tweede])
        session.flush()

        assert source_service.chapter_path(series, eerste) != source_service.chapter_path(
            series, tweede
        )

    def test_the_path_is_stable_for_the_same_chapter(self, session: Session):
        from bookpal.models import BookKind, Series

        series = Series(title="Reeks", sort_title="reeks")
        session.add(series)
        session.flush()
        book = Book(
            series_id=series.id,
            kind=BookKind.COMIC,
            title="Deel",
            volume="2",
            number="3",
            source_ref="cccccccc-9999-0000-1111-222222222222",
        )
        session.add(book)
        session.flush()
        # Opnieuw ophalen moet op hetzelfde pad uitkomen.
        assert source_service.chapter_path(series, book) == source_service.chapter_path(
            series, book
        )


class TestSafeName:
    def test_strips_characters_that_break_a_filesystem(self):
        assert "/" not in source_service.safe_name("Vol 1/2: test")
        assert ":" not in source_service.safe_name("Vol 1/2: test")

    def test_falls_back_when_nothing_is_left(self):
        assert source_service.safe_name("///") == "zonder-titel"

    def test_shortens_very_long_titles(self):
        assert len(source_service.safe_name("x" * 500)) <= 120


class TestAttachCover:
    """Een lokale serie (zelf gescand) een omslag van een bron geven, zonder
    er een abonnement van te maken."""

    def test_sets_the_cover_on_an_existing_local_series(self, session: Session):
        series = Series(title="Lokaal", sort_title="lokaal")
        session.add(series)
        session.flush()

        source_service.attach_cover(series, make_source(), MANGA_ID)
        assert series.cover_url == f"{mangadex.COVERS_BASE}/{MANGA_ID}/e0e1c1d1.jpg.512.jpg"
        # Blijft lokaal: geen abonnement, geen bron-referentie erbij.
        assert series.source_id is None
        assert series.source_ref is None

    def test_raises_clearly_when_the_bron_has_no_cover(self, session: Session):
        series = Series(title="Lokaal", sort_title="lokaal")
        session.add(series)
        session.flush()
        payload = {**MANGA_PAYLOAD, "relationships": []}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": "ok", "data": payload})

        with pytest.raises(SourceError):
            source_service.attach_cover(series, make_source(handler), MANGA_ID)


class TestSeriesCoverApi:
    def test_attach_cover_persists_on_the_series(
        self, client, session: Session, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("bookpal.api.deps.get_source", lambda _type: make_source())
        source_id = client.post("/api/sources", json={"type": "mangadex", "name": "MD"}).json()[
            "id"
        ]
        series = Series(title="Lokaal", sort_title="lokaal")
        session.add(series)
        session.commit()

        response = client.post(
            f"/api/series/{series.id}/cover", json={"source_id": source_id, "ref": MANGA_ID}
        )
        assert response.status_code == 200
        assert response.json()["has_cover_url"] is True
        assert client.get("/api/sources/types").status_code == 200  # bron blijft werken

    def test_get_cover_is_404_without_one(self, client, session: Session):
        series = Series(title="Zonder omslag", sort_title="zonder omslag")
        session.add(series)
        session.commit()
        assert client.get(f"/api/series/{series.id}/cover").status_code == 404

    def test_get_cover_serves_the_official_image(
        self, client, session: Session, monkeypatch: pytest.MonkeyPatch
    ):
        def fake_get(url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(200, content=_png(), request=httpx.Request("GET", url))

        monkeypatch.setattr("bookpal.images.pipeline.httpx.get", fake_get)

        series = Series(
            title="Met omslag", sort_title="met omslag", cover_url="https://example.test/c.jpg"
        )
        session.add(series)
        session.commit()

        response = client.get(f"/api/series/{series.id}/cover", params={"profile": "thumb"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"


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

    def test_search_includes_the_cover_for_the_picker(
        self, client, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("bookpal.api.deps.get_source", lambda _type: make_source())
        source_id = client.post("/api/sources", json={"type": "mangadex", "name": "MD"}).json()[
            "id"
        ]
        hits = client.get(f"/api/sources/{source_id}/search", params={"q": "x"}).json()
        assert hits[0]["cover_url"] == f"{mangadex.COVERS_BASE}/{MANGA_ID}/e0e1c1d1.jpg.512.jpg"

    def test_download_on_a_local_book_is_refused(self, scanned):
        book_id = scanned.get("/api/books").json()["items"][0]["id"]
        response = scanned.post(f"/api/sources/books/{book_id}/download", json={})
        assert response.status_code == 409
        assert "bron" in response.json()["detail"]

    def test_expire_endpoint_runs(self, client):
        assert client.post("/api/sources/downloads/expire").json() == {"removed": 0}
