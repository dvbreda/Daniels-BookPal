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
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.config import settings
from bookpal.images import ImageProfile, get_profile, open_source, render_page, source_id_for
from bookpal.models import Book, File, Series, Translation
from bookpal.translate import recolour, sidecar
from bookpal.translate.base import BubbleTranslator, PageResult, TranslationError
from bookpal.translate.imagepage import GeminiPageTranslator
from bookpal.translate.modes import BEST_FIRST, TranslateMode
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
    return render_for_translation_profile(session, book, page_index, get_profile(TRANSLATE_PROFILE))


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
    series = session.get(Series, book.series_id)
    path = sidecar.json_path(series, book, page_index, target_lang)

    if existing is not None and not force:
        # Zelfherstellend: staat het wel in de database maar niet op schijf
        # (vertaald toen de sidecar-map nog niet schrijfbaar was), dan zetten
        # we 'm er alsnog neer. Kost niets — de vertaling is al betaald.
        if not path.is_file():
            sidecar.write_json(path, existing.payload)
        return PageResult.from_payload(existing.payload)

    # Eerst op schijf kijken. Een vertaling die er al ligt opnieuw laten maken
    # is weggegooid geld — en na een herbouwde database ligt hij er wél nog.
    if not force:
        stored = sidecar.read_json(path)
        if stored is not None:
            result = PageResult.from_payload(stored)
            _record(session, book, page_index, target_lang, translator.provider, stored)
            return result

    image, media_type = render_for_translation(session, book, page_index)
    result = translator.translate_page(image, media_type=media_type, target_lang=target_lang)

    payload = result.to_payload()
    sidecar.write_json(path, payload)
    _record(session, book, page_index, target_lang, translator.provider, payload)
    return result


def _record(
    session: Session,
    book: Book,
    page_index: int,
    target_lang: str,
    provider: str,
    payload: dict[str, Any],
) -> Translation:
    row = find(session, book.id, page_index, target_lang, provider)
    if row is None:
        row = Translation(
            book_id=book.id,
            page_index=page_index,
            target_lang=target_lang,
            provider=provider,
        )
        session.add(row)
    row.payload = payload
    session.commit()
    return row


def translate_page_as_image(
    session: Session,
    translator: GeminiPageTranslator,
    book: Book,
    page_index: int,
    *,
    target_lang: str,
    mode: TranslateMode,
    force: bool = False,
) -> bytes:
    """Laat het beeldmodel de hele pagina hertekenen mét vertaling.

    Duur per pagina, dus de volgorde is: eerst kijken of hij er al ligt, en pas
    dan betalen. Het resultaat gaat naar de sidecar-map, want dát is wat je bij
    een herbouwde database niet opnieuw wilt aanschaffen.
    """
    series = session.get(Series, book.series_id)
    path = sidecar.image_path(series, book, page_index, target_lang, mode)

    if not force:
        stored = sidecar.read_bytes(path)
        if stored is not None:
            _record(
                session,
                book,
                page_index,
                target_lang,
                mode.provider,
                {"full_page": True, "model": translator.model},
            )
            return stored

    image, media_type = render_for_translation(session, book, page_index)
    produced = translator.translate_page(image, media_type=media_type, target_lang=target_lang)

    sidecar.write_bytes(path, produced)
    _record(
        session,
        book,
        page_index,
        target_lang,
        mode.provider,
        {"full_page": True, "model": translator.model},
    )
    return produced


#: Onder welke sleutel een ingekleurde pagina wordt bewaard. Bewust geen
#: TranslateMode: inkleuren is geen vertaling en mag er nooit voor doorgaan —
#: anders zou "de beste die er ligt" een ingekleurde pagina boven een vertaalde
#: kiezen.
COLOUR_PROVIDER = "gemini-color"
COLOUR_VARIANT = "kleur"


class AlreadyColour(TranslationError):
    """Deze pagina heeft al kleur van de tekenaar zelf.

    Een eigen soort omdat het geen storing is: er ging niets mis, het is alleen
    de vraag of je dit wel wilt. De lezer maakt er een bevestiging van en stuurt
    het desgewenst nog een keer met ``force``.
    """


def colour_variant(target_lang: str | None) -> str:
    """Onder welke naam een ingekleurde pagina wordt bewaard.

    Met taal erin als hij van een vertaalde pagina is gemaakt: dan zit de
    vertaalde tekst in het beeld gebakken, en een ingekleurde Nederlandse
    pagina is iets anders dan een ingekleurd origineel. Zonder dat onderscheid
    zou je met de vertaling uit alsnog Nederlandse tekst zien.
    """
    return f"{COLOUR_VARIANT}-{target_lang}" if target_lang else COLOUR_VARIANT


