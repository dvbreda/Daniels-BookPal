"""Metadata naast het bestand.

De database is weg zodra je opnieuw begint; de map met je boeken niet. Wat hier
vastligt is dat een sidecar aanvult en nooit overschrijft wat zwaarder weegt —
een titel die jij hebt ingetypt hoort een scan te overleven.
"""

from __future__ import annotations

import json
from pathlib import Path

from bookpal.library import sidecars


def _cbz(tmp_path: Path, naam: str = "Storm 01.cbz") -> Path:
    pad = tmp_path / naam
    pad.write_bytes(b"nep")
    return pad


class TestWritingAndReading:
    def test_it_lands_in_the_hidden_folder_next_to_the_file(self, tmp_path: Path):
        """Alles van ons bij elkaar, en uit het zicht bij normaal bladeren."""
        boek = _cbz(tmp_path)
        zijkant = sidecars.Sidecar(titles={"": "Herring Roe"})
        pad = sidecars.write(boek, zijkant)

        assert pad == tmp_path / ".sidecars" / "Storm 01.cbz.json"
        assert pad.is_file()

    def test_an_old_sidecar_is_still_read(self, tmp_path: Path):
        """Een map van een oudere installatie hoort gewoon te werken."""
        boek = _cbz(tmp_path)
        sidecars.legacy_path_for(boek).write_text(
            '{"titles": {"": "Oude Titel"}}', encoding="utf-8"
        )

        gelezen = sidecars.read(boek)
        assert gelezen is not None
        assert gelezen.titles[""] == "Oude Titel"

    def test_writing_cleans_up_the_old_one(self, tmp_path: Path):
        """Twee waarheden naast elkaar is hoe ze uit elkaar gaan lopen."""
        boek = _cbz(tmp_path)
        oud = sidecars.legacy_path_for(boek)
        oud.write_text('{"titles": {"": "Oude Titel"}}', encoding="utf-8")

        sidecars.write(boek, sidecars.Sidecar(titles={"": "Nieuwe Titel"}))

        assert not oud.exists()
        assert sidecars.read(boek).titles[""] == "Nieuwe Titel"

    def test_what_you_wrote_comes_back(self, tmp_path: Path):
        boek = _cbz(tmp_path)
        sidecars.write(
            boek,
            sidecars.Sidecar(
                titles={"en": "Herring Roe", "ja": "数の子"},
                series="Shinya Shokudo",
                number="59",
                authors=["Abe Yarou"],
            ),
        )

        terug = sidecars.read(boek)
        assert terug is not None
        assert terug.titles["ja"] == "数の子"
        assert terug.series == "Shinya Shokudo"
        assert terug.authors == ["Abe Yarou"]

    def test_it_is_readable_json(self, tmp_path: Path):
        """Je moet het met een teksteditor kunnen corrigeren."""
        boek = _cbz(tmp_path)
        sidecars.write(boek, sidecars.Sidecar(titles={"": "Iets"}))
        ruw = json.loads(sidecars.path_for(boek).read_text(encoding="utf-8"))
        assert ruw["version"] == sidecars.VERSION
        assert ruw["titles"] == {"": "Iets"}
        assert "updated_at" in ruw

    def test_empty_fields_are_left_out(self, tmp_path: Path):
        """Een muur van nulls maakt het onleesbaar."""
        boek = _cbz(tmp_path)
        sidecars.write(boek, sidecars.Sidecar(titles={"": "Iets"}))
        ruw = json.loads(sidecars.path_for(boek).read_text(encoding="utf-8"))
        assert "summary" not in ruw
        assert "cover_data" not in ruw

    def test_a_broken_sidecar_is_ignored_not_fatal(self, tmp_path: Path):
        boek = _cbz(tmp_path)
        pad = sidecars.path_for(boek)
        pad.parent.mkdir(parents=True, exist_ok=True)
        pad.write_text("{dit is geen json", encoding="utf-8")
        assert sidecars.read(boek) is None

    def test_a_hand_written_title_as_plain_text_is_accepted(self, tmp_path: Path):
        """Wie dit met de hand invult schrijft geen kaartje met taalcodes."""
        boek = _cbz(tmp_path)
        pad = sidecars.path_for(boek)
        pad.parent.mkdir(parents=True, exist_ok=True)
        pad.write_text('{"titles": "Met de hand"}', encoding="utf-8")
        zijkant = sidecars.read(boek)
        assert zijkant is not None
        assert zijkant.title() == "Met de hand"

    def test_nothing_half_written_is_left_behind(self, tmp_path: Path):
        boek = _cbz(tmp_path)
        sidecars.write(boek, sidecars.Sidecar(titles={"": "Iets"}))
        assert list(tmp_path.glob("*.deel")) == []


class TestPrecedence:
    def test_a_source_may_replace_a_filename(self, tmp_path: Path):
        zijkant = sidecars.Sidecar()
        assert zijkant.set_title("Chapter 59", herkomst="filename") is True
        assert zijkant.set_title("Herring Roe", herkomst="source") is True
        assert zijkant.title() == "Herring Roe"

    def test_a_filename_may_not_replace_your_own_words(self, tmp_path: Path):
        zijkant = sidecars.Sidecar()
        zijkant.set_title("Zo noem ik het", herkomst="manual")
        assert zijkant.set_title("Chapter 59", herkomst="filename") is False
        assert zijkant.title() == "Zo noem ik het"

    def test_the_same_source_may_update_itself(self, tmp_path: Path):
        """Een tweede ronde bij dezelfde bron is een actualisering."""
        zijkant = sidecars.Sidecar()
        zijkant.set_title("Oud", herkomst="source")
        assert zijkant.set_title("Nieuw", herkomst="source") is True


