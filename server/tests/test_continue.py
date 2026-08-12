"""Lees verder: waar je in een serie moet uitkomen, en hoe je de rommel
ervóór opruimt."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bookpal.db import current_user
from bookpal.models import Book, BookKind, File, LibraryRoot, Progress, Series


def _series_with_chapters(session: Session, count: int, *, naam: str = "Reeks") -> Series:
    # Eigen pad per serie: library_root.path is uniek, dus twee series in één
    # test botsen anders op elkaar.
    root = LibraryRoot(name=naam, path=f"/tmp/r-continue-{naam}")
    session.add(root)
    session.flush()
    series = Series(title=naam, sort_title=naam.lower())
    session.add(series)
    session.flush()
    for index in range(count):
        file_row = File(
            library_root_id=root.id,
            path=f"/tmp/r-continue-{naam}/{index}.cbz",
            size=1,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(file_row)
        session.flush()
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title=f"Deel {index + 1}",
                number=str(index + 1),
                sort_number=float(index + 1),
                page_count=20,
                file_id=file_row.id,
            )
        )
    session.flush()
    return series


def _books(session: Session, series: Series) -> list[Book]:
    return sorted(series.books, key=lambda b: (b.sort_volume, b.sort_number))


def _progress(session: Session, book: Book, percent: float, finished: bool, page: int = 0) -> None:
    session.add(
        Progress(
            user_id=current_user(session).id,
            book_id=book.id,
            percent=percent,
            finished=finished,
            position={"page": page},
        )
    )
    session.flush()


class TestContinue:
    def test_an_untouched_series_starts_at_the_first_chapter(
        self, client: TestClient, session: Session
    ):
        series = _series_with_chapters(session, 3)
        session.commit()

        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["book_id"] == _books(session, series)[0].id
        assert body["page"] == 0
        assert body["resuming"] is False

    def test_a_half_read_chapter_resumes_on_its_page(self, client: TestClient, session: Session):
        series = _series_with_chapters(session, 3)
        books = _books(session, series)
        _progress(session, books[0], 100.0, True)
        _progress(session, books[1], 40.0, False, page=7)
        session.commit()

        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["book_id"] == books[1].id
        assert body["page"] == 7
        assert body["resuming"] is True

    def test_after_finishing_one_it_moves_to_the_next(self, client: TestClient, session: Session):
        series = _series_with_chapters(session, 3)
        books = _books(session, series)
        _progress(session, books[0], 100.0, True)
        session.commit()

        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["book_id"] == books[1].id
        assert body["page"] == 0
        assert body["resuming"] is False

    def test_an_old_chapter_you_reopened_does_not_pull_you_back(
        self, client: TestClient, session: Session
    ):
        """Bij manga lees je vooruit: een teruggekeken hoofdstuk 1 hoort je niet
        van hoofdstuk 3 weg te trekken. Daarom leesvolgorde, niet 'laatst
        gelezen'."""
        series = _series_with_chapters(session, 3)
        books = _books(session, series)
        for book in books[:2]:
            _progress(session, book, 100.0, True)
        _progress(session, books[2], 30.0, False, page=5)
        session.commit()

        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["book_id"] == books[2].id

    def test_an_old_half_open_chapter_does_not_trap_you(self, client: TestClient, session: Session):
        """Het geval uit de praktijk: 7% op een hoofdstuk uit deel 1 dat ooit
        even openging, terwijl je allang in deel 3 zit. Dat oude restje hoorde
        je niet terug te trekken."""
        series = _series_with_chapters(session, 6)
        books = _books(session, series)
        _progress(session, books[0], 7.0, False, page=1)  # ooit even opengeslagen
        _progress(session, books[3], 89.0, False, page=18)  # waar je echt bent
        session.commit()

        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["book_id"] == books[3].id
        assert body["page"] == 18
        # En het oude restje is precies wat de opruimknop aanbiedt.
        assert body["unread_before"] == 3

    def test_after_finishing_the_furthest_it_goes_to_the_next(
        self, client: TestClient, session: Session
    ):
        series = _series_with_chapters(session, 5)
        books = _books(session, series)
        _progress(session, books[0], 7.0, False, page=1)
        _progress(session, books[2], 100.0, True)
        session.commit()

        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["book_id"] == books[3].id
        assert body["resuming"] is False

    def test_everything_read_falls_back_to_the_last_chapter(
        self, client: TestClient, session: Session
    ):
        """De knop hoort iets te doen in plaats van te verdwijnen."""
        series = _series_with_chapters(session, 2)
        for book in _books(session, series):
            _progress(session, book, 100.0, True)
        session.commit()

        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["book_id"] == _books(session, series)[-1].id

    def test_a_chapter_that_still_needs_fetching_says_so(
        self, client: TestClient, session: Session
    ):
        """Wat nog niet binnen is mag je wél aanwijzen, maar niet openen.

        Bij een serie die je online volgt is dat de normale situatie: je bent
        bij hoofdstuk 124 en 125 staat nog niet op de NAS. Het overslaan van
        zulke hoofdstukken zette je terug op het laatste bestand dat je
        toevallig had staan. ``has_file`` maakt er een ophaalknop van in plaats
        van een lege pagina.
        """
        series = _series_with_chapters(session, 1)
        readable = _books(session, series)[0]
        # Sorteert vóór het leesbare hoofdstuk, dus dit is precies het geval
        # waarin "gewoon de eerste pakken" fout zou gaan.
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title="Nog niet opgehaald",
                number="0",
                sort_number=0.0,
                page_count=None,
                file_id=None,
            )
        )
        session.commit()

        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["number"] == "0"
        assert body["has_file"] is False
        assert readable.file_id is not None

    def test_it_counts_what_is_still_unread_before_it(self, client: TestClient, session: Session):
        series = _series_with_chapters(session, 4)
        books = _books(session, series)
        _progress(session, books[0], 100.0, True)
        _progress(session, books[2], 20.0, False, page=3)
        session.commit()

        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["book_id"] == books[2].id
        assert body["unread_before"] == 1  # deel 2 staat nog open, deel 1 is uit

    def test_a_series_without_readable_chapters_is_a_404(
        self, client: TestClient, session: Session
    ):
        series = Series(title="Leeg", sort_title="leeg")
        session.add(series)
        session.commit()
        assert client.get(f"/api/series/{series.id}/continue").status_code == 404