def colour_base(
    session: Session, book: Book, page_index: int, target_lang: str
) -> tuple[bytes, str, str | None]:
    """Wat er ingekleurd moet worden, en hoe het resultaat gaat heten.

    Ligt er al een hertekende vertaling, dan is díe de betere basis: je krijgt
    kleur en vertaalde tekst in één beeld, in plaats van onze witte vlakjes
    over een ingekleurde pagina heen. Anders het origineel.
    """
    gevonden = best_available(session, book, page_index, target_lang)
    if gevonden is not None:
        mode, _row = gevonden
        if mode.is_image:
            vertaald = read_page_image(session, book, page_index, target_lang, mode)
            if vertaald is not None:
                return vertaald, "image/webp", target_lang

    image, media_type = render_for_translation(session, book, page_index)
    return image, media_type, None


def recompose_to_webp(original: bytes, coloured: bytes) -> bytes:
    """Kleur van het model over ons eigen lijnwerk, klaar om te bewaren."""
    buffer = BytesIO()
    recolour.recompose(original, coloured).save(buffer, format="WEBP", quality=88, method=4)
    return buffer.getvalue()


def colorise_page(
    session: Session,
    translator: GeminiPageTranslator,
    book: Book,
    page_index: int,
    *,
    target_lang: str,
    force: bool = False,
) -> bytes:
    """Laat het beeldmodel deze pagina inkleuren.

    Dezelfde volgorde als bij het hertekenen: eerst kijken of hij er al ligt en
    pas dan betalen. Het resultaat gaat naar de sidecar-map, want dat is wat je
    bij een herbouwde database niet opnieuw wilt aanschaffen.
    """
    series = session.get(Series, book.series_id)
    basis, media_type, van_taal = colour_base(session, book, page_index, target_lang)
    variant = colour_variant(van_taal)
    path = sidecar.variant_path(series, book, page_index, variant)

    if not force:
        stored = sidecar.read_bytes(path)
        if stored is not None:
            _record(
                session,
                book,
                page_index,
                van_taal or "src",
                COLOUR_PROVIDER,
                {"model": translator.model},
            )
            return stored

        # Een pagina die de tekenaar zelf al kleurde wordt hier niet ingekleurd
        # maar overschilderd, en dat kost evenveel. Vragen dus.
        if recolour.is_colour(basis):
            raise AlreadyColour("deze pagina heeft al kleur; inkleuren vervangt het palet")

    # Alleen de kleur van het model gebruiken; het lijnwerk en de letters
    # houden we zelf vast. Zie recolour voor waarom dat nodig is.
    produced = recompose_to_webp(basis, translator.colorise_page(basis, media_type=media_type))

    sidecar.write_bytes(path, produced)
    _record(
        session, book, page_index, van_taal or "src", COLOUR_PROVIDER, {"model": translator.model}
    )
    return produced


def read_colour(
    session: Session, book: Book, page_index: int, target_lang: str | None = None
) -> bytes | None:
    """Een al ingekleurde pagina van schijf, of None.

    Met een taal erbij krijg je de versie die van de vertaalde pagina is
    gemaakt, als die er is. Zonder taal alleen het ingekleurde origineel — want
    met de vertaling uit hoor je geen Nederlandse tekst te zien.
    """
    series = session.get(Series, book.series_id)
    if target_lang:
        vertaald = sidecar.read_bytes(
            sidecar.variant_path(series, book, page_index, colour_variant(target_lang))
        )
        if vertaald is not None:
            return vertaald
    return sidecar.read_bytes(sidecar.variant_path(series, book, page_index, COLOUR_VARIANT))


def read_page_image(
    session: Session, book: Book, page_index: int, target_lang: str, mode: TranslateMode
) -> bytes | None:
    """Een al gemaakte hele-pagina-vertaling van schijf, of None."""
    series = session.get(Series, book.series_id)
    return sidecar.read_bytes(sidecar.image_path(series, book, page_index, target_lang, mode))


def best_available(
    session: Session, book: Book, page_index: int, target_lang: str
) -> tuple[TranslateMode, Translation] | None:
    """Wat er voor deze pagina klaarstaat, duurste eerst.

    Als je één pagina met de hand door het dure model hebt gehaald, wil je díe
    zien — ook als de schakelaar op de goedkope stand staat. Er is immers al
    voor betaald.
    """
    for mode in BEST_FIRST:
        row = find(session, book.id, page_index, target_lang, mode.provider)
        if row is None:
            continue
        return mode, row
    return None


def bubbles_for(session: Session, book: Book, page_index: int, target_lang: str) -> PageResult:
    """De tekstvlakken uit de goedkope stand — ook wat de hybride gebruikt."""
    row = find(session, book.id, page_index, target_lang, TranslateMode.TEXT.provider)
    return PageResult.from_payload(row.payload) if row is not None else PageResult()


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
