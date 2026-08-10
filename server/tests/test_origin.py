"""De herkomst-keten — de lastigste eis, dus per stap uitgetest."""

from __future__ import annotations

from bookpal.metadata.origin import (
    Origin,
    from_embedded,
    from_online,
    from_root_default,
    resolve,
)
from bookpal.models import OriginRegion, OriginSource


class TestEmbedded:
    def test_manga_flag_wins_over_everything(self):
        # Een Nederlandse scan van een Japanse manga: taal zegt nl, maar het
        # Manga-veld zegt waar het vandaan komt.
        origin = from_embedded(publisher="Glénat", language="nl", manga_flag="YesAndRightToLeft")
        assert origin.region is OriginRegion.JAPAN
        assert origin.country == "jp"
        assert origin.source is OriginSource.EMBEDDED

    def test_manga_yes_also_counts(self):
        assert from_embedded(manga_flag="Yes").region is OriginRegion.JAPAN

    def test_manga_no_does_not_imply_japan(self):
        assert from_embedded(manga_flag="No").region is not OriginRegion.JAPAN

    def test_european_publisher(self):
        origin = from_embedded(publisher="Dupuis")
        assert origin.region is OriginRegion.EUROPE
        assert origin.country == "be"

    def test_publisher_with_extra_words(self):
        assert from_embedded(publisher="Dargaud Benelux").region is OriginRegion.EUROPE

    def test_japanese_publisher(self):
        assert from_embedded(publisher="Shueisha").region is OriginRegion.JAPAN

    def test_us_publisher(self):
        assert from_embedded(publisher="Marvel").region is OriginRegion.US

    def test_original_language_is_a_strong_signal(self):
        # Een bestand ín het Japans is vrijwel zeker Japans origineel.
        assert from_embedded(language="ja").region is OriginRegion.JAPAN
        assert from_embedded(language="ko").region is OriginRegion.KOREA

    def test_european_language_is_only_a_weak_signal(self):
        # Zonder manga-aanwijzing telt een Europese taal mee...
        assert from_embedded(language="nl").region is OriginRegion.EUROPE
        # ...maar zodra ComicInfo iets over manga zegt, niet meer, want dan kan
        # het net zo goed een vertaling zijn.
        assert from_embedded(language="nl", manga_flag="No").region is OriginRegion.UNKNOWN

    def test_nothing_known(self):
        assert from_embedded().region is OriginRegion.UNKNOWN
        assert from_embedded().known is False


class TestOnline:
    def test_mangadex_original_language(self):
        origin = from_online("ja")
        assert origin.region is OriginRegion.JAPAN
        assert origin.source is OriginSource.ONLINE

    def test_english_maps_to_us(self):
        assert from_online("en").region is OriginRegion.US

    def test_empty(self):
        assert from_online(None).known is False


class TestRootDefault:
    def test_explicit_region(self):
        origin = from_root_default(None, OriginRegion.EUROPE)
        assert origin.region is OriginRegion.EUROPE
        assert origin.source is OriginSource.ROOT_DEFAULT

    def test_language_implies_region(self):
        assert from_root_default("ja", None).region is OriginRegion.JAPAN

    def test_nothing_set(self):
        assert from_root_default(None, None).known is False


class TestPrecedence:
    def test_online_beats_embedded(self):
        best = resolve(
            from_embedded(publisher="Dupuis"),  # zegt Europa
            from_online("ja"),  # zegt Japan
        )
        assert best.region is OriginRegion.JAPAN
        assert best.source is OriginSource.ONLINE

    def test_embedded_beats_root_default(self):
        best = resolve(
            from_root_default(None, OriginRegion.EUROPE),
            from_embedded(manga_flag="Yes"),
        )
        assert best.region is OriginRegion.JAPAN

    def test_root_default_fills_the_gap(self):
        best = resolve(from_embedded(), from_root_default(None, OriginRegion.EUROPE))
        assert best.region is OriginRegion.EUROPE
        assert best.source is OriginSource.ROOT_DEFAULT

    def test_manual_choice_survives_a_rescan(self):
        """De belangrijkste eigenschap: wat jij zelf zet blijft staan."""
        manual = Origin("nl", "be", OriginRegion.EUROPE, OriginSource.MANUAL)
        best = resolve(
            from_embedded(manga_flag="YesAndRightToLeft"),  # zou Japan zeggen
            from_online("ja"),  # zou ook Japan zeggen
            current=manual,
        )
        assert best.region is OriginRegion.EUROPE
        assert best.source is OriginSource.MANUAL

    def test_unknown_current_is_replaced(self):
        best = resolve(from_embedded(publisher="Dupuis"), current=Origin())
        assert best.region is OriginRegion.EUROPE

    def test_nothing_known_at_all(self):
        assert resolve(from_embedded(), from_root_default(None, None)).known is False
