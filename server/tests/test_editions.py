"""Eén serie, meerdere uitgaven (kleur, zwart-wit, eigen bestanden)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from bookpal.library.editions import best_progress, slot_of, slots
from bookpal.models import Book, BookKind, Edition, Progress, Series


def _series(session: Session) -> Series:
    series = Series(title="Dragon Ball Super", sort_title="d")
    session.add(series)
    session.flush()
    return series


def _edition(session: Session, series: Series, naam: str, rang: int) -> Edition:
    edition = Edition(series_id=series.id, name=naam, rank=rang)
    session.add(edition)
    session.flush()
    return edition


def _book(
    session: Session,
    series: Series,
    edition: Edition | None,
    nummer: float,
    *,
    titel: str | None = None,
    file_id: int | None = None,
) -> Book:
    book = Book(
        series_id=series.id,
        edition_id=edition.id if edition else None,
        kind=BookKind.COMIC,
        title=titel or f"Hoofdstuk {nummer:g}",
        number=f"{nummer:g}",
        sort_number=nummer,
        page_count=20,
        file_id=file_id,
    )
    session.add(book)
    session.flush()
    return book


class TestSlots:
    def test_the_preferred_edition_wins_where_both_have_a_chapter(self, session: Session):
        series = _series(session)
        kleur = _edition(session, series, "Colored", 0)
        zwartwit = _edition(session, series, "Uncolored", 1)
        _book(session, series, kleur, 1.0, titel="H1 kleur")
        _book(session, series, zwartwit, 1.0, titel="H1 zwart-wit")

        [slot] = slots(list(series.books), list(series.editions))
        assert slot.chosen.title == "H1 kleur"
        assert [book.title for book in slot.alternatives] == ["H1 zwart-wit"]

    def test_a_lesser_edition_fills_the_gap(self, session: Session):
        """Precies het geval van de gekleurde uitgave die achterloopt."""
        series = _series(session)
        kleur = _edition(session, series, "Colored", 0)
        zwartwit = _edition(session, series, "Uncolored", 1)
        for nummer in (1.0, 2.0):
            _book(session, series, kleur, nummer, titel=f"H{nummer:g} kleur")
        for nummer in (1.0, 2.0, 3.0, 4.0):
            _book(session, series, zwartwit, nummer, titel=f"H{nummer:g} zw")

        gekozen = [slot.chosen.title for slot in slots(list(series.books), list(series.editions))]
        assert gekozen == ["H1 kleur", "H2 kleur", "H3 zw", "H4 zw"]

    def test_reordering_the_editions_changes_what_you_read(self, session: Session):
        series = _series(session)
        kleur = _edition(session, series, "Colored", 0)
        zwartwit = _edition(session, series, "Uncolored", 1)
        _book(session, series, kleur, 1.0, titel="H1 kleur")
        _book(session, series, zwartwit, 1.0, titel="H1 zw")

        kleur.rank, zwartwit.rank = 1, 0
        session.flush()

        [slot] = slots(list(series.books), list(series.editions))
        assert slot.chosen.title == "H1 zw"

    def test_a_book_you_already_have_wins_within_one_edition(self, session: Session):
        from bookpal.models import File, LibraryRoot

        series = _series(session)
        root = LibraryRoot(name="R", path="/tmp/r-edities")
        session.add(root)
        session.flush()
        bestand = File(
            library_root_id=root.id,
            path="/tmp/r-edities/1.cbz",
            size=1,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(bestand)
        session.flush()
        uitgave = _edition(session, series, "Bron", 0)
        _book(session, series, uitgave, 1.0, titel="Online")
        _book(session, series, uitgave, 1.0, titel="Op schijf", file_id=bestand.id)

        [slot] = slots(list(series.books), list(series.editions))
        assert slot.chosen.title == "Op schijf"

    def test_books_from_before_editions_existed_come_first(self, session: Session):
        """Een boek zonder uitgave is wat er al stond; dat hoort te winnen."""
        series = _series(session)
        nieuw = _edition(session, series, "Nieuwe bron", 0)
        _book(session, series, None, 1.0, titel="Bestaand")
        _book(session, series, nieuw, 1.0, titel="Van de bron")

        [slot] = slots(list(series.books), list(series.editions))
        assert slot.chosen.title == "Bestaand"


class TestSlotKey:
    def test_the_same_chapter_number_is_the_same_slot(self, session: Session):
        series = _series(session)
        eerste = _book(session, series, None, 5.0, titel="Chapter 5")
        tweede = _book(session, series, None, 5.0, titel="005 - Vertrek")
        assert slot_of(eerste) == slot_of(tweede)

    def test_different_volumes_are_different_slots(self, session: Session):
        series = _series(session)
        eerste = _book(session, series, None, 1.0)
        tweede = _book(session, series, None, 1.0)
        tweede.sort_volume = 2.0
        assert slot_of(eerste) != slot_of(tweede)

    def test_a_book_without_a_number_falls_back_to_its_title(self, session: Session):
        """Monty Don heeft drukken, geen delen."""
        series = _series(session)
        boek = Book(series_id=series.id, kind=BookKind.EPUB, title="Down to Earth")
        andere = Book(series_id=series.id, kind=BookKind.EPUB, title="down to earth!")
        assert slot_of(boek) == slot_of(andere)

    def test_a_hand_set_slot_binds_two_editions_of_one_book(self, session: Session):
        """Twee drukken die anders heten wijs je zelf aan elkaar toe."""
        series = _series(session)
        eerste = Book(series_id=series.id, kind=BookKind.EPUB, title="Down to Earth")
        tweede = Book(
            series_id=series.id, kind=BookKind.EPUB, title="Down to Earth: Gardening Wisdom"
        )
        assert slot_of(eerste) != slot_of(tweede)
        eerste.slot = tweede.slot = "down-to-earth"
        assert slot_of(eerste) == slot_of(tweede)


class TestProgressAcrossEditions:
    def test_reading_it_in_colour_counts_for_the_black_and_white_one(self, session: Session):
        series = _series(session)
        kleur = _edition(session, series, "Colored", 0)
        zwartwit = _edition(session, series, "Uncolored", 1)
        in_kleur = _book(session, series, kleur, 1.0)
        in_zw = _book(session, series, zwartwit, 1.0)
        session.flush()

        voortgang = {
            in_kleur.id: Progress(user_id=1, book_id=in_kleur.id, percent=100.0, finished=True)
        }
        [slot] = slots([in_kleur, in_zw], list(series.editions))
        gevonden = best_progress(slot, voortgang)
        assert gevonden is not None and gevonden.finished

    def test_finished_beats_halfway(self, session: Session):
        series = _series(session)
        kleur = _edition(session, series, "Colored", 0)
        zwartwit = _edition(session, series, "Uncolored", 1)
        in_kleur = _book(session, series, kleur, 1.0)
        in_zw = _book(session, series, zwartwit, 1.0)
        session.flush()

        voortgang = {
            in_kleur.id: Progress(user_id=1, book_id=in_kleur.id, percent=40.0, finished=False),
            in_zw.id: Progress(user_id=1, book_id=in_zw.id, percent=100.0, finished=True),
        }
        [slot] = slots([in_kleur, in_zw], list(series.editions))
        gevonden = best_progress(slot, voortgang)
        assert gevonden is not None and gevonden.finished

    def test_nothing_read_stays_nothing(self, session: Session):
        series = _series(session)
        boek = _book(session, series, None, 1.0)
        [slot] = slots([boek], [])
        assert best_progress(slot, {}) is None


class TestEditionsApi:
    """Het samenvouwen zoals een client het ziet."""

    def _setup(self, session: Session) -> tuple[Series, Edition, Edition]:
        from bookpal.models import File, LibraryRoot

        root = LibraryRoot(name="R", path="/tmp/r-api-edities")
        session.add(root)
        session.flush()
        series = _series(session)
        kleur = _edition(session, series, "Kleur", 0)
        zwartwit = _edition(session, series, "Zwart-wit", 1)

        def bestand(naam: str) -> int:
            row = File(
                library_root_id=root.id,
                path=f"/tmp/r-api-edities/{naam}",
                size=1,
                mtime=0.0,
                extension=".cbz",
            )
            session.add(row)
            session.flush()
            return row.id

        for nummer in (1.0, 2.0):
            _book(
                session,
                series,
                kleur,
                nummer,
                titel=f"H{nummer:g} kleur",
                file_id=bestand(f"k{nummer}.cbz"),
            )
        for nummer in (1.0, 2.0, 3.0):
            _book(
                session,
                series,
                zwartwit,
                nummer,
                titel=f"H{nummer:g} zw",
                file_id=bestand(f"z{nummer}.cbz"),
            )
        session.commit()
        return series, kleur, zwartwit

    def test_the_list_has_one_line_per_chapter(self, client, session: Session):
        series, _kleur, _zw = self._setup(session)
        body = client.get(f"/api/series/{series.id}").json()
        assert [book["title"] for book in body["books"]] == ["H1 kleur", "H2 kleur", "H3 zw"]
        assert body["books"][0]["alternatives"][0]["title"] == "H1 zw"

    def test_you_can_ask_for_everything_loose(self, client, session: Session):
        series, _kleur, _zw = self._setup(session)
        body = client.get(f"/api/series/{series.id}", params={"all_editions": True}).json()
        assert len(body["books"]) == 5

    def test_the_editions_show_what_they_contribute(self, client, session: Session):
        series, kleur, _zw = self._setup(session)
        body = client.get(f"/api/series/{series.id}").json()
        per_naam = {edition["name"]: edition for edition in body["editions"]}
        assert per_naam["Kleur"]["book_count"] == 2
        assert per_naam["Kleur"]["chosen_count"] == 2
        assert per_naam["Zwart-wit"]["book_count"] == 3
        assert per_naam["Zwart-wit"]["chosen_count"] == 1
        assert kleur.rank == 0

    def test_reordering_switches_which_edition_you_read(self, client, session: Session):
        series, kleur, zwartwit = self._setup(session)
        response = client.post(
            f"/api/series/{series.id}/editions/order",
            json={"edition_ids": [zwartwit.id, kleur.id]},
        )
        assert response.status_code == 200

        body = client.get(f"/api/series/{series.id}").json()
        assert [book["title"] for book in body["books"]] == ["H1 zw", "H2 zw", "H3 zw"]

    def test_an_edition_from_another_series_is_refused(self, client, session: Session):
        series, kleur, _zw = self._setup(session)
        andere = _series(session)
        andere.title = "Iets anders"
        session.flush()
        vreemd = _edition(session, andere, "Vreemd", 0)
        session.commit()

        response = client.post(
            f"/api/series/{series.id}/editions/order",
            json={"edition_ids": [vreemd.id, kleur.id]},
        )
        assert response.status_code == 400

    def test_renaming_sticks(self, client, session: Session):
        series, kleur, _zw = self._setup(session)
        response = client.patch(
            f"/api/series/{series.id}/editions/{kleur.id}",
            json={"name": "Official Colored", "note": "kleur"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Official Colored"
        assert response.json()["note"] == "kleur"

    def test_binding_two_books_makes_them_one_line(self, client, session: Session):
        """Monty Don: drie drukken van hetzelfde boek."""
        series = _series(session)
        eerste = Book(series_id=series.id, kind=BookKind.EPUB, title="Down to Earth")
        tweede = Book(series_id=series.id, kind=BookKind.EPUB, title="Down to Earth (2017)")
        session.add_all([eerste, tweede])
        session.commit()

        voor = client.get(f"/api/series/{series.id}").json()
        assert len(voor["books"]) == 2

        response = client.post(
            f"/api/series/{series.id}/slots", json={"book_ids": [eerste.id, tweede.id]}
        )
        assert response.status_code == 200
        assert len(response.json()["books"]) == 1

        na = client.post(
            f"/api/series/{series.id}/slots/unbind", json={"book_ids": [eerste.id, tweede.id]}
        ).json()
        assert len(na["books"]) == 2

    def test_binding_one_book_is_pointless_and_refused(self, client, session: Session):
        series = _series(session)
        boek = Book(series_id=series.id, kind=BookKind.EPUB, title="Alleen")
        session.add(boek)
        session.commit()

        response = client.post(f"/api/series/{series.id}/slots", json={"book_ids": [boek.id]})
        assert response.status_code == 400

    def test_books_from_another_series_cannot_be_bound(self, client, session: Session):
        series = _series(session)
        andere = _series(session)
        andere.title = "Iets anders"
        eerste = Book(series_id=series.id, kind=BookKind.EPUB, title="A")
        tweede = Book(series_id=andere.id, kind=BookKind.EPUB, title="B")
        session.add_all([eerste, tweede])
        session.commit()

        response = client.post(
            f"/api/series/{series.id}/slots", json={"book_ids": [eerste.id, tweede.id]}
        )
        assert response.status_code == 400
