"""Wanneer een uitgave verscheen, uit de bestandsnaam."""

from __future__ import annotations

import pytest

from bookpal.metadata.publicatiedatum import Publicatie, uit_naam


class TestEchteBestanden:
    """De twee die er daadwerkelijk in `_tijdschriften` staan."""

    def test_month_number_with_dots(self):
        gevonden = uit_naam("BBC_Gardeners'_World_09.2026_clean")
        assert gevonden == Publicatie(jaar=2026, maand=9)

    def test_month_name_without_a_separator(self):
        """`BBCGardeners'World-June2026` — de maand plakt aan het jaar vast."""
        assert uit_naam("BBCGardeners'World-June2026") == Publicatie(jaar=2026, maand=6)


class TestVormen:
    @pytest.mark.parametrize(
        ("naam", "verwacht"),
        [
            ("Tijdschrift 2026-09", Publicatie(2026, 9)),
            ("Tijdschrift_2026_09", Publicatie(2026, 9)),
            ("Blad - September 2026", Publicatie(2026, 9)),
            ("Blad sep-2026", Publicatie(2026, 9)),
            ("Blad Oktober 2026", Publicatie(2026, 10)),
            ("Blad maart 2026", Publicatie(2026, 3)),
            ("Blad 12.2026", Publicatie(2026, 12)),
            ("Jaarboek 2026", Publicatie(2026)),
        ],
    )
    def test_the_shapes_we_expect(self, naam: str, verwacht: Publicatie):
        assert uit_naam(naam) == verwacht

    def test_a_month_name_beats_a_bare_year_elsewhere(self):
        """Een maandnaam kan niets anders betekenen; een los jaartal wel."""
        assert uit_naam("Best of 1999 - June 2026") == Publicatie(2026, 6)


class TestNietVerzinnen:
    """Liever niets dan een verkeerde datum: die sorteert stil verkeerd."""

    def test_a_resolution_is_not_a_date(self):
        assert uit_naam("Aflevering 1080p") is None

    def test_a_bare_number_block_is_not_a_month_and_year(self):
        """`092026` zonder scheidingsteken is een nummer, geen datum."""
        assert uit_naam("Scan 092026") is None

    def test_an_impossible_month_falls_back_to_the_year(self):
        """13 is geen maand, maar 2026 is wel een jaar. Terugvallen op het jaar
        is dan juist — wat niet mag is maand 13 verzinnen."""
        gevonden = uit_naam("Blad 13.2026")
        assert gevonden == Publicatie(jaar=2026)
        assert gevonden.maand is None

    def test_a_year_out_of_range_is_refused(self):
        assert uit_naam("Blad 1823") is None
        assert uit_naam("Blad 2400") is None

    def test_nothing_at_all(self):
        assert uit_naam("Gewoon een titel") is None


class TestSorteren:
    def test_later_issues_sort_after_earlier_ones(self):
        namen = ["Blad June2026", "Blad 09.2026", "Blad 2026-01", "Jaarboek 2026"]
        gevonden = [uit_naam(naam) for naam in namen]
        assert all(item is not None for item in gevonden)
        op_volgorde = sorted(gevonden, key=lambda p: p.sorteersleutel)
        assert [str(p) for p in op_volgorde] == ["2026", "2026-01", "2026-06", "2026-09"]


class TestDoorDeKeten:
    """Van bestandsnaam tot API: de datum moet er aan de andere kant uitkomen."""

    def test_the_scanner_stores_what_it_finds(self, client, tmp_path):
        from tests.fixtures import make_pdf

        wortel = tmp_path / "bladen" / "Nintendo Power"
        wortel.mkdir(parents=True)
        make_pdf(wortel / "Nintendo Power Issue 001 July-August 1988.pdf", pages=1)
        root = client.post(
            "/api/libraries", json={"name": "Bladen", "path": str(tmp_path / "bladen")}
        ).json()["id"]
        client.post(f"/api/libraries/{root}/scan")

        boeken = client.get("/api/books?limit=5").json()["items"]
        gevonden = [b for b in boeken if b["published_year"]]
        assert gevonden, "geen enkel boek kreeg een publicatiedatum"
        assert gevonden[0]["published_year"] == 1988
        assert gevonden[0]["published_month"] == 8

    def test_sorting_by_name_is_still_the_default(self, scanned):
        """Op `sort_title` en niet op de titel zelf: die laat een lidwoord
        vallen, dus "Een Testboek" sorteert onder de T."""
        eerst = scanned.get("/api/series").json()["items"]
        op_naam = scanned.get("/api/series?sort=naam").json()["items"]
        assert [s["id"] for s in eerst] == [s["id"] for s in op_naam]
        sleutels = [s["sort_title"] for s in eerst]
        assert sleutels == sorted(sleutels)

    def test_an_unknown_sort_is_a_bad_request(self, scanned):
        assert scanned.get("/api/series?sort=onzin").status_code == 422

    def test_series_without_a_date_sort_last(self, scanned):
        """Onbekend is geen 1900: die horen achteraan, niet bovenaan."""
        titels = [s["title"] for s in scanned.get("/api/series?sort=verschenen").json()["items"]]
        assert len(titels) == 4
