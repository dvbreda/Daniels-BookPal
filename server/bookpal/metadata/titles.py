"""Titels vergelijken die hetzelfde bedoelen maar anders geschreven zijn.

Bij manga is dat eerder regel dan uitzondering: dezelfde reeks heet
"Shinya Shokudou" op MyAnimeList, "Shinya Shokudo" in je map en
"Shin'ya Shokudō" op de omslag. Dat zijn allemaal manieren om dezelfde lange
klinker te schrijven — ``ō``, ``ou`` en ``oo`` staan voor hetzelfde.

Bewust alleen gebruikt om *voorstellen* te doen. Wat er samengevoegd of
gekoppeld wordt beslist de gebruiker, want dit blijft raden: "Doubutsu" en
"Dobutsu" zijn hetzelfde, maar twee reeksen die toevallig op één letter
verschillen zijn dat niet.
"""

from __future__ import annotations

import re
import unicodedata

# Lange klinkers, in de drie schrijfwijzen die je tegenkomt. Volgorde telt:
# eerst de dubbele klinkers, anders blijft er na het strippen van een macron
# alsnog "ou" staan.
_LONG_VOWELS = (
    ("ou", "o"),
    ("oo", "o"),
    ("uu", "u"),
    ("aa", "a"),
    ("ee", "e"),
    ("ii", "i"),
)

_NOT_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise(title: str) -> str:
    """Een sleutel waarop twee schrijfwijzen van dezelfde titel gelijk zijn."""
    # Macrons en accenten eraf: ō wordt o, é wordt e.
    folded = unicodedata.normalize("NFKD", title.lower())
    folded = "".join(character for character in folded if not unicodedata.combining(character))

    # Leestekens en spaties eruit vóór het inkorten van klinkers, zodat
    # "Shin'ya" en "Shinya" hetzelfde worden.
    folded = _NOT_ALNUM.sub("", folded)

    for long_form, short_form in _LONG_VOWELS:
        folded = folded.replace(long_form, short_form)
    return folded


def same_title(left: str, right: str) -> bool:
    return bool(left) and bool(right) and normalise(left) == normalise(right)
