"""Tekstwolkjes vertalen: het contract (M8).

Eén pagina in, een lijst tekstvlakken uit — elk met waar het staat, wat er
staat en wat het betekent. De clients (web nu, iOS later) tekenen daar een
overlay mee; voor de Kobo bakt de server het in het beeld, omdat die pagina's
toch al server-side klaargemaakt worden.

Bewust géén inpainting in v1: een dekkend vlakje met de vertaling erop is
goedkoper en goed genoeg, en het origineel blijft één tik verderop zichtbaar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TranslationError(RuntimeError):
    """De vertaler kon deze pagina niet doen. Zacht falen: de lezer toont dan
    gewoon het origineel."""


class BubbleKind(StrEnum):
    SPEECH = "speech"
    THOUGHT = "thought"
    CAPTION = "caption"
    SFX = "sfx"


@dataclass(frozen=True, slots=True)
class Bubble:
    """Eén tekstvlak op een pagina.

    De box is genormaliseerd op 0..1 ten opzichte van de volledige pagina, niet
    in pixels: dezelfde vertaling moet over elk beeldprofiel heen passen — de
    web-versie, de Kobo-versie en de miniatuur hebben alle drie een andere
    afmeting.
    """

    x0: float
    y0: float
    x1: float
    y1: float
    source: str
    translation: str
    kind: BubbleKind = BubbleKind.SPEECH
    # Hoe de lettering eruitziet in het origineel. Het model kan geen font
    # namaken — glyphs tekenen kan het niet — maar het kan wél zien dat iets
    # vet of schuin staat, en daar hebben we echte striplettering voor.
    bold: bool = False
    italic: bool = False

    @property
    def upper(self) -> bool:
        """Stond het origineel in kapitalen?

        Dit vragen we niet aan het model: het staat gewoon in de brontekst, en
        een controle die je zelf kunt doen hoort niet in een prompt. Striplettering
        is traditioneel volledig in kapitalen, en een vertaling in onderkast
        daartussen valt meteen op als 'ingeplakt'.
        """
        letters = [character for character in self.source if character.isalpha()]
        return len(letters) >= 2 and all(character.isupper() for character in letters)

    def to_payload(self) -> dict[str, Any]:
        return {
            "box": [self.x0, self.y0, self.x1, self.y1],
            "source": self.source,
            "translation": self.translation,
            "kind": str(self.kind),
            "bold": self.bold,
            "italic": self.italic,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> Bubble:
        box = data.get("box") or [0.0, 0.0, 0.0, 0.0]
        try:
            kind = BubbleKind(data.get("kind", "speech"))
        except ValueError:
            kind = BubbleKind.SPEECH
        return cls(
            x0=float(box[0]),
            y0=float(box[1]),
            x1=float(box[2]),
            y1=float(box[3]),
            source=str(data.get("source", "")),
            translation=str(data.get("translation", "")),
            kind=kind,
            bold=bool(data.get("bold", False)),
            italic=bool(data.get("italic", False)),
        )


@dataclass(frozen=True, slots=True)
class PageResult:
    """Wat een vertaler van één pagina maakt."""

    bubbles: list[Bubble] = field(default_factory=list)
    source_lang: str | None = None
    model: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "bubbles": [bubble.to_payload() for bubble in self.bubbles],
            "source_lang": self.source_lang,
            "model": self.model,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> PageResult:
        return cls(
            bubbles=[Bubble.from_payload(item) for item in data.get("bubbles") or []],
            source_lang=data.get("source_lang"),
            model=str(data.get("model", "")),
        )


class BubbleTranslator(ABC):
    """Detecteren, uitlezen en vertalen in één stap.

    Bewust één interface in plaats van drie (detectie → OCR → vertaling): een
    model dat de hele pagina ziet, vertaalt beter dan een keten die losse
    strings doorgeeft. Wie later een lokale YOLO+OCR-pipeline wil bouwen,
    implementeert gewoon dezelfde methode.
    """

    provider: str

    @abstractmethod
    def translate_page(self, image: bytes, *, media_type: str, target_lang: str) -> PageResult:
        """Vertaal één pagina. Gooit ``TranslationError`` als het niet lukt."""

    def close(self) -> None:  # noqa: B027
        """Ruim netwerkverbindingen op. Standaard niets te doen."""
