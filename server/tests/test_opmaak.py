"""Opmaak uit een omschrijving halen."""

from __future__ import annotations

import pytest

from bookpal.metadata.opmaak import zonder_opmaak


class TestEchteOmschrijvingen:
    """Zoals ze in Daniëls bibliotheek staan."""

    def test_mangadex_wraps_everything_in_divs(self):
        gevonden = zonder_opmaak(
            "<div><div>Darakuya Store Monogatari is Usui's debut series.</div>"
            "<div>The origin of Crayon Shin-chan.</div></div>"
        )
        assert "<" not in gevonden
        assert "debut series." in gevonden
        assert "The origin" in gevonden

    def test_epub_metadata_uses_paragraphs_and_bold(self):
        gevonden = zonder_opmaak(
            "<p><b>Unrivalled gardening wisdom. </b></p><p>Written as he talks.</p>"
        )
        assert gevonden.startswith("Unrivalled gardening wisdom.")
        assert "<b>" not in gevonden


class TestVorm:
    def test_paragraphs_stay_apart(self):
        """Zonder regeleindes plakt alles aan elkaar tot één muur tekst."""
        gevonden = zonder_opmaak("<p>Eerste alinea.</p><p>Tweede alinea.</p>")
        assert "\n" in gevonden
        assert gevonden.count("\n\n") <= 1

    def test_entities_become_characters(self):
        assert zonder_opmaak("Jan &amp; Alleman &mdash; klaar") == "Jan & Alleman — klaar"

    def test_bbcode_from_mangadex_is_removed(self):
        assert zonder_opmaak("[b]Let op[/b]: [url=http://x]hier[/url]") == "Let op: hier"

    def test_plain_text_is_left_alone(self):
        assert zonder_opmaak("Gewoon een zin.") == "Gewoon een zin."


class TestNiets:
    def test_none_stays_none(self):
        assert zonder_opmaak(None) is None

    def test_empty_stays_none(self):
        assert zonder_opmaak("") is None

    @pytest.mark.parametrize("tekst", ["<div></div>", "<p>  </p>", "   "])
    def test_markup_without_content_is_none(self, tekst: str):
        """Een lege regel in de app is verwarrender dan helemaal niets."""
        assert zonder_opmaak(tekst) is None
