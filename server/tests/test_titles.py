"""Titels die hetzelfde bedoelen maar anders geschreven zijn."""

from __future__ import annotations

import pytest

from bookpal.metadata.titles import normalise, same_title


class TestNormalise:
    @pytest.mark.parametrize(
        ("links", "rechts"),
        [
            # Het echte geval: MyAnimeList schrijft "Shinya Shokudou",
            # de map "Shinya Shokudo", de omslag "Shin'ya Shokudō".
            ("Shinya Shokudou", "Shinya Shokudo"),
            ("Shin'ya Shokudō", "Shinya Shokudo"),
            ("Shinya Shokudoo", "Shinya Shokudo"),
            # Hoofdletters en leestekens.
            ("Crayon Shin-Chan", "Crayon Shin-chan"),
            ("Crayon Shin chan", "CrayonShinchan"),
            # Andere lange klinkers.
            ("Yuuki", "Yuki"),
            ("Fuyu no Doubutsuen", "Fuyu no Dobutsuen"),
            ("Ōkami", "Okami"),
        ],
    )
    def test_variants_of_the_same_title_match(self, links: str, rechts: str):
        assert same_title(links, rechts), f"{links!r} != {rechts!r}"

    @pytest.mark.parametrize(
        ("links", "rechts"),
        [
            ("Oishinbo", "Shinya Shokudo"),
            ("Dragon Ball", "Dragon Ball Super"),
            ("One Piece", "One Punch Man"),
        ],
    )
    def test_different_titles_stay_different(self, links: str, rechts: str):
        assert not same_title(links, rechts)

    def test_an_empty_title_never_matches(self):
        assert not same_title("", "")
        assert not same_title("Oishinbo", "")

    def test_the_key_is_stable(self):
        assert normalise("Shin'ya Shokudō") == normalise("shinya shokudou")
