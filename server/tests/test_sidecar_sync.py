"""Betaald werk uitwisselen met een client die zelf ook mag vertalen.

De telefoon mag onderweg vertalen — wél internet, geen NAS — dus er zijn twee
plekken waar werk ontstaat. Deze routes zijn hoe ze elkaar inhalen.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from bookpal.db import session_scope
from bookpal.models import Book, Series, Translation
from bookpal.translate import inventory, sidecar


def _eerste_boek(client: TestClient) -> int:
    return int(client.get("/api/books?limit=1").json()["items"][0]["id"])


def _leg_neer(book_id: int, naam: str, data: bytes = b"x" * 40) -> Path:
    """Een sidecar op schijf zetten zoals de server dat zelf zou doen."""
    with session_scope() as s:
        book = s.get(Book, book_id)
        assert book is not None
        series = s.get(Series, book.series_id) if book.series_id else None
        pad = sidecar.chapter_dir(series, book) / naam
        sidecar.write_bytes(pad, data)
        return pad


class TestNaamherkenning:
    """De naam komt straks van buiten en wordt een pad; dus streng."""

    def test_the_four_shapes_we_write_ourselves(self):
        assert inventory.soort_van("p0007-nl.json") == "tekst"
        assert inventory.soort_van("p0007-nl-image_fast.webp") == "hertekend"
        assert inventory.soort_van("p0007-nl-image_pro.webp") == "hertekend"
        assert inventory.soort_van("p0007-kleur.webp") == "kleuren"
        assert inventory.soort_van("p0007-kleur-nl.webp") == "kleuren"

    def test_the_raw_plate_is_its_own_kind(self):
        """Die is niet om te lezen; hij is er zodat een fout in het
        samenstellen het betaalde beeld niet kan kosten."""
        assert inventory.soort_van("p0007-kleur-ruw.webp") == "kleur-ruw"

    def test_a_path_cannot_climb_out_of_the_chapter(self):
        for poging in [
            "../p0007-nl.json",
            "../../etc/passwd",
            "/etc/passwd",
            "p0007-nl.json/../../x",
            "p7-nl.json",
            "p0007-nl.exe",
            "p0007-nl.json.webp",
            "",
        ]:
            assert inventory.soort_van(poging) is None, poging

    def test_the_page_number_comes_out_of_the_name(self):
        assert inventory.pagina_van("p0007-nl-image_fast.webp") == 7
        assert inventory.pagina_van("p0000-kleur.webp") == 0
        assert inventory.pagina_van("onzin.webp") is None


class TestInventaris:
    def test_an_empty_library_lists_nothing(self, scanned: TestClient):
        body = scanned.get("/api/sidecars").json()
        assert body == {"items": [], "total": 0, "total_bytes": 0}

    def test_what_lies_there_is_listed_with_its_size(self, scanned: TestClient):
        boek = _eerste_boek(scanned)
        _leg_neer(boek, "p0003-nl-image_fast.webp", b"y" * 128)

        body = scanned.get("/api/sidecars").json()
        assert body["total"] == 1
        assert body["total_bytes"] == 128
        regel = body["items"][0]
        assert regel["book_id"] == boek
        assert regel["page_index"] == 3
        assert regel["kind"] == "hertekend"
        assert regel["name"] == "p0003-nl-image_fast.webp"

    def test_it_can_be_narrowed_to_one_book(self, scanned: TestClient):
        boeken = scanned.get("/api/books?limit=2").json()["items"]
        _leg_neer(int(boeken[0]["id"]), "p0000-kleur.webp")
        _leg_neer(int(boeken[1]["id"]), "p0000-kleur.webp")

        assert scanned.get("/api/sidecars").json()["total"] == 2
        smal = scanned.get(f"/api/sidecars?book_id={boeken[0]['id']}").json()
        assert smal["total"] == 1
        assert smal["items"][0]["book_id"] == int(boeken[0]["id"])

    def test_files_we_did_not_write_are_ignored(self, scanned: TestClient):
        """Een losse map of een kladbestand hoort niet in de inventaris."""
        boek = _eerste_boek(scanned)
        pad = _leg_neer(boek, "p0001-nl.json", b"{}")
        (pad.parent / "aantekening.txt").write_bytes(b"hallo")

        namen = [i["name"] for i in scanned.get("/api/sidecars").json()["items"]]
        assert namen == ["p0001-nl.json"]


class TestOphalen:
    def test_you_get_the_bytes_back(self, scanned: TestClient):
        boek = _eerste_boek(scanned)
        _leg_neer(boek, "p0002-nl.json", b'{"bubbles": []}')

        antwoord = scanned.get(f"/api/sidecars/{boek}/p0002-nl.json")
        assert antwoord.status_code == 200
        assert antwoord.content == b'{"bubbles": []}'
        assert antwoord.headers["content-type"].startswith("application/json")

    def test_a_missing_one_is_a_404_and_not_an_empty_file(self, scanned: TestClient):
        boek = _eerste_boek(scanned)
        assert scanned.get(f"/api/sidecars/{boek}/p0099-nl.json").status_code == 404

    def test_a_bad_name_is_refused_before_it_touches_the_disk(self, scanned: TestClient):
        boek = _eerste_boek(scanned)
        assert scanned.get(f"/api/sidecars/{boek}/kwaad.txt").status_code == 400


class TestTerugzetten:
    def test_a_sidecar_from_the_phone_lands_on_disk(self, scanned: TestClient):
        boek = _eerste_boek(scanned)
        antwoord = scanned.put(f"/api/sidecars/{boek}/p0005-nl-image_fast.webp", content=b"z" * 64)
        assert antwoord.status_code == 201, antwoord.text
        assert antwoord.json()["bytes"] == 64

        terug = scanned.get(f"/api/sidecars/{boek}/p0005-nl-image_fast.webp")
        assert terug.content == b"z" * 64

    def test_the_index_learns_the_page_is_done(self, scanned: TestClient):
        """Anders telt de planner hem nog als werk en betaal je twee keer."""
        boek = _eerste_boek(scanned)
        scanned.put(f"/api/sidecars/{boek}/p0006-nl-image_fast.webp", content=b"z" * 64)

        with session_scope() as s:
            rij = s.scalar(
                select(Translation).where(
                    Translation.book_id == boek,
                    Translation.page_index == 6,
                    Translation.provider == "gemini-image-fast",
                )
            )
            assert rij is not None
            assert rij.payload == {"herkomst": "client"}

    def test_what_is_already_there_is_left_alone(self, scanned: TestClient):
        """Twee kanten met dezelfde pagina hebben allebei iets bruikbaars;
        dan is niets doen het goedkoopste antwoord."""
        boek = _eerste_boek(scanned)
        _leg_neer(boek, "p0004-kleur.webp", b"oud" * 10)

        antwoord = scanned.put(f"/api/sidecars/{boek}/p0004-kleur.webp", content=b"nieuw")
        assert antwoord.status_code == 201
        assert scanned.get(f"/api/sidecars/{boek}/p0004-kleur.webp").content == b"oud" * 10

    def test_the_client_can_tell_it_was_not_the_one_who_stored_it(self, scanned: TestClient):
        """Met drie of vier apparaten is dit het normale geval: iemand was je
        voor. Dat is iets anders dan "ik heb bijgedragen", en een client die
        het verschil niet ziet meldt onzin."""
        boek = _eerste_boek(scanned)

        eerste = scanned.put(f"/api/sidecars/{boek}/p0007-kleur.webp", content=b"eerste")
        assert eerste.json()["stored"] is True

        tweede = scanned.put(f"/api/sidecars/{boek}/p0007-kleur.webp", content=b"tweede")
        assert tweede.json()["stored"] is False

    def test_force_does_overwrite(self, scanned: TestClient):
        boek = _eerste_boek(scanned)
        _leg_neer(boek, "p0004-kleur.webp", b"oud" * 10)

        scanned.put(f"/api/sidecars/{boek}/p0004-kleur.webp?force=true", content=b"nieuw")
        assert scanned.get(f"/api/sidecars/{boek}/p0004-kleur.webp").content == b"nieuw"

    def test_a_bad_name_never_becomes_a_path(self, scanned: TestClient, temp_settings: Path):
        """Niet op de statuscode maar op de schijf: dát is wat telt.

        Een klimpoging strandt op verschillende plekken — de ene op ons eigen
        patroon (400), de andere al bij de router omdat de client het pad zelf
        platslaat (405). Wat ze gemeen moeten hebben is dat er niets verschijnt.
        """
        boek = _eerste_boek(scanned)
        with session_scope() as s:
            book = s.get(Book, boek)
            assert book is not None
            hoofdstuk = sidecar.chapter_dir(
                s.get(Series, book.series_id) if book.series_id else None, book
            )
        vooraf = set(hoofdstuk.parent.parent.rglob("*")) if hoofdstuk.parent.exists() else set()

        for poging in ["..%2Fp0001-nl.json", "kwaad.sh", "p0001-nl.json.exe", "p0001-nl.json%00"]:
            antwoord = scanned.put(f"/api/sidecars/{boek}/{poging}", content=b"x")
            assert antwoord.status_code >= 400, f"{poging} werd geaccepteerd"

        achteraf = set(hoofdstuk.parent.parent.rglob("*")) if hoofdstuk.parent.exists() else set()
        assert achteraf == vooraf, "er is toch iets weggeschreven"

    def test_an_empty_body_is_refused(self, scanned: TestClient):
        boek = _eerste_boek(scanned)
        assert scanned.put(f"/api/sidecars/{boek}/p0008-nl.json", content=b"").status_code == 400

    def test_something_far_too_big_is_refused(self, scanned: TestClient):
        from bookpal.api.sidecars import MAX_BYTES

        boek = _eerste_boek(scanned)
        antwoord = scanned.put(
            f"/api/sidecars/{boek}/p0009-nl-image_pro.webp", content=b"x" * (MAX_BYTES + 1)
        )
        assert antwoord.status_code == 413

    def test_an_unknown_book_is_a_404(self, scanned: TestClient):
        assert scanned.put("/api/sidecars/99999/p0001-nl.json", content=b"x").status_code == 404


class TestRondje:
    def test_what_goes_up_comes_back_in_the_manifest(self, scanned: TestClient):
        """Het hele punt: de ene kant zet neer, de andere ziet het staan."""
        boek = _eerste_boek(scanned)
        scanned.put(f"/api/sidecars/{boek}/p0010-nl-image_fast.webp", content=b"q" * 99)

        lijst = scanned.get("/api/sidecars").json()["items"]
        assert [(i["page_index"], i["kind"], i["bytes"]) for i in lijst] == [(10, "hertekend", 99)]
