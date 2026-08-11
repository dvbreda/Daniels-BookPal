"""Vertaalde pagina's maken en bewaren (M8).

Een pagina gaat één keer door de molen: het resultaat komt in ``Translation``
te staan, met ``(book_id, page_index, target_lang, provider)`` als unieke
sleutel. Alles wat daarna om die pagina vraagt — de web-overlay, de ingebakken
Kobo-versie, iOS later — leest dezelfde rij.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.images import ImageProfile, get_profile, open_source, render_page, source_id_for
from bookpal.models import Book, File, Translation
from bookpal.translate.base import BubbleTranslator, PageResult, TranslationError
from bookpal.translate.overlay import render_layer

logger = logging.getLogger(__name__)

# Waarop de vertaler de pagina te zien krijgt. Groter dan "web" levert geen
# betere uitlezing op maar wel een groter verzoek; "web" is wat de browser
# toch al toont, dus dit hergebruikt de bestaande cache in plaats van een
# tweede variant van elke pagina op schijf te zetten.
TRANSLATE_PROFILE = "web"


def find(
    session: Session, book_id: int, page_index: int, target_lang: str, provider: str
) -> Translation | None:
    return session.scalar(
        select(Translation).where(
            Translation.book_id == book_id,
            Translation.page_index == page_index,
            Translation.target_lang == target_lang,
            Translation.provider == provider,
        )
    )


def render_for_translation(session: Session, book: Book, page_index: int) -> tuple[bytes, str]:
    """De pagina als bytes, in hetzelfde profiel dat de browser toont."""
    return render_for_translation_profile(
        session, book, page_index, get_profile(TRANSLATE_PROFILE)
    )


def render_for_translation_profile(
    session: Session, book: Book, page_index: int, profile: ImageProfile
) -> tuple[bytes, str]:
    if book.file_id is None:
        raise TranslationError("dit boek heeft nog geen lokaal bestand")
    file_row = session.get(File, book.file_id)
    if file_row is None:
        raise TranslationError("bestand niet gevonden")

    path = Path(file_row.path)
    if not path.is_file():
        raise TranslationError("bestand niet gevonden")

    source = open_source(path)
    try:
        rendered = render_page(source, page_index, profile, source_id=source_id_for(path))
    except (IndexError, OSError) as exc:
        raise TranslationError(f"pagina {page_index} kon niet gerenderd worden: {exc}") from exc
    return rendered.data, rendered.media_type


def translate_page(
    session: Session,
    translator: BubbleTranslator,
    book: Book,
    page_index: int,
    *,
    target_lang: str,
    force: bool = False,
) -> PageResult:
    """Vertaal één pagina, of geef terug wat er al ligt.

    ``force`` gooit een bestaand resultaat weg en vertaalt opnieuw — nodig als
    je van model wisselt en wilt zien of het beter wordt.
    """
    existing = find(session, book.id, page_index, target_lang, translator.provider)
    if existing is not None and not force:
        return PageResult.from_payload(existing.payload)

    image, media_type = render_for_translation(session, book, page_index)
    result = translator.translate_page(image, media_type=media_type, target_lang=target_lang)

    if existing is None:
        existing = Translation(
            book_id=book.id,
            page_index=page_index,
            target_lang=target_lang,
            provider=translator.provider,
        )
        session.add(existing)
    existing.payload = result.to_payload()
    session.commit()
    return result


def render_layer_for(
    session: Session, book: Book, page_index: int, profile: ImageProfile, row: Translation
) -> bytes:
    """De vertaallaag als doorzichtige PNG, op de maat van deze pagina in dit
    profiel — en gecached, want tekst zetten is niet gratis op een N100.

    De cachesleutel bevat de opgeslagen vertaling zelf, dus opnieuw vertalen
    (``force``) levert vanzelf een nieuwe sleutel op in plaats van de oude laag
    te blijven tonen.
    """
    image, _media_type = render_for_translation_profile(session, book, page_index, profile)
    with Image.open(BytesIO(image)) as page:
        size = page.size

    stamp = hashlib.sha256(
        json.dumps(row.payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    key = hashlib.sha256(
        f"overlay|{book.id}|{page_index}|{profile.name}|{size[0]}x{size[1]}|{stamp}".encode()
    ).hexdigest()
    path = settings.cache_dir / "overlay" / key[:2] / key[2:4] / f"{key}.png"
    if path.exists():
        return path.read_bytes()

    data = render_layer(size, PageResult.from_payload(row.payload).bubbles)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{threading.get_ident()}.tmp")
    temp.write_bytes(data)
    temp.replace(path)
    return data


def translated_pages(session: Session, book_id: int, target_lang: str, provider: str) -> set[int]:
    """Welke pagina's van dit boek al klaar zijn — voedt zowel de
    voortgangsbalk als de planner die bepaalt wat er nog moet."""
    rows = session.scalars(
        select(Translation.page_index).where(
            Translation.book_id == book_id,
            Translation.target_lang == target_lang,
            Translation.provider == provider,
        )
    ).all()
    return {index for index in rows if index is not None}


def plan_pages(
    session: Session,
    book: Book,
    *,
    target_lang: str,
    provider: str,
    from_page: int = 0,
    limit: int | None = None,
) -> list[int]:
    """Welke pagina's nog vertaald moeten worden, in leesvolgorde vanaf
    ``from_page``.

    Net als het vooruitlezen van M5 begint dit bij waar je bent en niet bij
    pagina 1: wat je al voorbij bent, hoef je niet meer vertaald te krijgen.
    """
    if book.page_count is None:
        return []
    done = translated_pages(session, book.id, target_lang, provider)
    todo = [index for index in range(from_page, book.page_count) if index not in done]
    if limit is not None:
        todo = todo[:limit]
    return todo


def readahead_pages(
    session: Session, book: Book, *, target_lang: str, provider: str, current_page: int
) -> list[int]:
    """De paar pagina's vlak vóór je uit, zodat de overlay er al staat als je
    omslaat."""
    if settings.translate_readahead_pages <= 0:
        return []
    return plan_pages(
        session,
        book,
        target_lang=target_lang,
        provider=provider,
        from_page=current_page,
        limit=settings.translate_readahead_pages,
    )
