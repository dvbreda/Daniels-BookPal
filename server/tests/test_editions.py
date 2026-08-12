"""Eén serie, meerdere uitgaven (kleur, zwart-wit, eigen bestanden)."""

from __future__ import annotations

from sqlalchemy import select
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


class TestTwoLanguagesOfOneSeries:
    """Van Shinya Shokudo is maar een klein deel vertaald.

    Dan wil je het Engelse voorop en het Japanse origineel eronder, zodat je
    verder kunt lezen waar de vertaling ophoudt — met de vertaalknop erbij.
    """

    def _bron(self, session: Session):
        from bookpal.models import Source

        row = Source(type="mangadex", name="MangaDex")
        session.add(row)
        session.flush()
        return row

    def _nep(self, per_taal: dict[str, list[str]]):
        """Een bron die per taal andere hoofdstukken heeft."""
        import httpx

        from bookpal.sources.mangadex import MangaDexSource
        from tests.test_sources import MANGA_ID, MANGA_PAYLOAD, _chapter

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == f"/manga/{MANGA_ID}":
                return httpx.Response(200, json={"result": "ok", "data": MANGA_PAYLOAD})
            if path == f"/manga/{MANGA_ID}/feed":
                taal = request.url.params.get("translatedLanguage[]", "en")
                nummers = per_taal.get(taal, [])
                return httpx.Response(
                    200,
                    json={
                        "result": "ok",
                        "total": len(nummers),
                        "data": [_chapter(f"{taal}-{nummer}", nummer, "1") for nummer in nummers],
                    },
                )
            return httpx.Response(404, json={"result": "error"})

        return MangaDexSource(
            client=httpx.Client(
                base_url="https://api.test", transport=httpx.MockTransport(handler)
            ),
            rate=1000.0,
            at_home_rate=1000.0,
        )

    def test_both_languages_become_editions_of_one_series(self, session: Session, temp_settings):
        from bookpal.sources import service as source_service
        from tests.test_sources import MANGA_ID

        bron = self._bron(session)
        implementatie = self._nep({"en": ["1", "2"], "ja": ["1", "2", "3", "4"]})

        series, engels, _ = source_service.subscribe(
            session, bron, implementatie, MANGA_ID, language="en"
        )
        zelfde, japans, _ = source_service.subscribe(
            session, bron, implementatie, MANGA_ID, language="ja"
        )

        assert zelfde.id == series.id, "één serie, twee uitgaven"
        assert engels.id != japans.id
        assert {engels.language, japans.language} == {"en", "ja"}

        uitgaven = sorted(series.editions, key=lambda edition: edition.rank)
        # De taal komt er alleen bij als hij nodig is om ze te onderscheiden.
        assert [edition.name for edition in uitgaven] == [
            "Crayon Shin-chan",
            "Crayon Shin-chan · ja",
        ]

    def test_the_untranslated_rest_fills_in_behind_the_translation(
        self, session: Session, temp_settings
    ):
        from bookpal.sources import service as source_service
        from tests.test_sources import MANGA_ID

        bron = self._bron(session)
        implementatie = self._nep({"en": ["1", "2"], "ja": ["1", "2", "3", "4"]})
        series, _, _ = source_service.subscribe(
            session, bron, implementatie, MANGA_ID, language="en"
        )
        source_service.subscribe(session, bron, implementatie, MANGA_ID, language="ja")
        session.flush()

        gekozen = slots(list(series.books), list(series.editions))
        namen = {edition.id: edition.name for edition in series.editions}
        assert [(slot.chosen.number, namen[slot.chosen.edition_id]) for slot in gekozen] == [
            ("1", "Crayon Shin-chan"),
            ("2", "Crayon Shin-chan"),
            ("3", "Crayon Shin-chan · ja"),
            ("4", "Crayon Shin-chan · ja"),
        ]

    def test_a_refresh_keeps_each_subscription_in_its_own_language(
        self, session: Session, temp_settings
    ):
        """Zonder de taal op het abonnement haalt de ronde altijd Engels op."""
        from bookpal.models import Subscription
        from bookpal.sources import service as source_service
        from tests.test_sources import MANGA_ID

        bron = self._bron(session)
        implementatie = self._nep({"en": ["1"], "ja": ["1", "2"]})
        source_service.subscribe(session, bron, implementatie, MANGA_ID, language="en")
        source_service.subscribe(session, bron, implementatie, MANGA_ID, language="ja")
        session.flush()

        talen = sorted(row.language for row in session.scalars(select(Subscription)))
        assert talen == ["en", "ja"]