class TestMarkReadBefore:
    def test_it_marks_everything_before_and_not_the_target(
        self, client: TestClient, session: Session
    ):
        series = _series_with_chapters(session, 4)
        books = _books(session, series)
        session.commit()

        body = client.post(f"/api/series/{series.id}/mark-read-before/{books[2].id}").json()
        assert body["marked"] == 2

        after = client.get(f"/api/series/{series.id}").json()["books"]
        by_id = {item["id"]: item for item in after}
        assert by_id[books[0].id]["progress"]["finished"] is True
        assert by_id[books[1].id]["progress"]["finished"] is True
        # Het hoofdstuk zelf blijft ongemoeid: daar ga je juist lezen.
        assert by_id[books[2].id]["progress"] is None

    def test_already_finished_chapters_are_not_counted_again(
        self, client: TestClient, session: Session
    ):
        series = _series_with_chapters(session, 3)
        books = _books(session, series)
        _progress(session, books[0], 100.0, True)
        session.commit()

        body = client.post(f"/api/series/{series.id}/mark-read-before/{books[2].id}").json()
        assert body["marked"] == 1

    def test_marking_before_the_first_chapter_does_nothing(
        self, client: TestClient, session: Session
    ):
        series = _series_with_chapters(session, 3)
        books = _books(session, series)
        session.commit()

        body = client.post(f"/api/series/{series.id}/mark-read-before/{books[0].id}").json()
        assert body["marked"] == 0

    def test_a_chapter_from_another_series_is_refused(self, client: TestClient, session: Session):
        first = _series_with_chapters(session, 2, naam="Eerste")
        second = _series_with_chapters(session, 2, naam="Tweede")
        session.commit()

        other = _books(session, second)[0]
        response = client.post(f"/api/series/{first.id}/mark-read-before/{other.id}")
        assert response.status_code == 400

    def test_continue_moves_on_after_marking(self, client: TestClient, session: Session):
        """De twee knoppen horen samen te werken: eerst opruimen, dan verder."""
        series = _series_with_chapters(session, 4)
        books = _books(session, series)
        session.commit()

        client.post(f"/api/series/{series.id}/mark-read-before/{books[2].id}")
        body = client.get(f"/api/series/{series.id}/continue").json()
        assert body["book_id"] == books[2].id
        assert body["unread_before"] == 0


