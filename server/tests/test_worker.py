"""De abonnementen-worker (M5).

Het zwaartepunt ligt op ``plan_readahead``: dat is de enige plek met echte
beslissingen, en hij is zonder netwerk te testen.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from bookpal.db import current_user
from bookpal.models import (
    Book,
    BookKind,
    Progress,
    Series,
    Source,
    Subscription,
    SubscriptionPolicy,
)
from bookpal.sources import worker
from tests.test_sources import MANGA_ID, make_source


def _series_with_chapters(session: Session, count: int, *, with_files: int = 0) -> Series:
    series = Series(title="Reeks", sort_title="reeks")
    session.add(series)
    session.flush()
    for index in range(count):
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title=f"Hoofdstuk {index + 1}",
                number=str(index + 1),
                sort_number=float(index + 1),
                source_ref=f"ref-{index + 1}",
                # De eerste `with_files` doen alsof ze al binnen zijn.
                file_id=None,
            )
        )
    session.flush()
    return series


def _subscription(session: Session, series: Series, *, readahead_n: int = 3) -> Subscription:
    source = Source(type="mangadex", name="MangaDex")
    session.add(source)
    session.flush()
    subscription = Subscription(
        source_id=source.id,
        series_id=series.id,
        policy=SubscriptionPolicy.READAHEAD,
        readahead_n=readahead_n,
    )
    session.add(subscription)
    session.flush()
    return subscription


def _finish(session: Session, book: Book) -> None:
    session.add(
        Progress(
            user_id=current_user(session).id,
            book_id=book.id,
            percent=100.0,
            finished=True,
        )
    )
    session.flush()


class TestPlanReadahead:
    def test_takes_the_first_n_when_nothing_is_read(self, session: Session):
        series = _series_with_chapters(session, 10)
        subscription = _subscription(session, series, readahead_n=3)

        planned = worker.plan_readahead(session, subscription, current_user(session))
        assert [book.number for book in planned] == ["1", "2", "3"]

    def test_starts_after_what_you_finished(self, session: Session):
        series = _series_with_chapters(session, 10)
        subscription = _subscription(session, series, readahead_n=2)
        books = session.query(Book).order_by(Book.sort_number).all()
        _finish(session, books[0])
        _finish(session, books[1])

        planned = worker.plan_readahead(session, subscription, current_user(session))
        assert [book.number for book in planned] == ["3", "4"]

    def test_skips_chapters_that_are_already_local(self, session: Session):
        from bookpal.models import File, LibraryRoot

        series = _series_with_chapters(session, 5)
        subscription = _subscription(session, series, readahead_n=3)
        root = LibraryRoot(name="R", path="/tmp/r-plan")
        session.add(root)
        session.flush()

        books = session.query(Book).order_by(Book.sort_number).all()
        file_row = File(
            library_root_id=root.id, path="/tmp/r-plan/1.cbz", size=1, mtime=0.0, extension=".cbz"
        )
        session.add(file_row)
        session.flush()
        books[0].file_id = file_row.id
        session.flush()

        planned = worker.plan_readahead(session, subscription, current_user(session))
        assert [book.number for book in planned] == ["2", "3", "4"]

    def test_nothing_to_do_when_everything_is_finished(self, session: Session):
        series = _series_with_chapters(session, 3)
        subscription = _subscription(session, series)
        for book in session.query(Book).all():
            _finish(session, book)

        assert worker.plan_readahead(session, subscription, current_user(session)) == []

    def test_readahead_zero_downloads_nothing(self, session: Session):
        series = _series_with_chapters(session, 5)
        subscription = _subscription(session, series, readahead_n=0)
        assert worker.plan_readahead(session, subscription, current_user(session)) == []

    def test_a_gap_in_the_middle_is_filled(self, session: Session):
        """Deel 1 uit, deel 2 nog niet: dan begint vooruitlezen bij 2."""
        series = _series_with_chapters(session, 6)
        subscription = _subscription(session, series, readahead_n=2)
        books = session.query(Book).order_by(Book.sort_number).all()
        _finish(session, books[0])
        _finish(session, books[2])  # deel 3 ook al uit, maar 2 niet

        planned = worker.plan_readahead(session, subscription, current_user(session))
        assert [book.number for book in planned] == ["2", "3"]

    def test_books_without_a_source_ref_are_ignored(self, session: Session):
        series = _series_with_chapters(session, 3)
        subscription = _subscription(session, series, readahead_n=3)
        book = session.query(Book).order_by(Book.sort_number).first()
        assert book is not None
        book.source_ref = None
        session.flush()

        planned = worker.plan_readahead(session, subscription, current_user(session))
        assert [b.number for b in planned] == ["2", "3"]

    def test_empty_series(self, session: Session):
        series = Series(title="Leeg", sort_title="leeg")
        session.add(series)
        session.flush()
        subscription = _subscription(session, series)
        assert worker.plan_readahead(session, subscription, current_user(session)) == []


class TestRunOnce:
    def test_without_subscriptions_it_does_nothing(self, session: Session):
        report = worker.run_once(session)
        assert report.subscriptions == 0
        assert report.downloaded == 0

    def test_refresh_and_download(self, session: Session, temp_settings: Path, monkeypatch):
        """Volledige ronde tegen de nagebootste bron."""
        monkeypatch.setattr(worker, "get_source", lambda _type: make_source())

        source_row = Source(type="mangadex", name="MangaDex")
        session.add(source_row)
        session.flush()
        from bookpal.sources import service as source_service

        _, subscription, _ = source_service.subscribe(
            session, source_row, make_source(), MANGA_ID
        )
        subscription.readahead_n = 1
        session.commit()

        report = worker.run_once(session)
        assert report.subscriptions == 1
        assert report.downloaded == 1

        local = session.query(Book).filter(Book.file_id.isnot(None)).count()
        assert local == 1

    def test_download_false_only_refreshes(
        self, session: Session, temp_settings: Path, monkeypatch
    ):
        monkeypatch.setattr(worker, "get_source", lambda _type: make_source())

        source_row = Source(type="mangadex", name="MangaDex")
        session.add(source_row)
        session.flush()
        from bookpal.sources import service as source_service

        source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        session.commit()

        report = worker.run_once(session, download=False)
        assert report.downloaded == 0
        assert session.query(Book).filter(Book.file_id.isnot(None)).count() == 0

    def test_refresh_backfills_series_metadata(
        self, session: Session, temp_settings: Path, monkeypatch
    ):
        """Metadata die pas later bij de bron goed komt te staan — auteur,
        omslag, tracker-ids — moet een ronde later alsnog binnenkomen."""
        monkeypatch.setattr(worker, "get_source", lambda _type: make_source())
        source_row = Source(type="mangadex", name="MangaDex")
        session.add(source_row)
        session.flush()
        from bookpal.sources import service as source_service

        series, _subscription, _added = source_service.subscribe(
            session, source_row, make_source(), MANGA_ID
        )
        series.authors = []  # alsof je de serie volgde toen de bron dit nog niet wist
        session.commit()

        worker.run_once(session, download=False)
        session.refresh(series)
        assert series.authors == ["Yoshito Usui"]

    def test_a_broken_source_is_reported_not_raised(
        self, session: Session, temp_settings: Path, monkeypatch
    ):
        """Eén hikkende bron mag de ronde niet laten klappen."""
        from bookpal.sources.base import SourceError

        source_row = Source(type="mangadex", name="MangaDex")
        session.add(source_row)
        session.flush()
        from bookpal.sources import service as source_service

        source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        # Committen zoals de API doet: run_once krijgt altijd een schone
        # sessie, en zijn rollback mag alleen de mislukte stap terugdraaien.
        session.commit()

        class Kapot:
            def detail(self, *args, **kwargs):
                raise SourceError("bron plat")

            def chapters(self, *args, **kwargs):
                raise SourceError("bron plat")

            def download(self, *args, **kwargs):
                raise SourceError("bron plat")

        monkeypatch.setattr(worker, "get_source", lambda _type: Kapot())
        report = worker.run_once(session)
        assert report.errors
        assert report.downloaded == 0

    def test_a_disabled_source_is_skipped(self, session: Session, temp_settings: Path, monkeypatch):
        monkeypatch.setattr(worker, "get_source", lambda _type: make_source())
        source_row = Source(type="mangadex", name="MangaDex")
        session.add(source_row)
        session.flush()
        from bookpal.sources import service as source_service

        source_service.subscribe(session, source_row, make_source(), MANGA_ID)
        source_row.enabled = False
        session.commit()

        report = worker.run_once(session)
        assert report.downloaded == 0


class TestWorkerLifecycle:
    def test_start_is_idempotent_and_stop_cleans_up(self):
        instance = worker.SubscriptionWorker(interval_seconds=3600)
        instance.start()
        first = instance._thread
        instance.start()
        assert instance._thread is first
        instance.stop()
        assert instance._thread is None

    def test_disabled_in_settings_means_no_thread(self, temp_settings: Path):
        # De fixture zet subscriptions_enabled op False.
        assert worker.start_worker() is None


class TestRunEndpoint:
    def test_run_endpoint_reports(self, client):
        body = client.post("/api/sources/run").json()
        assert body["subscriptions"] == 0
        assert body["errors"] == []