class TestAddingASourceToWhatYouHave:
    """Een bron toevoegen aan een serie die je al hebt, niet een tweede maken."""

    def _bron(self, session: Session):
        from bookpal.models import Source

        row = Source(type="mangadex", name="MangaDex")
        session.add(row)
        session.flush()
        return row

    def _treffer(self, titel: str, ref: str = "abc"):
        from bookpal.sources.base import SearchResult

        return SearchResult(ref=ref, title=titel)

    def test_a_romanisation_variant_lands_on_the_series_you_have(self, session: Session):
        """ "Shinya Shokudou" bij de bron is jouw "Shinya Shokudo"."""
        from bookpal.sources import service as source_service

        eigen = Series(title="Shinya Shokudo", sort_title="s")
        session.add(eigen)
        session.flush()
        bron = self._bron(session)

        gevonden = source_service.upsert_series(session, bron, self._treffer("Shinya Shokudou"))
        assert gevonden.id == eigen.id
        assert session.query(Series).count() == 1

    def test_a_local_series_keeps_its_own_title(self, session: Session):
        from bookpal.sources import service as source_service

        eigen = Series(title="Shinya Shokudo", sort_title="s")
        session.add(eigen)
        session.flush()
        bron = self._bron(session)

        source_service.upsert_series(session, bron, self._treffer("Shinya Shokudou"))
        assert eigen.title == "Shinya Shokudo"
        assert eigen.source_ref == "abc"

    def test_a_different_series_still_becomes_its_own(self, session: Session):
        from bookpal.sources import service as source_service

        session.add(Series(title="Oishinbo", sort_title="o"))
        session.flush()
        bron = self._bron(session)

        gevonden = source_service.upsert_series(session, bron, self._treffer("One Piece"))
        assert gevonden.title == "One Piece"
        assert session.query(Series).count() == 2

    def test_the_search_says_you_would_be_adding_to_an_existing_series(
        self, client, session: Session, monkeypatch
    ):
        from bookpal.sources.base import SearchResult
        from bookpal.sources.mangadex import MangaDexSource

        session.add(Series(title="Shinya Shokudo", sort_title="s"))
        session.commit()
        client.post("/api/sources", json={"type": "mangadex", "name": "MangaDex"})
        monkeypatch.setattr(
            MangaDexSource,
            "search",
            lambda self, query, *, limit=20: [SearchResult(ref="abc", title="Shinya Shokudou")],
        )

        [treffer] = client.get("/api/sources/1/search", params={"q": "shinya"}).json()
        assert treffer["existing_series_title"] == "Shinya Shokudo"
        assert treffer["subscribed_series_id"] is None