class TestTitles:
    def test_your_language_wins(self):
        zijkant = sidecars.Sidecar(titles={"": "Naamloos", "nl": "Haringkuit"})
        assert zijkant.title("nl") == "Haringkuit"

    def test_without_your_language_the_plain_one_wins(self):
        zijkant = sidecars.Sidecar(titles={"": "Naamloos", "ja": "数の子"})
        assert zijkant.title("nl") == "Naamloos"

    def test_with_nothing_at_all_there_is_no_title(self):
        assert sidecars.Sidecar().title() is None


class TestCovers:
    def test_a_picture_goes_in_and_comes_out(self):
        plaatje = b"\x89PNG nep"
        uri = sidecars.encode_cover(plaatje, "image/png")
        assert uri is not None and uri.startswith("data:image/png;base64,")
        assert sidecars.cover_bytes(sidecars.Sidecar(cover_data=uri)) == plaatje

    def test_something_too_big_is_refused(self):
        """763 hoofdstukken met elk een halve MB is een halve GB aan json."""
        assert sidecars.encode_cover(b"x" * (sidecars.MAX_COVER_BYTES + 1)) is None

    def test_nonsense_in_the_cover_field_is_ignored(self):
        assert sidecars.cover_bytes(sidecars.Sidecar(cover_data="geen base64!")) is None


class TestTheScannerUsesThem:
    """Bij de scan gelezen én geschreven, zodat het vanzelf bijblijft."""

    def test_a_scan_leaves_a_sidecar_behind(self, session, tmp_path: Path):
        from bookpal.library import scan_root
        from tests.conftest import make_cbz, make_root

        wortel = tmp_path / "lib"
        make_cbz(wortel / "Storm" / "Storm 01.cbz", pages=2)
        root = make_root(session, wortel)
        session.commit()

        scan_root(session, root)
        assert (wortel / "Storm" / ".sidecars" / "Storm 01.cbz.json").is_file()

    def test_a_title_in_the_sidecar_wins_from_the_filename(self, session, tmp_path: Path):
        from bookpal.library import scan_root
        from bookpal.models import Book
        from tests.conftest import make_cbz, make_root

        wortel = tmp_path / "lib"
        bestand = wortel / "Storm" / "Storm 01.cbz"
        make_cbz(bestand, pages=2)
        sidecars.write(bestand, sidecars.Sidecar(titles={"": "Zo noem ik het"}))
        root = make_root(session, wortel)
        session.commit()

        scan_root(session, root)
        boek = session.query(Book).one()
        assert boek.title == "Zo noem ik het"

    def test_a_second_scan_keeps_it(self, session, tmp_path: Path):
        """Zonder dit legt elke scan er weer de bestandsnaam overheen."""
        from bookpal.library import scan_root
        from bookpal.models import Book
        from tests.conftest import make_cbz, make_root

        wortel = tmp_path / "lib"
        bestand = wortel / "Storm" / "Storm 01.cbz"
        make_cbz(bestand, pages=2)
        sidecars.write(bestand, sidecars.Sidecar(titles={"": "Zo noem ik het"}))
        root = make_root(session, wortel)
        session.commit()

        scan_root(session, root)
        scan_root(session, root, force=True)
        assert session.query(Book).one().title == "Zo noem ik het"

    def test_a_chosen_cover_page_comes_back(self, session, tmp_path: Path):
        from bookpal.library import scan_root
        from bookpal.models import Book
        from tests.conftest import make_cbz, make_root

        wortel = tmp_path / "lib"
        bestand = wortel / "Storm" / "Storm 01.cbz"
        make_cbz(bestand, pages=4)
        sidecars.write(bestand, sidecars.Sidecar(cover_page=2))
        root = make_root(session, wortel)
        session.commit()

        scan_root(session, root)
        assert session.query(Book).one().cover_page_index == 2


class TestBackfill:
    def test_the_whole_library_gets_them(self, client, session, tmp_path: Path):
        from bookpal.library import scan_root
        from tests.conftest import make_cbz, make_root

        wortel = tmp_path / "lib"
        make_cbz(wortel / "Storm" / "Storm 01.cbz", pages=2)
        make_cbz(wortel / "Storm" / "Storm 02.cbz", pages=2)
        root = make_root(session, wortel)
        session.commit()
        scan_root(session, root)
        session.commit()
        # Doe alsof ze er nog niet waren.
        for pad in wortel.rglob(".sidecars/*.json"):
            pad.unlink()

        body = client.post("/api/libraries/sidecars").json()
        assert body["written"] == 2
        assert len(list(wortel.rglob(".sidecars/*.json"))) == 2

    def test_running_twice_writes_nothing_new(self, client, session, tmp_path: Path):
        from bookpal.library import scan_root
        from tests.conftest import make_cbz, make_root

        wortel = tmp_path / "lib"
        make_cbz(wortel / "Storm" / "Storm 01.cbz", pages=2)
        root = make_root(session, wortel)
        session.commit()
        scan_root(session, root)
        session.commit()

        client.post("/api/libraries/sidecars")
        tweede = client.post("/api/libraries/sidecars").json()
        assert tweede["written"] == 0
