"""Tijdschriften en drukwerk in de naamherkenning.

Twee soorten test door elkaar, met opzet.

De eerste klasse legt vast wat er nu al gebeurt met de bestanden die Daniël
écht in zijn strips-, manga- en boekenmappen heeft staan. Die namen zijn hier
letterlijk overgenomen. `parse_filename` is de functie waar de hele scanner op
leunt, dus een regel erbij voor tijdschriften mag daar niets aan veranderen —
en dat kun je alleen zien als je eerst opschrijft wat er stond.

De tweede klasse is het nieuwe gedrag.
"""

from __future__ import annotations

import pytest

from bookpal.metadata.filename import parse_filename


class TestWatErAlWas:
    """Bestaand gedrag op echte bestanden. Verandert hier iets, dan is dat een
    regressie in de rest van de bibliotheek."""

    @pytest.mark.parametrize(
        ("stem", "serie", "nummer", "deel"),
        [
            ("Dirk Jan 06", "Dirk Jan", "06", None),
            ("Dirk Jan 00.5", "Dirk Jan", "00.5", None),
            ("01 - Op Eigen Benen", "01 - Op Eigen Benen", None, None),
            (
                "Vol.10 Ch.1   Vol.10 Volume 10 - Crayon Shin-chan",
                "Vol 10 Volume 10 - Crayon Shin-chan",
                "1",
                "10",
            ),
            ("Shin'ya Shokudō Chapter 19 - Yarō Abe", "Shin'ya Shokudō", "19", None),
            (
                "Harry Potter en de Halfbloed Prins - J. K. Rowling",
                "Harry Potter en de Halfbloed Prins - J K Rowling",
                None,
                None,
            ),
        ],
    )
    def test_the_existing_library_parses_as_before(
        self, stem: str, serie: str | None, nummer: str | None, deel: str | None
    ):
        gevonden = parse_filename(stem)
        assert (gevonden.series, gevonden.number, gevonden.volume) == (serie, nummer, deel)

    def test_a_year_at_the_end_is_still_read_as_a_number(self):
        """Bestaande eigenaardigheid, hier vastgelegd en niet gerepareerd:
        `DirkJan - Z11 - 2011` levert nummer 2011. Dat is een aparte kwestie —
        wie hem oplost heeft hiermee de vindplaats."""
        assert parse_filename("DirkJan - Z11 - 2011").number == "2011"


class TestDrukwerk:
    def test_an_issue_number_beats_a_year(self):
        """`Nintendo Power Issue 001 July-August 1988` gaf eerder nummer 1988,
        dus 89 nummers kwamen binnen als aflevering 1988 tot 2012."""
        gevonden = parse_filename("Nintendo Power Issue 001 July-August 1988")
        assert gevonden.series == "Nintendo Power"
        assert gevonden.number == "001"

    @pytest.mark.parametrize("woord", ["Issue", "issue", "nr", "no", "Nr."])
    def test_the_words_a_magazine_uses(self, woord: str):
        assert parse_filename(f"Blad {woord} 7").number == "7"

    def test_a_bare_number_takes_the_series_from_the_folder(self):
        """`Power Unlimited 30 jaar/001.PDF` — de map is de reeks, het bestand
        de aflevering. Zonder dit werd "001" zelf een serienaam en kreeg je
        net zoveel series als afleveringen."""
        gevonden = parse_filename("001", folder="Power Unlimited 30 jaar")
        assert gevonden.series == "Power Unlimited 30 jaar"
        assert gevonden.number == "1"

    def test_leading_zeroes_do_not_survive_as_a_number(self):
        assert parse_filename("007", folder="Blad").number == "7"

    def test_without_a_folder_nothing_changes(self):
        """De map telt alleen mee als hij meegegeven wordt; anders blijft het
        oude gedrag staan."""
        assert parse_filename("001").series == "001"
        assert parse_filename("001").number is None

    def test_a_real_name_ignores_the_folder(self):
        """De map is een terugval, geen overheersing: een bestandsnaam die het
        zelf weet, wint."""
        gevonden = parse_filename("Dirk Jan 06", folder="Van alles")
        assert gevonden.series == "Dirk Jan"
        assert gevonden.number == "06"


class TestSerietitelUitDeMap:
    """De scanner kiest de serietitel in een eigen functie (`_series_title`),
    met een eigen aanroep van `parse_filename`. Die was ik vergeten, en toen
    kwamen 447 tijdschriften binnen als 355 losse series die "001", "002" en
    "003" heetten. Twee plekken die hetzelfde moeten weten is precies het soort
    ding dat uit de pas loopt, dus hier staat het vast.
    """

    def _titel(self, tmp_path, bestand: str, submap: str | None, kind):
        from bookpal.formats.base import BookMetadata
        from bookpal.library.scanner import _series_title

        wortel = tmp_path / "collectie"
        map_ = wortel / submap if submap else wortel
        map_.mkdir(parents=True, exist_ok=True)
        pad = map_ / bestand
        pad.write_bytes(b"x")
        return _series_title(BookMetadata(), pad, wortel, kind)

    def test_a_numbered_pdf_in_a_folder_takes_the_folder_name(self, tmp_path):
        from bookpal.models import BookKind

        titel = self._titel(tmp_path, "001.PDF", "Power Unlimited 30 jaar", BookKind.PDF)
        assert titel == "Power Unlimited 30 jaar"

    def test_a_pdf_with_a_real_name_keeps_it(self, tmp_path):
        from bookpal.models import BookKind

        titel = self._titel(tmp_path, "1989-LEGO-Catalog-1-EN-FR-NL.pdf", "Lego", BookKind.PDF)
        assert titel != "Lego"
        assert "LEGO" in titel

    def test_a_numbered_pdf_without_a_folder_is_unchanged(self, tmp_path):
        """Los in de wortel is er geen map om op terug te vallen."""
        from bookpal.models import BookKind

        assert self._titel(tmp_path, "001.PDF", None, BookKind.PDF) == "001"
