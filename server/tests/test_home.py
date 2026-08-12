"""De startpagina: waar je was, en wat er nieuw is.

Wat hier vooral vastligt is de begrenzing. Eén serie waarin je vlot leest mag
een rij niet vullen, en een deel dat je halverwege hebt hoort niet óók nog eens
in "het volgende deel" te staan.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bookpal.db import current_user
from bookpal.models import Book, BookKind, File, LibraryRoot, Progress, Series


def _reeks(session: Session, naam: str, aantal: int) -> Series:
    root = LibraryRoot(name=naam, path=f"/tmp/home-{naam}")
    session.add(root)
    session.flush()
    series = Series(title=naam, sort_title=naam.lower())
    session.add(series)
    session.flush()
    for index in range(aantal):
        bestand = File(
            library_root_id=root.id,
            path=f"/tmp/home-{naam}/{index}.cbz",
            size=1,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(bestand)
        session.flush()
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title=f"Hoofdstuk {index + 1}",
                number=str(index + 1),
                sort_number=float(index + 1),
                page_count=20,
                file_id=bestand.id,
            )
        )
    session.flush()
    return series


def _boeken(series: Series) -> list[Book]:
    return sorted(series.books, key=lambda b: b.sort_number)


def _lezen(session: Session, boek: Book, percent: float, finished: bool = False) -> None:
    session.add(
        Progress(
            user_id=current_user(session).id,
            book_id=boek.id,
            percent=percent,
            finished=finished,
            position={"page": int(20 * percent / 100)},
        )
    )
    session.flush()


def _rail(body: dict, key: str) -> list[dict]:
    for rail in body["rails"]:
        if rail["key"] == key:
            return rail["items"]
    return []


class TestContinueRail:
    def test_what_you_started_shows_up_with_its_progress(
        self, client: TestClient, session: Session
    ):
        series = _reeks(session, "Reeks", 3)
        _lezen(session, _boeken(series)[1], 45.0)
        session.commit()

        [item] = _rail(client.get("/api/home").json(), "verder")
        assert item["title"] == "Hoofdstuk 2"
        assert item["percent"] == 45.0
        assert item["page"] == 9
        assert item["series_title"] == "Reeks"

    def test_one_series_does_not_fill_the_rail(self, client: TestClient, session: Session):
        """Anders zie je juist niet meer wat er verder openstaat."""
        eerste = _reeks(session, "Veel", 5)
        tweede = _reeks(session, "Ander", 2)
        for boek in _boeken(eerste)[:4]:
            _lezen(session, boek, 30.0)
        _lezen(session, _boeken(tweede)[0], 10.0)
        session.commit()

        items = _rail(client.get("/api/home").json(), "verder")
        assert len(items) == 2
        assert {item["series_title"] for item in items} == {"Veel", "Ander"}

    def test_a_finished_chapter_is_not_something_to_continue(
        self, client: TestClient, session: Session
    ):
        series = _reeks(session, "Reeks", 2)
        _lezen(session, _boeken(series)[0], 100.0, finished=True)
        session.commit()

        assert _rail(client.get("/api/home").json(), "verder") == []


class TestNextUpRail:
    def test_the_chapter_after_what_you_finished(self, client: TestClient, session: Session):
        series = _reeks(session, "Reeks", 3)
        _lezen(session, _boeken(series)[0], 100.0, finished=True)
        session.commit()

        [item] = _rail(client.get("/api/home").json(), "volgende")
        assert item["title"] == "Hoofdstuk 2"
        assert item["percent"] == 0.0

    def test_a_series_you_are_halfway_through_is_not_repeated(
        self, client: TestClient, session: Session
    ):
        """Die staat al bij "verder lezen"; twee keer is verwarrend."""
        series = _reeks(session, "Reeks", 3)
        boeken = _boeken(series)
        _lezen(session, boeken[0], 100.0, finished=True)
        _lezen(session, boeken[1], 30.0)
        session.commit()

        body = client.get("/api/home").json()
        assert [item["title"] for item in _rail(body, "verder")] == ["Hoofdstuk 2"]
        assert _rail(body, "volgende") == []

    def test_a_series_you_never_touched_is_not_next_up(self, client: TestClient, session: Session):
        _reeks(session, "Onbegonnen", 3)
        session.commit()
        assert _rail(client.get("/api/home").json(), "volgende") == []

    def test_a_series_you_finished_offers_nothing(self, client: TestClient, session: Session):
        series = _reeks(session, "Uit", 2)
        for boek in _boeken(series):
            _lezen(session, boek, 100.0, finished=True)
        session.commit()

        assert _rail(client.get("/api/home").json(), "volgende") == []


class TestRecentRail:
    def test_new_books_show_up(self, client: TestClient, session: Session):
        _reeks(session, "Nieuw", 2)
        session.commit()

        items = _rail(client.get("/api/home").json(), "nieuw")
        assert len(items) == 1, "per serie één"
        assert items[0]["series_title"] == "Nieuw"

    def test_a_chapter_without_a_file_is_not_offered(self, client: TestClient, session: Session):
        """Een tegel die je niet kunt openen hoort niet op de startpagina."""
        series = _reeks(session, "Reeks", 1)
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title="Nog niet opgehaald",
                number="2",
                sort_number=2.0,
            )
        )
        session.commit()

        items = _rail(client.get("/api/home").json(), "nieuw")
        assert [item["title"] for item in items] == ["Hoofdstuk 1"]


class TestEmptyLibrary:
    def test_no_rails_when_there_is_nothing(self, client: TestClient):
        assert client.get("/api/home").json()["rails"] == []


class TestWhatCountsAsNews:
    def test_a_new_chapter_of_what_you_read_comes_first(self, client: TestClient, session: Session):
        """Een abonnement levert elke ronde delen; die mogen je lijst niet vullen."""
        vreemd = _reeks(session, "Nooit gelezen", 1)
        eigen = _reeks(session, "Jouw reeks", 2)
        _lezen(session, _boeken(eigen)[0], 40.0)
        # De vreemde serie is later toegevoegd en zou anders bovenaan staan.
        for boek in vreemd.books:
            boek.added_at = _boeken(eigen)[0].added_at.replace(year=2030)
        session.commit()

        items = _rail(client.get("/api/home").json(), "nieuw")
        assert items[0]["series_title"] == "Jouw reeks"
