"""Vertaling (M8): tekstwolkjes detecteren, uitlezen en vertalen."""

from __future__ import annotations

from bookpal.config import settings
from bookpal.translate.base import (
    Bubble,
    BubbleKind,
    BubbleTranslator,
    PageResult,
    TranslationError,
)
from bookpal.translate.gemini import GeminiBubbleTranslator


def get_translator() -> BubbleTranslator:
    """De ingestelde vertaler. Gooit ``TranslationError`` als er geen sleutel
    is — dat is geen storing maar een keuze die de gebruiker nog moet maken."""
    return GeminiBubbleTranslator(settings.gemini_api_key, model=settings.gemini_model)


def is_configured() -> bool:
    """Kan er überhaupt vertaald worden? De clients verbergen de knop als dit
    False is, in plaats van je op een 409 te laten lopen."""
    return bool(settings.gemini_api_key)


__all__ = [
    "Bubble",
    "BubbleKind",
    "BubbleTranslator",
    "GeminiBubbleTranslator",
    "PageResult",
    "TranslationError",
    "get_translator",
    "is_configured",
]