class TestNextChapter:
    def test_it_gives_the_following_chapter(self, client: TestClient, session: Session):
        series = _series_with_chapters(session, 3, naam="Volgende")
        books = _books(session, series)
        session.commit()

        body = client.get(f"/api/books/{books[0].id}/next").json()
        assert body["book_id"] == books[1].id
        assert body["has_file"] is True

    def test_the_last_chapter_has_no_next(self, client: TestClient, session: Session):
        series = _series_with_chapters(session, 2, naam="Laatste")
        books = _books(session, series)
        session.commit()

        assert client.get(f"/api/books/{books[-1].id}/next").status_code == 404

    def test_a_chapter_still_to_download_is_offered_too(self, client: TestClient, session: Session):
        """Juist als je er een uit hebt wil je weten dat het volgende bestaat,
        ook al staat het nog niet op schijf."""
        series = _series_with_chapters(session, 1, naam="Ophalen")
        books = _books(session, series)
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title="Nog op te halen",
                number="2",
                sort_number=2.0,
                file_id=None,
                source_ref="abc",
            )
        )
        session.commit()

        body = client.get(f"/api/books/{books[0].id}/next").json()
        assert body["title"] == "Nog op te halen"
        assert body["has_file"] is False


class TestOpeningIsNotReading:
    """Een hoofdstuk aanklikken en meteen wegklikken is geen voortgang."""

    def test_the_first_page_does_not_create_progress(self, client: TestClient, session: Session):
        series = _series_with_chapters(session, 2)
        session.commit()
        boek = _books(session, series)[0]

        response = client.put(
            "/api/progress",
            json={"book_id": boek.id, "position": {"page": 0}, "percent": 0.0, "device": "web"},
        )
        assert response.status_code == 200

        session.expire_all()
        assert session.query(Progress).count() == 0

    def test_turning_one_page_does_create_progress(self, client: TestClient, session: Session):
        series = _series_with_chapters(session, 2)
        session.commit()
        boek = _books(session, series)[0]

        client.put(
            "/api/progress",
            json={"book_id": boek.id, "position": {"page": 1}, "percent": 5.0, "device": "web"},
        )

        session.expire_all()
        assert session.query(Progress).count() == 1

    def test_going_back_to_page_one_keeps_what_you_had(self, client: TestClient, session: Session):
        """Terugbladeren in een boek waar je al in zat is wél nieuws."""
        series = _series_with_chapters(session, 2)
        session.commit()
        boek = _books(session, series)[0]
        _progress(session, boek, 60.0, False, page=12)
        session.commit()

        client.put(
            "/api/progress",
            json={"book_id": boek.id, "position": {"page": 0}, "percent": 0.0, "device": "web"},
        )

        session.expire_all()
        row = session.query(Progress).one()
        assert row.position == {"page": 0}

    def test_an_opened_chapter_is_not_where_you_continue(
        self, client: TestClient, session: Session
    ):
        """Zonder deze regel wees verder-lezen naar het even opengeslagen deel."""
        series = _series_with_chapters(session, 3)
        session.commit()
        boeken = _books(session, series)
        _progress(session, boeken[0], 100.0, True, page=19)
        session.commit()

        client.put(
            "/api/progress",
            json={
                "book_id": boeken[2].id,
                "position": {"page": 0},
                "percent": 0.0,
                "device": "web",
            },
        )

        verder = client.get(f"/api/series/{series.id}/continue").json()
        assert verder["book_id"] == boeken[1].id
        assert verder["resuming"] is False
