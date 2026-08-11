"""Trackers (M7): eenrichtingsverkeer, dus geen conflictafhandeling nodig —
alleen "wat zou er naar buiten gaan" en "gaat dat ook echt uit"."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from bookpal.db import current_user
from bookpal.models import Book, BookKind, File, LibraryRoot, Progress, Series, TrackerAccount
from bookpal.trackers import scheduler
from bookpal.trackers.base import (
    PushResult,
    ReadingStatus,
    Tracker,
    TrackerEntry,
    TrackerError,
)
from bookpal.trackers.goodreads import GoodreadsRow, export_csv
from bookpal.trackers.mal import MyAnimeListTracker, authorize_url, make_code_verifier
from bookpal.trackers.service import (
    entries_for_provider,
    entry_for_series,
    goodreads_rows,
    push_all,
    push_series,
    reading_status_for,
)


def _series(session: Session, *, tracker_ids: dict | None = None, authors=None) -> Series:
    series = Series(
        title="Reeks", sort_title="reeks", tracker_ids=tracker_ids or {}, authors=authors or []
    )
    session.add(series)
    session.flush()
    return series


def _book(session: Session, series: Series, *, file_id: int | None = None) -> Book:
    book = Book(series_id=series.id, kind=BookKind.COMIC, title="Deel", file_id=file_id)
    session.add(book)
    session.flush()
    return book


def _finish(session: Session, book: Book) -> None:
    session.add(
        Progress(user_id=current_user(session).id, book_id=book.id, percent=100.0, finished=True)
    )
    session.flush()


def _partial(session: Session, book: Book) -> None:
    session.add(
        Progress(user_id=current_user(session).id, book_id=book.id, percent=40.0, finished=False)
    )
    session.flush()


class FakeTracker(Tracker):
    provider = "fake"

    def __init__(self, credentials: dict | None = None) -> None:
        self.credentials = credentials or {}
        self.pushed: list[TrackerEntry] = []
        self.fail = False

    def push(self, entry: TrackerEntry, *, dry_run: bool) -> PushResult:
        if self.fail:
            raise TrackerError("kapot")
        if not dry_run:
            self.pushed.append(entry)
        return PushResult(entry=entry, pushed=not dry_run, dry_run=dry_run, detail="")


class TestReadingStatus:
    def test_no_books_is_plan_to_read(self, session: Session):
        series = _series(session)
        assert reading_status_for(session, current_user(session), series) is (
            ReadingStatus.PLAN_TO_READ
        )

    def test_no_progress_is_plan_to_read(self, session: Session):
        series = _series(session)
        _book(session, series, file_id=None)
        assert reading_status_for(session, current_user(session), series) is (
            ReadingStatus.PLAN_TO_READ
        )

    def test_partial_progress_is_reading(self, session: Session):
        series = _series(session)
        book = _book(session, series)
        _partial(session, book)
        assert reading_status_for(session, current_user(session), series) is ReadingStatus.READING

    def test_every_book_with_a_file_finished_is_completed(self, session: Session):
        series = _series(session)
        book = _book(session, series, file_id=None)
        # file_id=None simuleert hier geen bestand; forceer een niet-None id
        # door een echte file-rij te maken in plaats van dat te faken.
        root = LibraryRoot(name="R", path="/tmp/r-tracker")
        session.add(root)
        session.flush()
        file_row = File(
            library_root_id=root.id,
            path="/tmp/r-tracker/a.cbz",
            size=1,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(file_row)
        session.flush()
        book.file_id = file_row.id
        session.flush()

        _finish(session, book)
        assert reading_status_for(session, current_user(session), series) is (
            ReadingStatus.COMPLETED
        )

    def test_one_unfinished_book_keeps_it_reading(self, session: Session):
        series = _series(session)
        root = LibraryRoot(name="R", path="/tmp/r-tracker2")
        session.add(root)
        session.flush()

        finished_book = _book(session, series)
        unfinished_book = _book(session, series)
        for book in (finished_book, unfinished_book):
            file_row = File(
                library_root_id=root.id,
                path=f"/tmp/r-tracker2/{book.id}.cbz",
                size=1,
                mtime=0.0,
                extension=".cbz",
            )
            session.add(file_row)
            session.flush()
            book.file_id = file_row.id
        session.flush()

        _finish(session, finished_book)
        _partial(session, unfinished_book)
        assert reading_status_for(session, current_user(session), series) is ReadingStatus.READING

    def test_a_source_backed_book_without_a_file_is_not_required_to_finish(self, session: Session):
        """Een geabonneerd hoofdstuk dat nog niet is opgehaald mag 'voltooid'
        niet blokkeren — dat zou 'm voor een hele bibliotheek onbereikbaar
        maken zodra er één abonnement bijkomt."""
        series = _series(session)
        root = LibraryRoot(name="R", path="/tmp/r-tracker3")
        session.add(root)
        session.flush()
        finished_book = _book(session, series)
        file_row = File(
            library_root_id=root.id,
            path="/tmp/r-tracker3/a.cbz",
            size=1,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(file_row)
        session.flush()
        finished_book.file_id = file_row.id
        session.flush()
        _finish(session, finished_book)

        _book(session, series, file_id=None)  # nog niet gedownload
        assert reading_status_for(session, current_user(session), series) is (
            ReadingStatus.COMPLETED
        )


class TestEntryForSeries:
    def test_picks_up_the_remote_id(self, session: Session):
        series = _series(session, tracker_ids={"mal": "2435"})
        entry = entry_for_series(session, current_user(session), series, "mal")
        assert entry.remote_id == "2435"

    def test_no_remote_id_when_this_tracker_has_none(self, session: Session):
        series = _series(session, tracker_ids={"anilist": "1"})
        entry = entry_for_series(session, current_user(session), series, "mal")
        assert entry.remote_id is None

    def test_chapters_read_counts_finished_books(self, session: Session):
        series = _series(session)
        root = LibraryRoot(name="R", path="/tmp/r-entry")
        session.add(root)
        session.flush()
        books = [_book(session, series) for _ in range(3)]
        for book in books:
            file_row = File(
                library_root_id=root.id,
                path=f"/tmp/r-entry/{book.id}.cbz",
                size=1,
                mtime=0.0,
                extension=".cbz",
            )
            session.add(file_row)
            session.flush()
            book.file_id = file_row.id
        session.flush()
        _finish(session, books[0])
        _finish(session, books[1])

        entry = entry_for_series(session, current_user(session), series, "mal")
        assert entry.chapters_read == 2


class TestEntriesForProvider:
    def test_only_series_with_this_tracker_id(self, session: Session):
        _series(session, tracker_ids={"mal": "1"})
        _series(session, tracker_ids={"anilist": "2"})
        book = _book(session, _series(session, tracker_ids={"mal": "3"}))
        _partial(session, book)

        entries = entries_for_provider(session, current_user(session), "mal")
        assert {e.remote_id for e in entries} == {"3"}

    def test_skips_untouched_series_by_default(self, session: Session):
        _series(session, tracker_ids={"mal": "1"})  # geen enkele Progress-rij
        entries = entries_for_provider(session, current_user(session), "mal")
        assert entries == []

    def test_include_unread_when_asked(self, session: Session):
        _series(session, tracker_ids={"mal": "1"})
        entries = entries_for_provider(
            session, current_user(session), "mal", only_with_progress=False
        )
        assert len(entries) == 1


class TestPush:
    def test_push_series_returns_none_without_a_remote_id(self, session: Session):
        series = _series(session)
        tracker = FakeTracker()
        account = TrackerAccount(provider="fake", dry_run=True)
        assert push_series(session, tracker, account, current_user(session), series) is None

    def test_push_series_calls_the_tracker(self, session: Session):
        series = _series(session, tracker_ids={"fake": "9"})
        tracker = FakeTracker()
        account = TrackerAccount(provider="fake", dry_run=False)
        result = push_series(session, tracker, account, current_user(session), series)
        assert result is not None
        assert result.pushed is True
        assert len(tracker.pushed) == 1

    def test_dry_run_never_actually_pushes(self, session: Session):
        series = _series(session, tracker_ids={"fake": "9"})
        tracker = FakeTracker()
        account = TrackerAccount(provider="fake", dry_run=True)
        result = push_series(session, tracker, account, current_user(session), series)
        assert result is not None
        assert result.pushed is False
        assert result.dry_run is True
        assert tracker.pushed == []

    def test_push_all_reports_errors_without_stopping(self, session: Session):
        series = _series(session, tracker_ids={"fake": "1"})
        book = _book(session, series)
        _partial(session, book)
        tracker = FakeTracker()
        tracker.fail = True
        account = TrackerAccount(provider="fake", dry_run=False)
        report = push_all(session, tracker, account, current_user(session))
        assert report.errors
        assert report.results == []


class TestGoodreadsExport:
    def test_maps_status_to_shelves(self, session: Session):
        rows = [
            GoodreadsRow(title="Klaar", author="A", status=ReadingStatus.COMPLETED),
            GoodreadsRow(title="Bezig", author=None, status=ReadingStatus.READING),
        ]
        csv_text = export_csv(rows)
        assert "Klaar" in csv_text
        assert "read" in csv_text
        assert "currently-reading" in csv_text

    def test_date_read_only_for_completed(self):
        rows = [
            GoodreadsRow(
                title="X", author=None, status=ReadingStatus.READING, date_read="2024/01/01"
            )
        ]
        csv_text = export_csv(rows)
        assert "2024/01/01" not in csv_text

    def test_goodreads_rows_covers_the_whole_library_including_untouched(self, session: Session):
        _series(session, authors=["Iemand"])  # geen Progress-rij
        rows = list(goodreads_rows(session, current_user(session)))
        assert len(rows) == 1
        assert rows[0].status is ReadingStatus.PLAN_TO_READ
        assert rows[0].author == "Iemand"


class TestMyAnimeListOAuth:
    def test_authorize_url_uses_plain_pkce(self):
        verifier = make_code_verifier()
        url = authorize_url("client-x", verifier)
        assert f"code_challenge={verifier}" in url
        assert "code_challenge_method=plain" in url

    def test_code_verifier_is_within_mal_limits(self):
        verifier = make_code_verifier()
        assert 43 <= len(verifier) <= 128

    def test_exchange_code_updates_credentials(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "tok", "refresh_token": "ref"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        tracker = MyAnimeListTracker({"client_id": "x", "client_secret": "y"}, client=client)
        tracker.exchange_code("code", "verifier")
        assert tracker.credentials["access_token"] == "tok"

    def test_a_rejected_token_request_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "invalid_client"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        tracker = MyAnimeListTracker({}, client=client)
        with pytest.raises(TrackerError):
            tracker.exchange_code("code", "verifier")

    def test_push_without_a_token_raises(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        tracker = MyAnimeListTracker({}, client=client)
        entry = TrackerEntry(
            series_id=1, title="X", remote_id="2435", status=ReadingStatus.READING
        )
        with pytest.raises(TrackerError):
            tracker.push(entry, dry_run=False)

    def test_dry_run_describes_without_a_token(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        tracker = MyAnimeListTracker({}, client=client)
        entry = TrackerEntry(
            series_id=1, title="X", remote_id="2435", status=ReadingStatus.READING, chapters_read=5
        )
        result = tracker.push(entry, dry_run=True)
        assert result.dry_run is True
        # veldnaam is num_chapters_read, niet chapters_read
        assert "num_chapters_read=5" in result.detail

    def test_push_without_a_remote_id_is_skipped_not_an_error(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        tracker = MyAnimeListTracker({"access_token": "tok"}, client=client)
        entry = TrackerEntry(series_id=1, title="X", remote_id=None, status=ReadingStatus.READING)
        result = tracker.push(entry, dry_run=False)
        assert result.pushed is False

    def test_a_successful_push(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PATCH"
            return httpx.Response(200, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        tracker = MyAnimeListTracker({"access_token": "tok"}, client=client)
        entry = TrackerEntry(series_id=1, title="X", remote_id="2435", status=ReadingStatus.READING)
        result = tracker.push(entry, dry_run=False)
        assert result.pushed is True

    def test_an_expired_token_is_reported_clearly(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
        tracker = MyAnimeListTracker({"access_token": "verlopen"}, client=client)
        entry = TrackerEntry(series_id=1, title="X", remote_id="2435", status=ReadingStatus.READING)
        with pytest.raises(TrackerError):
            tracker.push(entry, dry_run=False)


class TestScheduler:
    def test_notify_progress_is_a_no_op_when_disabled(self, temp_settings: Path):
        # temp_settings zet trackers_enabled al op False.
        scheduler.notify_progress(999)
        assert scheduler._timers == {}

    def test_notify_progress_schedules_and_replaces_a_timer(
        self, temp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from bookpal.config import settings as app_settings

        monkeypatch.setattr(app_settings, "trackers_enabled", True)
        monkeypatch.setattr(app_settings, "tracker_debounce_seconds", 60.0)
        try:
            scheduler.notify_progress(1)
            first = scheduler._timers[1]
            scheduler.notify_progress(1)
            second = scheduler._timers[1]
            assert first is not second  # oude timer vervangen, niet gestapeld
            # is_alive() is racy vlak na cancel() (de thread moet nog uit zijn
            # wait() ontwaken); het is_set()-vlaggetje is wat cancel() echt zet.
            assert first.finished.is_set()
        finally:
            scheduler.stop_all()

    def test_push_series_helper_is_targeted_not_library_wide(self, session: Session):
        """De kern van 'gedebounced per serie': _push_series mag alleen de
        aangeroepen serie raken, niet de rest van de bibliotheek."""
        series_a = _series(session, tracker_ids={"fake": "a"})
        series_b = _series(session, tracker_ids={"fake": "b"})
        book_a = _book(session, series_a)
        book_b = _book(session, series_b)
        _partial(session, book_a)
        _partial(session, book_b)

        tracker = FakeTracker()
        account = TrackerAccount(provider="fake", dry_run=False)
        push_series(session, tracker, account, current_user(session), series_a)
        assert len(tracker.pushed) == 1
        assert tracker.pushed[0].series_id == series_a.id