class TestRenamingASeries:
    def test_you_can_drop_the_edition_from_the_title(self, client, session: Session):
        """Na het samenvoegen klopt "(Official Colored)" niet meer."""
        series = Series(title="Dragon Ball Super (Official Colored)", sort_title="d")
        session.add(series)
        session.commit()

        response = client.patch(
            f"/api/series/{series.id}/title", json={"title": "Dragon Ball Super"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Dragon Ball Super"

        session.expire_all()
        assert session.get(Series, series.id).sort_title == "dragon ball super"

    def test_an_empty_title_is_refused(self, client, session: Session):
        series = Series(title="Iets", sort_title="i")
        session.add(series)
        session.commit()

        response = client.patch(f"/api/series/{series.id}/title", json={"title": "   "})
        assert response.status_code == 400


class TestWhatEachChapterTellsYou:
    """Taal en kleur horen per hoofdstuk zichtbaar te zijn."""

    def test_the_language_and_label_land_on_every_chapter(self, client, session: Session):
        from bookpal.models import Source, Subscription

        bron = Source(type="mangadex", name="MD")
        session.add(bron)
        session.flush()
        series = _series(session)
        abo = Subscription(source_id=bron.id, series_id=series.id, language="ja")
        session.add(abo)
        session.flush()
        uitgave = Edition(
            series_id=series.id, name="Kleureditie", rank=0, subscription_id=abo.id, note="kleur"
        )
        session.add(uitgave)
        session.flush()
        _book(session, series, uitgave, 1.0)
        session.commit()

        [regel] = client.get(f"/api/series/{series.id}").json()["books"]
        assert regel["edition_language"] == "ja"
        assert regel["edition_note"] == "kleur"
        assert regel["edition_name"] == "Kleureditie"

    def test_your_own_files_have_no_language(self, client, session: Session):
        series = _series(session)
        uitgave = _edition(session, series, "Eigen bestanden", 0)
        _book(session, series, uitgave, 1.0)
        session.commit()

        [regel] = client.get(f"/api/series/{series.id}").json()["books"]
        assert regel["edition_language"] is None

    def test_an_older_edition_gets_its_label_from_its_name(self, client, session: Session):
        """Uitgaven van vóór dit label horen ook gewoon "kleur" te tonen."""
        series = _series(session)
        uitgave = _edition(session, series, "One Piece (Official Colored)", 0)
        _book(session, series, uitgave, 1.0)
        session.commit()

        body = client.get(f"/api/series/{series.id}").json()
        assert body["books"][0]["edition_note"] == "kleur"
        # En bij de uitgave zelf, want daar staat de lijst waarin je ordent.
        assert body["editions"][0]["note"] == "kleur"

    def test_a_coloured_source_is_labelled_by_itself(self):
        from bookpal.sources.service import edition_note

        assert edition_note("One Piece (Official Colored)") == "kleur"
        assert edition_note("Dragon Ball Super (Coloured Edition)") == "kleur"
        assert edition_note("Oishinbo") is None


class TestRenamingOntoAnExistingName:
    def test_a_taken_name_in_the_same_folder_is_not_an_error(self, client, session: Session):
        """Binnen één map is de titel uniek; dat is geen 500 maar een voorstel."""
        from bookpal.models import LibraryRoot

        root = LibraryRoot(name="R", path="/tmp/r-hernoem")
        session.add(root)
        session.flush()
        bezet = Series(title="One Piece", sort_title="o", library_root_id=root.id)
        hernoemd = Series(
            title="One Piece (Official Colored)", sort_title="o", library_root_id=root.id
        )
        session.add_all([bezet, hernoemd])
        session.commit()

        response = client.patch(f"/api/series/{hernoemd.id}/title", json={"title": "One Piece"})
        assert response.status_code == 200
        body = response.json()
        assert body["renamed"] is False
        assert body["title"] == "One Piece (Official Colored)", "de naam blijft zoals hij was"
        assert body["merge_candidate"]["id"] == bezet.id

    def test_it_offers_to_merge(self, client, session: Session):
        session.add(Series(title="Shinya Shokudou", sort_title="s"))
        hernoemd = Series(title="Iets anders", sort_title="i")
        session.add(hernoemd)
        session.commit()

        body = client.patch(
            f"/api/series/{hernoemd.id}/title", json={"title": "Shinya Shokudo"}
        ).json()
        assert body["title"] == "Shinya Shokudo"
        assert body["merge_candidate"]["title"] == "Shinya Shokudou"

    def test_a_unique_name_offers_nothing(self, client, session: Session):
        series = Series(title="Iets", sort_title="i")
        session.add(series)
        session.commit()

        body = client.patch(f"/api/series/{series.id}/title", json={"title": "Iets nieuws"}).json()
        assert body["merge_candidate"] is None

    def test_renaming_to_its_own_name_offers_nothing(self, client, session: Session):
        """Zichzelf is geen naamgenoot."""
        series = Series(title="Iets", sort_title="i")
        session.add(series)
        session.commit()

        body = client.patch(f"/api/series/{series.id}/title", json={"title": "Iets"}).json()
        assert body["merge_candidate"] is None


class TestFetchingCovers:
    """Omslagen per deel ophalen, per uitgave apart."""

    def _opzet(self, session: Session):
        from bookpal.models import Source, Subscription

        bron = Source(type="mangadex", name="MD")
        session.add(bron)
        session.flush()
        series = _series(session)
        series.source_id = bron.id
        series.source_ref = "kleur-ref"

        uitgaven = {}
        for naam, ref, rang in (("Kleur", "kleur-ref", 0), ("Zwart-wit", "zw-ref", 1)):
            abo = Subscription(source_id=bron.id, series_id=series.id, source_ref=ref)
            session.add(abo)
            session.flush()
            uitgave = Edition(series_id=series.id, name=naam, rank=rang, subscription_id=abo.id)
            session.add(uitgave)
            session.flush()
            boek = _book(session, series, uitgave, 1.0, titel=f"H1 {naam}")
            boek.volume = "1"
            uitgaven[naam] = uitgave
        session.commit()
        return series, uitgaven

    def test_each_edition_gets_its_own_cover(self, client, session: Session, monkeypatch):
        from bookpal.sources.base import CoverInfo
        from bookpal.sources.mangadex import MangaDexSource

        series, uitgaven = self._opzet(session)
        monkeypatch.setattr(
            MangaDexSource,
            "covers",
            lambda self, ref, *, limit=100: [
                CoverInfo(url=f"https://voorbeeld.test/{ref}-v1.jpg", volume="1")
            ],
        )

        body = client.post(f"/api/series/{series.id}/covers").json()
        assert body["updated"] == 2

        session.expire_all()
        per_uitgave = {
            book.edition_id: book.cover_url
            for book in session.scalars(select(Book).where(Book.series_id == series.id))
        }
        assert per_uitgave[uitgaven["Kleur"].id] == "https://voorbeeld.test/kleur-ref-v1.jpg"
        assert per_uitgave[uitgaven["Zwart-wit"].id] == "https://voorbeeld.test/zw-ref-v1.jpg"

    def test_a_series_without_a_source_says_so(self, client, session: Session):
        series = _series(session)
        session.commit()
        assert client.post(f"/api/series/{series.id}/covers").status_code == 409

    def test_a_source_that_fails_does_not_take_the_rest_down(
        self, client, session: Session, monkeypatch
    ):
        from bookpal.sources.base import SourceError
        from bookpal.sources.mangadex import MangaDexSource

        series, _ = self._opzet(session)

        def stuk(self, ref, *, limit=100):
            raise SourceError("bron doet niet mee")

        monkeypatch.setattr(MangaDexSource, "covers", stuk)

        response = client.post(f"/api/series/{series.id}/covers")
        assert response.status_code == 200
        assert response.json()["updated"] == 0


class TestSimilarSeries:
    """Een dubbele serie ontstaat vanzelf; je hoort erop gewezen te worden."""

    def test_a_romanisation_variant_is_offered(self, client, session: Session):
        session.add(Series(title="Shinya Shokudo", sort_title="s"))
        andere = Series(title="Shinya Shokudou", sort_title="s")
        session.add(andere)
        session.commit()

        [voorstel] = client.get(f"/api/series/{andere.id}/similar").json()
        assert voorstel["title"] == "Shinya Shokudo"

    def test_a_title_with_an_edition_behind_it_is_offered(self, client, session: Session):
        """ "One Piece" en "One Piece (Official Colored)" zijn dezelfde reeks."""
        kaal = Series(title="One Piece", sort_title="o")
        gekleurd = Series(title="One Piece (Official Colored)", sort_title="o")
        session.add_all([kaal, gekleurd])
        session.commit()

        titels = [v["title"] for v in client.get(f"/api/series/{kaal.id}/similar").json()]
        assert titels == ["One Piece (Official Colored)"]

    def test_an_unrelated_series_is_not_offered(self, client, session: Session):
        eerste = Series(title="Oishinbo", sort_title="o")
        session.add_all([eerste, Series(title="One Piece", sort_title="o")])
        session.commit()

        assert client.get(f"/api/series/{eerste.id}/similar").json() == []

    def test_a_short_title_does_not_drag_everything_in(self, client, session: Session):
        """ "Ai" zit in van alles; daar valt niets op te baseren."""
        kort = Series(title="Ai", sort_title="a")
        session.add_all([kort, Series(title="Ai Yori Aoshi", sort_title="a")])
        session.commit()

        assert client.get(f"/api/series/{kort.id}/similar").json() == []
