"""Bubbelvertaling (M8): wat er van een pagina gemaakt wordt, en wat de lezer
ermee kan als het misgaat."""

from __future__ import annotations

import io
import json
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from bookpal.config import settings as app_settings
from bookpal.models import Book, BookKind, Series, Translation
from bookpal.translate import sidecar
from bookpal.translate.base import Bubble, BubbleKind, PageResult, TranslationError
from bookpal.translate.gemini import GeminiBubbleTranslator, _to_bubble
from bookpal.translate.modes import BEST_FIRST, TranslateMode, from_provider
from bookpal.translate.overlay import _fit, _load_font, bake, draw_bubbles, render_layer
from bookpal.translate.preferences import get_mode, set_mode
from bookpal.translate.queue import TranslationQueue
from bookpal.translate.service import (
    find,
    plan_pages,
    render_for_translation,
    translate_page,
    translated_pages,
)
from tests.fixtures import make_cbz


def _reply(items: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": json.dumps(items)}]}}]},
    )


def _translator(handler) -> GeminiBubbleTranslator:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test")
    return GeminiBubbleTranslator("sleutel", client=client, rate=1000.0)


def _png(width: int = 40, height: int = 60) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class TestBubbleParsing:
    def test_gemini_coordinates_become_normalised_xy(self):
        """Gemini geeft [ymin, xmin, ymax, xmax] op 0..1000; wij bewaren
        [x0, y0, x1, y1] op 0..1."""
        bubble = _to_bubble(
            {"box_2d": [100, 200, 300, 400], "source": "A", "translation": "B", "kind": "speech"}
        )
        assert bubble is not None
        assert (bubble.x0, bubble.y0, bubble.x1, bubble.y1) == (0.2, 0.1, 0.4, 0.3)

    def test_swapped_corners_are_sorted_not_dropped(self):
        bubble = _to_bubble({"box_2d": [300, 400, 100, 200], "translation": "B"})
        assert bubble is not None
        assert bubble.x0 < bubble.x1 and bubble.y0 < bubble.y1

    def test_a_bubble_without_translation_is_skipped(self):
        assert _to_bubble({"box_2d": [0, 0, 10, 10], "source": "A", "translation": "  "}) is None

    def test_a_bubble_without_a_box_is_skipped(self):
        assert _to_bubble({"translation": "B"}) is None

    def test_a_zero_size_box_is_skipped(self):
        assert _to_bubble({"box_2d": [10, 10, 10, 10], "translation": "B"}) is None

    def test_an_unknown_kind_falls_back_to_speech(self):
        bubble = _to_bubble({"box_2d": [0, 0, 10, 10], "translation": "B", "kind": "gekrijs"})
        assert bubble is not None
        assert bubble.kind is BubbleKind.SPEECH

    def test_coordinates_are_clamped_to_the_page(self):
        bubble = _to_bubble({"box_2d": [-50, -50, 1200, 1200], "translation": "B"})
        assert bubble is not None
        assert (bubble.x0, bubble.y0) == (0.0, 0.0)
        assert (bubble.x1, bubble.y1) == (1.0, 1.0)


class TestGeminiTranslator:
    def test_a_page_becomes_bubbles(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _reply(
                [
                    {"box_2d": [0, 0, 100, 100], "source": "HI", "translation": "HOI"},
                    {"box_2d": [200, 200, 300, 300], "source": "BYE", "translation": "DOEI"},
                ]
            )

        result = _translator(handler).translate_page(b"x", media_type="image/png", target_lang="nl")
        assert [b.translation for b in result.bubbles] == ["HOI", "DOEI"]

    def test_the_model_name_is_recorded(self):
        result = _translator(lambda r: _reply([])).translate_page(
            b"x", media_type="image/png", target_lang="nl"
        )
        assert result.model == "gemini-3-flash-preview"

    def test_a_page_without_text_is_not_an_error(self):
        """Een splash-pagina zonder tekst hoort een leeg resultaat te geven,
        geen fout — anders blijft de wachtrij het eeuwig proberen."""
        result = _translator(lambda r: _reply([])).translate_page(
            b"x", media_type="image/png", target_lang="nl"
        )
        assert result.bubbles == []

    def test_a_wrapped_list_is_accepted(self):
        def handler(request: httpx.Request) -> httpx.Response:
            payload = {"bubbles": [{"box_2d": [0, 0, 10, 10], "translation": "HOI"}]}
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
            )

        result = _translator(handler).translate_page(b"x", media_type="image/png", target_lang="nl")
        assert len(result.bubbles) == 1

    def test_one_broken_bubble_does_not_lose_the_rest(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _reply(
                [
                    {"box_2d": "onzin", "translation": "X"},
                    {"box_2d": [0, 0, 100, 100], "translation": "GOED"},
                ]
            )

        result = _translator(handler).translate_page(b"x", media_type="image/png", target_lang="nl")
        assert [b.translation for b in result.bubbles] == ["GOED"]

    def test_rate_limit_is_reported_clearly(self):
        with pytest.raises(TranslationError, match="rate limit"):
            _translator(lambda r: httpx.Response(429)).translate_page(
                b"x", media_type="image/png", target_lang="nl"
            )

    def test_invalid_json_is_an_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "geen json"}]}}]}
            )

        with pytest.raises(TranslationError, match="geldige JSON"):
            _translator(handler).translate_page(b"x", media_type="image/png", target_lang="nl")

    def test_a_blocked_response_is_an_error_not_a_crash(self):
        with pytest.raises(TranslationError, match="geen antwoord"):
            _translator(lambda r: httpx.Response(200, json={})).translate_page(
                b"x", media_type="image/png", target_lang="nl"
            )

    def test_no_key_is_refused_at_construction(self):
        with pytest.raises(TranslationError, match="geen Gemini-sleutel"):
            GeminiBubbleTranslator("")

    def test_the_target_language_reaches_the_prompt(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return _reply([])

        _translator(handler).translate_page(b"x", media_type="image/png", target_lang="nl")
        prompt = seen["contents"][0]["parts"][0]["text"]
        assert "Nederlands" in prompt


class TestOverlay:
    def test_text_stays_inside_its_box(self):
        """Dit ging mis op de eerste ingebakken pagina: _fit keek alleen naar
        de hoogte, dus een woord dat langer was dan het vlak stak er dwars
        overheen."""
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        font, lines, _ = _fit(draw, "BEDRIJFSFILOSOFIE.", 60.0, 40.0)
        assert max(draw.textlength(line, font=font) for line in lines) <= 60.0

    def test_bold_and_italic_select_different_font_files(self):
        """Zonder dit ziet een nadruk in de brontekst er in de vertaling
        precies hetzelfde uit als de rest van de ballon."""
        regular = _load_font(24)
        bold = _load_font(24, bold=True)
        italic = _load_font(24, italic=True)
        bold_italic = _load_font(24, bold=True, italic=True)
        paths = {getattr(f, "path", None) for f in (regular, bold, italic, bold_italic)}
        assert len(paths) == 4, paths

    def test_whole_words_are_preferred_over_hard_breaks(self):
        """Liever een maat kleiner dan "BESCHIKBA/AR." middenin een woord."""
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        _font, lines, _ = _fit(draw, "ANDERE GERECHTEN ZIJN BESCHIKBAAR.", 90.0, 120.0)
        assert lines == ["ANDERE", "GERECHTEN", "ZIJN", "BESCHIKBAAR."]

    def test_a_word_that_never_fits_is_broken_as_a_last_resort(self):
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        _font, lines, _ = _fit(draw, "BEDRIJFSFILOSOFIE.", 24.0, 200.0)
        assert len(lines) > 1
        assert "".join(lines) == "BEDRIJFSFILOSOFIE."

    def test_a_grayscale_page_stays_grayscale(self):
        """De Kobo-profielen leveren geditherde grijswaarden; die naar RGB
        tillen gooit precies het werk weg waar dat profiel voor bestaat."""
        page = Image.new("L", (100, 100), 200)
        result = draw_bubbles(page, [Bubble(0.1, 0.1, 0.9, 0.5, "HI", "HOI")])
        assert result.mode == "L"

    def test_the_layer_is_transparent_where_there_is_no_bubble(self):
        """Het hele punt van een losse laag: de pagina eronder moet zichtbaar
        blijven waar geen tekst staat."""
        data = render_layer((60, 60), [Bubble(0.0, 0.0, 0.4, 0.4, "HI", "HOI")])
        with Image.open(BytesIO(data)) as layer:
            assert layer.mode == "RGBA"
            assert layer.getpixel((55, 55))[3] == 0  # rechtsonder: niets getekend
            assert layer.getpixel((5, 5))[3] == 255  # in de ballon: dekkend

    def test_the_layer_has_the_size_it_was_asked_for(self):
        data = render_layer((123, 45), [])
        with Image.open(BytesIO(data)) as layer:
            assert layer.size == (123, 45)

    def test_a_layer_without_bubbles_is_fully_transparent(self):
        data = render_layer((20, 20), [])
        with Image.open(BytesIO(data)) as layer:
            assert layer.getextrema()[3] == (0, 0)

    def test_the_layer_is_much_smaller_than_the_page(self):
        """De reden om een laag te sturen in plaats van de pagina opnieuw: hij
        kost een fractie van de bytes.

        Met een geruisde pagina in plaats van een egaal wit vlak, want dat
        laatste comprimeert tot een paar kilobyte en is dus geen eerlijke maat
        voor een echte scan.
        """
        import random

        ruis = Image.new("RGB", (800, 1200))
        willekeurig = random.Random(1)
        ruis.putdata(
            [
                (willekeurig.randrange(256), willekeurig.randrange(256), willekeurig.randrange(256))
                for _ in range(800 * 1200)
            ]
        )
        buffer = BytesIO()
        ruis.save(buffer, format="PNG")
        page = buffer.getvalue()

        layer = render_layer((800, 1200), [Bubble(0.1, 0.1, 0.4, 0.2, "HI", "HOI")])
        assert len(layer) < len(page) / 10

    def test_baking_keeps_the_format(self):
        data = bake(_png(), [Bubble(0.1, 0.1, 0.9, 0.5, "HI", "HOI")], media_type="image/png")
        with Image.open(BytesIO(data)) as image:
            assert image.format == "PNG"

    def test_baking_changes_the_pixels(self):
        original = _png()
        baked = bake(original, [Bubble(0.1, 0.1, 0.9, 0.5, "HI", "HOI")], media_type="image/png")
        assert baked != original

    def test_no_bubbles_means_no_work(self):
        page = Image.new("RGB", (20, 20), "white")
        assert draw_bubbles(page, []) is page

    def test_an_empty_translation_is_not_drawn(self):
        page = Image.new("L", (60, 60), 128)
        result = draw_bubbles(page.copy(), [Bubble(0.1, 0.1, 0.9, 0.9, "HI", "   ")])
        assert result.tobytes() == page.tobytes()


def _comic(session: Session, pages: int = 5) -> Book:
    series = Series(title="Reeks", sort_title="reeks")
    session.add(series)
    session.flush()
    book = Book(series_id=series.id, kind=BookKind.COMIC, title="Deel", page_count=pages)
    session.add(book)
    session.flush()
    return book


def _store(session: Session, book: Book, page_index: int, lang: str = "nl") -> None:
    session.add(
        Translation(
            book_id=book.id,
            page_index=page_index,
            target_lang=lang,
            provider="gemini",
            payload=PageResult(bubbles=[]).to_payload(),
        )
    )
    session.flush()


class TestService:
    def test_translated_pages_only_counts_this_language(self, session: Session):
        book = _comic(session)
        _store(session, book, 0, "nl")
        _store(session, book, 1, "de")
        assert translated_pages(session, book.id, "nl", "gemini") == {0}

    def test_plan_skips_what_is_already_done(self, session: Session):
        book = _comic(session, pages=4)
        _store(session, book, 1)
        assert plan_pages(session, book, target_lang="nl", provider="gemini") == [0, 2, 3]

    def test_plan_starts_where_you_are_reading(self, session: Session):
        """Net als het vooruitlezen van M5: wat je al voorbij bent hoeft niet
        meer vertaald te worden."""
        book = _comic(session, pages=6)
        assert plan_pages(session, book, target_lang="nl", provider="gemini", from_page=3) == [
            3,
            4,
            5,
        ]

    def test_plan_respects_the_limit(self, session: Session):
        book = _comic(session, pages=10)
        planned = plan_pages(session, book, target_lang="nl", provider="gemini", limit=2)
        assert planned == [0, 1]

    def test_a_book_without_pages_plans_nothing(self, session: Session):
        book = _comic(session)
        book.page_count = None
        session.flush()
        assert plan_pages(session, book, target_lang="nl", provider="gemini") == []

    def test_a_cached_page_is_not_translated_again(self, session: Session):
        book = _comic(session)
        _store(session, book, 0)
        calls = []

        class Counting(GeminiBubbleTranslator):
            def translate_page(self, image, *, media_type, target_lang):  # type: ignore[override]
                calls.append(1)
                return PageResult()

        translator = Counting("sleutel", client=httpx.Client(base_url="https://test"))
        translate_page(session, translator, book, 0, target_lang="nl")
        assert calls == []

    def test_a_book_without_a_file_fails_clearly(self, session: Session):
        book = _comic(session)
        translator = GeminiBubbleTranslator("sleutel", client=httpx.Client(base_url="https://x"))
        with pytest.raises(TranslationError, match="lokaal bestand"):
            translate_page(session, translator, book, 0, target_lang="nl")


class TestQueue:
    def test_pages_are_queued_once(self):
        queue = TranslationQueue()
        assert queue.submit(1, [0, 1, 2], "nl") == 3
        assert queue.submit(1, [1, 2, 3], "nl") == 1
        assert queue.pending == 4

    def test_a_higher_priority_wins_for_an_already_queued_page(self):
        """Als je naar een pagina toe leest die al achteraan stond, moet hij
        naar voren — niet nog een keer in de rij."""
        queue = TranslationQueue()
        queue.submit(1, [5], "nl", priority=5)
        queue.submit(1, [5], "nl", priority=1)
        assert queue.pending == 1
        assert queue._jobs[0].priority == 1

    def test_the_queue_is_sorted_by_priority(self):
        queue = TranslationQueue()
        queue.submit(1, [9], "nl", priority=5)
        queue.submit(1, [2], "nl", priority=1)
        assert queue._jobs[0].page_index == 2

    def test_pending_for_counts_only_that_book(self):
        queue = TranslationQueue()
        queue.submit(1, [0, 1], "nl")
        queue.submit(2, [0], "nl")
        assert queue.pending_for(1) == 2
        assert queue.pending_for(2) == 1

    def test_the_page_being_worked_on_still_counts_as_pending(self):
        """Anders meldt de lezer "klaar" terwijl er nog een pagina onderweg is:
        die is dan al uit de rij gehaald maar nog niet opgeslagen."""
        queue = TranslationQueue()
        queue.submit(1, [0], "nl")
        assert queue._take() is not None
        assert queue._jobs == []
        assert queue.pending_for(1) == 1
        assert queue.pending == 1

    def test_another_book_is_not_counted_as_pending(self):
        queue = TranslationQueue()
        queue.submit(1, [0], "nl")
        queue._take()
        assert queue.pending_for(2) == 0

    def test_a_disabled_queue_starts_no_thread(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(app_settings, "translations_enabled", False)
        queue = TranslationQueue()
        queue.start()
        assert queue._thread is None


def _comic_id(client: TestClient) -> int:
    """Een strip, geen epub: die laatste heeft geen vaste pagina's."""
    items = client.get("/api/books").json()["items"]
    return int(next(item for item in items if item["kind"] == "comic")["id"])


class TestApi:
    def test_an_untranslated_page_is_a_404(self, scanned: TestClient):
        book_id = _comic_id(scanned)
        assert scanned.get(f"/api/books/{book_id}/pages/0/translation").status_code == 404

    def test_translating_without_a_key_is_refused_clearly(self, scanned: TestClient):
        book_id = _comic_id(scanned)
        response = scanned.post(f"/api/books/{book_id}/pages/0/translation")
        assert response.status_code == 409
        assert "BOOKPAL_GEMINI_API_KEY" in response.json()["detail"]

    def test_status_reports_that_nothing_is_configured(self, scanned: TestClient):
        book_id = _comic_id(scanned)
        body = scanned.get(f"/api/books/{book_id}/translation-status").json()
        assert body["configured"] is False
        assert body["translated"] == 0

    def test_status_counts_what_is_stored(self, scanned: TestClient, session: Session):
        book_id = _comic_id(scanned)
        book = session.get(Book, book_id)
        assert book is not None
        _store(session, book, 0)
        session.commit()
        body = scanned.get(f"/api/books/{book_id}/translation-status").json()
        assert body["translated"] == 1

    def test_a_stored_translation_comes_back(self, scanned: TestClient, session: Session):
        book_id = _comic_id(scanned)
        row = Translation(
            book_id=book_id,
            page_index=0,
            target_lang="nl",
            provider="gemini",
            payload=PageResult(
                bubbles=[Bubble(0.1, 0.2, 0.3, 0.4, "HI", "HOI", bold=True, italic=True)],
                model="test",
            ).to_payload(),
        )
        session.add(row)
        session.commit()

        body = scanned.get(f"/api/books/{book_id}/pages/0/translation").json()
        assert body["model"] == "test"
        # Dit ging eerder mis: bold/italic werden wel opgeslagen maar
        # BubbleOut liet ze onder de tafel vallen bij het teruggeven.
        assert body["bubbles"][0]["bold"] is True
        assert body["bubbles"][0]["italic"] is True
        assert body["bubbles"][0]["translation"] == "HOI"
        assert body["bubbles"][0]["box"] == [0.1, 0.2, 0.3, 0.4]

    def test_a_page_without_a_translation_serves_the_original(
        self, scanned: TestClient, session: Session
    ):
        """De lezer mag nooit blokkeren op een vertaling die er nog niet is."""
        book_id = _comic_id(scanned)
        plain = scanned.get(f"/api/books/{book_id}/pages/0")
        asked = scanned.get(f"/api/books/{book_id}/pages/0", params={"translate": "nl"})
        assert asked.status_code == 200
        assert asked.content == plain.content

    def test_asking_for_a_translated_page_bakes_it_in(self, scanned: TestClient, session: Session):
        book_id = _comic_id(scanned)
        session.add(
            Translation(
                book_id=book_id,
                page_index=0,
                target_lang="nl",
                provider="gemini",
                payload=PageResult(bubbles=[Bubble(0.1, 0.1, 0.9, 0.5, "HI", "HOI")]).to_payload(),
            )
        )
        session.commit()

        plain = scanned.get(f"/api/books/{book_id}/pages/0")
        baked = scanned.get(f"/api/books/{book_id}/pages/0", params={"translate": "nl"})
        assert baked.status_code == 200
        assert baked.content != plain.content

    def test_the_overlay_is_a_png_the_size_of_the_page(self, scanned: TestClient, session: Session):
        book_id = _comic_id(scanned)
        session.add(
            Translation(
                book_id=book_id,
                page_index=0,
                target_lang="nl",
                provider="gemini",
                payload=PageResult(bubbles=[Bubble(0.1, 0.1, 0.9, 0.5, "HI", "HOI")]).to_payload(),
            )
        )
        session.commit()

        page = scanned.get(f"/api/books/{book_id}/pages/0")
        overlay = scanned.get(f"/api/books/{book_id}/pages/0/overlay")
        assert overlay.status_code == 200
        assert overlay.headers["content-type"] == "image/png"
        with Image.open(BytesIO(page.content)) as a, Image.open(BytesIO(overlay.content)) as b:
            assert a.size == b.size
            assert b.mode == "RGBA"

    def test_an_untranslated_overlay_is_a_404(self, scanned: TestClient):
        """Niet een lege laag: de client moet weten dat er niets te tonen is."""
        book_id = _comic_id(scanned)
        assert scanned.get(f"/api/books/{book_id}/pages/0/overlay").status_code == 404

    def test_the_overlay_follows_the_profile(self, scanned: TestClient, session: Session):
        """Anders past de laag niet over een Kobo-pagina van een andere maat."""
        book_id = _comic_id(scanned)
        session.add(
            Translation(
                book_id=book_id,
                page_index=0,
                target_lang="nl",
                provider="gemini",
                payload=PageResult(bubbles=[Bubble(0.1, 0.1, 0.9, 0.5, "A", "B")]).to_payload(),
            )
        )
        session.commit()

        for profile in ("web", "thumb"):
            page = scanned.get(f"/api/books/{book_id}/pages/0", params={"profile": profile})
            overlay = scanned.get(
                f"/api/books/{book_id}/pages/0/overlay", params={"profile": profile}
            )
            with Image.open(BytesIO(page.content)) as a, Image.open(BytesIO(overlay.content)) as b:
                assert a.size == b.size, profile

    def test_queueing_a_book_without_a_key_is_refused(self, scanned: TestClient):
        book_id = _comic_id(scanned)
        response = scanned.post(f"/api/books/{book_id}/translate", json={})
        assert response.status_code == 409


class TestBubbleStyle:
    def test_all_caps_source_is_detected(self):
        assert Bubble(0, 0, 1, 1, "IT LOOKS DELICIOUS!", "x").upper is True

    def test_mixed_case_source_is_not_upper(self):
        assert Bubble(0, 0, 1, 1, "It looks delicious!", "x").upper is False

    def test_a_single_letter_is_not_enough_to_call_it_upper(self):
        """'A' of een geluidseffect met één letter zegt niets over de lettering
        van de rest van de ballon."""
        assert Bubble(0, 0, 1, 1, "A!", "x").upper is False

    def test_bold_and_italic_are_parsed_from_gemini(self):
        bubble = _to_bubble(
            {"box_2d": [0, 0, 10, 10], "translation": "X", "bold": True, "italic": True}
        )
        assert bubble is not None
        assert bubble.bold is True
        assert bubble.italic is True

    def test_bold_and_italic_default_to_false(self):
        bubble = _to_bubble({"box_2d": [0, 0, 10, 10], "translation": "X"})
        assert bubble is not None
        assert bubble.bold is False
        assert bubble.italic is False


class TestPayloadRoundTrip:
    def test_a_bubble_survives_storage(self):
        original = Bubble(0.1, 0.2, 0.3, 0.4, "HI", "HOI", BubbleKind.CAPTION)
        assert Bubble.from_payload(original.to_payload()) == original

    def test_bold_and_italic_survive_storage(self):
        original = Bubble(0.1, 0.2, 0.3, 0.4, "HI", "HOI", bold=True, italic=True)
        restored = Bubble.from_payload(original.to_payload())
        assert restored.bold is True
        assert restored.italic is True

    def test_a_page_result_survives_storage(self):
        original = PageResult(
            bubbles=[Bubble(0.1, 0.2, 0.3, 0.4, "HI", "HOI")], source_lang="en", model="m"
        )
        restored = PageResult.from_payload(original.to_payload())
        assert restored == original

    def test_an_empty_payload_is_harmless(self):
        assert PageResult.from_payload({}).bubbles == []


def test_the_translation_is_found_by_its_own_language(session: Session, tmp_path: Path):
    book = _comic(session)
    _store(session, book, 0, "nl")
    assert find(session, book.id, 0, "nl", "gemini") is not None
    assert find(session, book.id, 0, "de", "gemini") is None


class TestModes:
    def test_each_mode_has_its_own_storage_key(self):
        """Een pagina die met het goedkope beeldmodel is gedaan mag niet
        doorgaan voor een pagina die met het dure model is gedaan."""
        providers = {mode.provider for mode in TranslateMode}
        assert len(providers) == len(list(TranslateMode))

    def test_only_the_image_modes_are_image(self):
        assert TranslateMode.TEXT.is_image is False
        assert TranslateMode.IMAGE_FAST.is_image is True
        assert TranslateMode.IMAGE_PRO.is_image is True

    def test_provider_round_trips(self):
        for mode in TranslateMode:
            assert from_provider(mode.provider) is mode

    def test_best_first_prefers_the_expensive_one(self):
        """Er is al voor betaald, dus die hoort te winnen."""
        assert BEST_FIRST[0] is TranslateMode.IMAGE_PRO
        assert BEST_FIRST[-1] is TranslateMode.TEXT
        assert set(BEST_FIRST) == set(TranslateMode)

    def test_only_the_text_mode_uses_our_own_bubbles(self):
        assert TranslateMode.TEXT.needs_bubbles is True
        assert TranslateMode.IMAGE_FAST.needs_bubbles is False
        assert TranslateMode.IMAGE_PRO.needs_bubbles is False


class TestModePreference:
    def test_the_default_is_the_cheap_mode(self, session: Session):
        """Een dure stand hoort nooit de standaard te zijn die je per ongeluk
        aan laat staan."""
        assert get_mode(session) is TranslateMode.TEXT

    def test_a_chosen_mode_survives(self, session: Session):
        set_mode(session, TranslateMode.IMAGE_PRO)
        assert get_mode(session) is TranslateMode.IMAGE_PRO

    def test_a_corrupt_setting_falls_back_to_cheap(self, session: Session):
        from bookpal.models import Setting

        session.add(Setting(key="translate", value={"mode": "onzin"}))
        session.commit()
        assert get_mode(session) is TranslateMode.TEXT


class TestSidecar:
    def test_the_path_sits_next_to_the_series(self, session: Session, temp_settings):
        """Naast de serie in je eigen bibliotheek, in een verborgen map."""
        series = Series(title="Shinya Shokudo", sort_title="shinya")
        session.add(series)
        session.flush()
        book = Book(series_id=series.id, kind=BookKind.COMIC, title="Deel", number="03")
        session.add(book)
        session.flush()

        path = sidecar.json_path(series, book, 7, "nl")
        assert "Shinya Shokudo" in str(path)
        assert sidecar.SIDECAR_DIRNAME in path.parts
        assert path.parent.name == "c003", "nullen ervoor, zodat ls op volgorde staat"
        assert path.name == "p0007-nl.json"

    def test_unsafe_characters_are_stripped(self, session: Session):
        series = Series(title='Hij/Zij: "raar"', sort_title="x")
        session.add(series)
        session.flush()
        book = Book(series_id=series.id, kind=BookKind.COMIC, title="a/b")
        session.add(book)
        session.flush()

        path = sidecar.json_path(series, book, 0, "nl")
        assert "/" not in path.parent.name
        assert '"' not in str(path)

    def test_image_paths_differ_per_mode(self, session: Session):
        series = Series(title="S", sort_title="s")
        session.add(series)
        session.flush()
        book = Book(series_id=series.id, kind=BookKind.COMIC, title="H")
        session.add(book)
        session.flush()

        fast = sidecar.image_path(series, book, 1, "nl", TranslateMode.IMAGE_FAST)
        pro = sidecar.image_path(series, book, 1, "nl", TranslateMode.IMAGE_PRO)
        assert fast != pro

    def test_a_written_payload_comes_back(self, tmp_path: Path):
        path = tmp_path / "diep" / "p0001-nl.json"
        sidecar.write_json(path, {"bubbles": [], "model": "m"})
        assert sidecar.read_json(path) == {"bubbles": [], "model": "m"}

    def test_a_corrupt_sidecar_is_ignored_not_fatal(self, tmp_path: Path):
        path = tmp_path / "stuk.json"
        path.write_text("{ dit is geen json", encoding="utf-8")
        assert sidecar.read_json(path) is None

    def test_a_missing_sidecar_is_none(self, tmp_path: Path):
        assert sidecar.read_json(tmp_path / "bestaat-niet.json") is None
        assert sidecar.read_bytes(tmp_path / "bestaat-niet.webp") is None


class TestSidecarPersistence:
    def _book_with_page(self, session: Session) -> Book:
        series = Series(title="Reeks", sort_title="reeks")
        session.add(series)
        session.flush()
        book = Book(series_id=series.id, kind=BookKind.COMIC, title="Deel", page_count=3)
        session.add(book)
        session.flush()
        return book

    def test_a_database_hit_backfills_a_missing_sidecar(
        self, session: Session, temp_settings: Path
    ):
        """Pagina's die vertaald zijn toen de sidecar-map nog niet schrijfbaar
        was, horen er alsnog te komen: de vertaling is al betaald."""
        book = self._book_with_page(session)
        payload = PageResult(bubbles=[Bubble(0.1, 0.1, 0.5, 0.5, "HI", "HOI")]).to_payload()
        session.add(
            Translation(
                book_id=book.id,
                page_index=0,
                target_lang="nl",
                provider="gemini",
                payload=payload,
            )
        )
        session.commit()

        series = session.get(Series, book.series_id)
        path = sidecar.json_path(series, book, 0, "nl")
        assert not path.is_file()

        calls: list[int] = []

        class Counting(GeminiBubbleTranslator):
            def translate_page(self, image, *, media_type, target_lang):  # type: ignore[override]
                calls.append(1)
                return PageResult()

        translator = Counting("sleutel", client=httpx.Client(base_url="https://test"))
        translate_page(session, translator, book, 0, target_lang="nl")

        assert calls == []  # niet opnieuw betaald
        assert path.is_file()  # wel alsnog bewaard

    def test_a_sidecar_is_used_instead_of_calling_again(
        self, session: Session, temp_settings: Path
    ):
        """Na een herbouwde database staat het nog op schijf; dan mag er geen
        nieuwe aanroep uitgaan."""
        book = self._book_with_page(session)
        series = session.get(Series, book.series_id)
        path = sidecar.json_path(series, book, 1, "nl")
        sidecar.write_json(
            path, PageResult(bubbles=[Bubble(0.2, 0.2, 0.6, 0.6, "A", "B")]).to_payload()
        )

        calls: list[int] = []

        class Counting(GeminiBubbleTranslator):
            def translate_page(self, image, *, media_type, target_lang):  # type: ignore[override]
                calls.append(1)
                return PageResult()

        translator = Counting("sleutel", client=httpx.Client(base_url="https://test"))
        result = translate_page(session, translator, book, 1, target_lang="nl")

        assert calls == []
        assert [b.translation for b in result.bubbles] == ["B"]
        # En de database is bijgewerkt, zodat de statusteller weer klopt.
        assert find(session, book.id, 1, "nl", "gemini") is not None


class TestTwoTranslateModes:
    """Vanzelf mag goedkoop zijn, de knop mag duur zijn.

    Dat zijn twee losse keuzes: de wachtrij loopt zonder dat je erom vraagt, en
    als jij zelf op een pagina drukt is dat juist omdat díé pagina het waard is.
    """

    def test_they_start_apart(self, client: TestClient):
        body = client.get("/api/translate/mode").json()
        assert body["mode"] == "text", "vanzelf hoort goedkoop te zijn"
        assert body["button_mode"] == "image_fast", "de knop een stap hoger"

    def test_setting_one_leaves_the_other_alone(self, client: TestClient):
        client.put("/api/translate/mode", json={"button_mode": "image_pro"})
        body = client.get("/api/translate/mode").json()
        assert body["button_mode"] == "image_pro"
        assert body["mode"] == "text"

        client.put("/api/translate/mode", json={"mode": "image_fast"})
        body = client.get("/api/translate/mode").json()
        assert body["mode"] == "image_fast"
        assert body["button_mode"] == "image_pro", "de knopstand bleef staan"

    def test_an_unknown_mode_is_refused(self, client: TestClient):
        response = client.put("/api/translate/mode", json={"button_mode": "gratis"})
        assert response.status_code == 400

    def test_sending_nothing_changes_nothing(self, client: TestClient):
        voor = client.get("/api/translate/mode").json()
        na = client.put("/api/translate/mode", json={}).json()
        assert na["mode"] == voor["mode"]
        assert na["button_mode"] == voor["button_mode"]


class TestColourising:
    """Inkleuren is geen vertaling en mag er nooit voor doorgaan.

    Zou het als vertaalstand meetellen, dan zou "de beste die er ligt" een
    ingekleurde pagina boven een vertaalde kiezen — en dan lees je ineens weer
    de oorspronkelijke taal.
    """

    def test_grey_is_not_put_back(self):
        """Bij een vertaling hoort zwart-wit zwart-wit te blijven; hier juist niet."""
        from bookpal.translate.imagepage import _match_original

        grijs = Image.new("L", (40, 60), 200)
        buffer = BytesIO()
        grijs.save(buffer, format="PNG")

        gekleurd = Image.new("RGB", (40, 60), (200, 40, 40))
        uit = BytesIO()
        gekleurd.save(uit, format="PNG")

        # Op de pixels en niet op de modus: webp kent geen grijswaardenmodus,
        # dus alles komt als RGB terug. Waar het om gaat is of de kleur er nog
        # ín zit.
        def heeft_kleur(data: bytes) -> bool:
            with Image.open(BytesIO(data)) as beeld:
                rgb = beeld.convert("RGB")
                return any(
                    abs(r - g) > 12 or abs(g - b) > 12 for r, g, b in list(rgb.getdata())[:400]
                )

        assert heeft_kleur(_match_original(uit.getvalue(), buffer.getvalue(), keep_gray=False))
        assert not heeft_kleur(_match_original(uit.getvalue(), buffer.getvalue())), (
            "een vertaling houdt zich wél aan het zwart-wit van het origineel"
        )

    def test_the_size_still_follows_the_original(self):
        from bookpal.translate.imagepage import _match_original

        klein = BytesIO()
        Image.new("L", (40, 60), 200).save(klein, format="PNG")
        groot = BytesIO()
        Image.new("RGB", (80, 120), (10, 20, 30)).save(groot, format="PNG")

        uit = _match_original(groot.getvalue(), klein.getvalue(), keep_gray=False)
        with Image.open(BytesIO(uit)) as beeld:
            assert beeld.size == (40, 60)

    def test_it_is_stored_under_its_own_name(self, session: Session, temp_settings):
        """Naast de vertalingen, niet ertussen."""
        from bookpal.translate import sidecar
        from bookpal.translate.modes import TranslateMode
        from bookpal.translate.service import COLOUR_VARIANT

        boek = _comic(session)
        kleur = sidecar.variant_path(None, boek, 3, COLOUR_VARIANT)
        vertaald = sidecar.image_path(None, boek, 3, "nl", TranslateMode.IMAGE_PRO)
        assert kleur != vertaald
        assert "kleur" in kleur.name

    def test_a_colour_page_is_never_offered_as_a_translation(self, session: Session, temp_settings):
        from bookpal.models import Translation
        from bookpal.translate.service import COLOUR_PROVIDER, best_available

        boek = _comic(session)
        session.add(
            Translation(
                book_id=boek.id,
                page_index=0,
                target_lang="src",
                provider=COLOUR_PROVIDER,
                payload={"model": "gemini-3-pro-image"},
            )
        )
        session.commit()

        assert best_available(session, boek, 0, "nl") is None

    def test_asking_for_a_page_that_is_not_coloured_is_a_404(
        self, client: TestClient, session: Session
    ):
        boek = _comic(session)
        session.commit()
        response = client.get(f"/api/books/{boek.id}/pages/0/colour")
        assert response.status_code == 404


class TestColourAndTranslationTogether:
    """Eén keer inkleuren, en die kleur over elke vertaling.

    Eerder werd de hertekende vertaling zelf ingekleurd; dat werkte, maar
    maakte kleur taalgebonden — elke taal een nieuwe aanroep van tientallen
    centen voor dezelfde verf. Nu is de kleur taalloos en wordt de combinatie
    ter plekke berekend.
    """

    def _serie(self, session: Session, boek: Book) -> Series:
        gevonden = session.get(Series, boek.series_id)
        assert gevonden is not None
        return gevonden

    def _kleur(self, session: Session, boek: Book, kleur=(40, 160, 40)) -> None:
        from bookpal.translate.service import COLOUR_VARIANT

        plaat = io.BytesIO()
        Image.new("RGB", (40, 60), kleur).save(plaat, format="WEBP")
        sidecar.write_bytes(
            sidecar.variant_path(self._serie(session, boek), boek, 0, COLOUR_VARIANT),
            plaat.getvalue(),
        )

    def _hertekend(self, session: Session, boek: Book) -> None:
        from bookpal.models import Translation
        from bookpal.translate.modes import TranslateMode

        plaat = Image.new("RGB", (40, 60), (255, 255, 255))
        for x in range(40):
            plaat.putpixel((x, 30), (0, 0, 0))  # "tekst" op de vertaalde pagina
        buffer = io.BytesIO()
        plaat.save(buffer, format="WEBP", lossless=True)
        sidecar.write_bytes(
            sidecar.image_path(self._serie(session, boek), boek, 0, "nl", TranslateMode.IMAGE_PRO),
            buffer.getvalue(),
        )
        session.add(
            Translation(
                book_id=boek.id,
                page_index=0,
                target_lang="nl",
                provider=TranslateMode.IMAGE_PRO.provider,
                payload={"full_page": True, "model": "gemini-3-pro-image"},
            )
        )
        session.commit()

    def test_the_colour_page_is_language_free(self, session: Session, temp_settings):
        """Anders betaal je twee keer voor dezelfde verf."""
        from bookpal.translate.service import COLOUR_VARIANT, colour_variant

        assert colour_variant(None) == COLOUR_VARIANT

    def test_asking_with_a_language_builds_the_combination(self, session: Session, temp_settings):
        from bookpal.translate.service import colour_variant, read_colour

        boek = _comic(session)
        session.commit()
        self._kleur(session, boek)
        self._hertekend(session, boek)

        gemaakt = read_colour(session, boek, 0, "nl")
        assert gemaakt is not None
        # En hij wordt bewaard, zodat het rekenwerk eenmalig is.
        assert sidecar.variant_path(
            self._serie(session, boek), boek, 0, colour_variant("nl")
        ).is_file()

    def test_the_translated_text_survives(self, session: Session, temp_settings):
        """De letters komen van onze pagina, niet van de ingekleurde."""
        from bookpal.translate.service import read_colour

        boek = _comic(session)
        session.commit()
        self._kleur(session, boek)
        self._hertekend(session, boek)

        beeld = Image.open(io.BytesIO(read_colour(session, boek, 0, "nl"))).convert("RGB")
        rood, groen, blauw = beeld.getpixel((20, 30))
        assert max(rood, groen, blauw) < 60, "de zwarte regel hoort zwart te blijven"

    def test_colour_arrives_where_the_page_is_white(self, session: Session, temp_settings):
        from bookpal.translate.service import read_colour

        boek = _comic(session)
        session.commit()
        self._kleur(session, boek)
        self._hertekend(session, boek)

        beeld = Image.open(io.BytesIO(read_colour(session, boek, 0, "nl"))).convert("RGB")
        rood, groen, blauw = beeld.getpixel((20, 10))
        assert groen > rood and groen > blauw, "het groen van de verf hoort door te komen"

    def test_without_a_redrawn_page_you_get_the_plain_colour(self, session: Session, temp_settings):
        """Onze eigen tekstvlakken komen er in de lezer gewoon overheen."""
        from bookpal.translate.service import read_colour

        boek = _comic(session)
        session.commit()
        self._kleur(session, boek)

        assert read_colour(session, boek, 0, "nl") is not None

    def test_nothing_coloured_means_nothing(self, session: Session, temp_settings):
        from bookpal.translate.service import read_colour

        boek = _comic(session)
        session.commit()
        self._hertekend(session, boek)

        assert read_colour(session, boek, 0, "nl") is None
        assert read_colour(session, boek, 0) is None


class TestRecompose:
    """De kleur komt van het model, het lijnwerk van ons."""

    def _bytes(self, image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_our_ink_stays_black(self):
        """Het model levert de inkt zachter terug dan hij erin ging."""
        from bookpal.translate.recolour import recompose

        pagina = Image.new("RGB", (20, 20), (255, 255, 255))
        pagina.putpixel((5, 5), (0, 0, 0))
        verzacht = Image.new("RGB", (20, 20), (255, 255, 255))
        verzacht.putpixel((5, 5), (120, 120, 120))

        samen = recompose(self._bytes(pagina), self._bytes(verzacht))
        assert samen.getpixel((5, 5)) == (0, 0, 0)

    def test_the_colour_comes_from_the_painted_version(self):
        from bookpal.translate.recolour import recompose

        pagina = Image.new("RGB", (20, 20), (200, 200, 200))
        geverfd = Image.new("RGB", (20, 20), (200, 60, 60))

        rood, groen, blauw = recompose(self._bytes(pagina), self._bytes(geverfd)).getpixel((1, 1))
        assert rood > groen and rood > blauw, "de tint hoort van de verf te komen"

    def test_a_wash_darker_than_the_paper_is_kept(self):
        """Anders verdwijnt juist de schaduw die aquarel zijn textuur geeft."""
        from bookpal.translate.recolour import recompose

        pagina = Image.new("RGB", (20, 20), (255, 255, 255))
        wassing = Image.new("RGB", (20, 20), (160, 190, 160))

        rood, _groen, _blauw = recompose(self._bytes(pagina), self._bytes(wassing)).getpixel((1, 1))
        assert rood < 255, "de wassing hoort donkerder te blijven dan het papier"

    def test_a_different_size_is_scaled_to_the_page(self):
        from bookpal.translate.recolour import recompose

        pagina = Image.new("RGB", (30, 40), (255, 255, 255))
        verf = Image.new("RGB", (60, 80), (200, 60, 60))

        assert recompose(self._bytes(pagina), self._bytes(verf)).size == (30, 40)


def _colour_book(session: Session, tmp_path: Path) -> Book:
    """Een boek waarvan de eerste pagina al kleur van de tekenaar heeft."""
    import zipfile

    from bookpal.models import File, LibraryRoot

    pad = tmp_path / "kleurstrip.cbz"
    plaat = io.BytesIO()
    Image.new("RGB", (60, 90), (200, 40, 40)).save(plaat, format="PNG")
    with zipfile.ZipFile(pad, "w") as archief:
        for nummer in range(3):
            archief.writestr(f"{nummer + 1:03d}.png", plaat.getvalue())

    boek = _comic(session, pages=3)
    root = LibraryRoot(name="R", path=str(tmp_path))
    session.add(root)
    session.flush()
    bestand = File(
        library_root_id=root.id,
        path=str(pad),
        size=pad.stat().st_size,
        mtime=0.0,
        extension=".cbz",
    )
    session.add(bestand)
    session.flush()
    boek.file_id = bestand.id
    session.commit()
    return boek


class TestAlreadyColour:
    """Een pagina die de tekenaar zelf kleurde wordt overschilderd, niet ingekleurd."""

    def _bytes(self, image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_a_black_and_white_page_is_not_colour(self):
        from bookpal.translate.recolour import is_colour

        pagina = Image.new("RGB", (60, 60), (255, 255, 255))
        for x in range(60):
            pagina.putpixel((x, 30), (0, 0, 0))
        assert is_colour(self._bytes(pagina)) is False

    def test_yellowed_paper_is_not_colour(self):
        """Anders zou elke oude scan als kleurpagina gelden."""
        from bookpal.translate.recolour import is_colour

        assert is_colour(self._bytes(Image.new("RGB", (60, 60), (240, 228, 200)))) is False

    def test_a_two_tone_page_counts_as_colour(self):
        """Bewust: liever een vraag te veel dan een palet stilletjes vervangen."""
        from bookpal.translate.recolour import is_colour

        pagina = Image.new("RGB", (60, 60), (255, 255, 255))
        for y in range(30):
            for x in range(60):
                pagina.putpixel((x, y), (200, 30, 30))
        assert is_colour(self._bytes(pagina)) is True

    def test_colourising_a_colour_page_asks_first(
        self,
        client: TestClient,
        session: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(app_settings, "gemini_api_key", "test-sleutel")
        boek = _colour_book(session, tmp_path)
        response = client.post(f"/api/books/{boek.id}/pages/0/colour")
        assert response.status_code == 412
        assert "kleur" in response.json()["detail"]

    def test_force_goes_ahead(
        self,
        client: TestClient,
        session: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """De vraag is een bevestiging, geen verbod."""
        monkeypatch.setattr(app_settings, "gemini_api_key", "test-sleutel")
        boek = _colour_book(session, tmp_path)
        geverfd = Image.new("RGB", (40, 60), (40, 120, 40))
        buffer = io.BytesIO()
        geverfd.save(buffer, format="PNG")
        monkeypatch.setattr(
            "bookpal.translate.imagepage.GeminiPageTranslator.colorise_page",
            lambda self, image, *, media_type: buffer.getvalue(),
        )

        response = client.post(f"/api/books/{boek.id}/pages/0/colour?force=true")
        assert response.status_code == 200
        assert client.get(f"/api/books/{boek.id}/pages/0/colour").status_code == 200


class TestColourMode:
    """Met welk beeldmodel er ingekleurd wordt, is een eigen keuze."""

    def test_it_defaults_to_the_cheap_model(self, session: Session):
        from bookpal.translate.preferences import get_colour_mode

        assert get_colour_mode(session) is TranslateMode.IMAGE_FAST

    def test_it_can_be_set_to_the_heavy_one(self, session: Session):
        from bookpal.translate.preferences import get_colour_mode, set_colour_mode

        set_colour_mode(session, TranslateMode.IMAGE_PRO)
        assert get_colour_mode(session) is TranslateMode.IMAGE_PRO

    def test_it_is_separate_from_the_button(self, session: Session):
        """Anders zou een dure vertaalknop ook duur inkleuren afdwingen."""
        from bookpal.translate.preferences import get_colour_mode, set_button_mode

        set_button_mode(session, TranslateMode.IMAGE_PRO)
        assert get_colour_mode(session) is TranslateMode.IMAGE_FAST

    def test_the_text_mode_is_not_a_colour_mode(self, session: Session):
        """Inkleuren levert een afbeelding op; de tekststand kan dat niet."""
        from bookpal.translate.preferences import get_colour_mode, set_colour_mode

        set_colour_mode(session, TranslateMode.TEXT)
        assert get_colour_mode(session) is TranslateMode.IMAGE_FAST

    def test_the_api_refuses_the_text_mode(self, client: TestClient):
        response = client.put("/api/translate/mode", json={"colour_mode": "text"})
        assert response.status_code == 400
        assert "beeldstand" in response.json()["detail"]

    def test_the_api_reports_and_stores_it(self, client: TestClient):
        assert client.get("/api/translate/mode").json()["colour_mode"] == "image_fast"
        response = client.put("/api/translate/mode", json={"colour_mode": "image_pro"})
        assert response.json()["colour_mode"] == "image_pro"
        assert client.get("/api/translate/mode").json()["colour_mode"] == "image_pro"

    def test_colourising_uses_the_chosen_model(
        self,
        client: TestClient,
        session: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """De stand hoort ook echt het model te kiezen, niet alleen te tonen."""
        from bookpal.config import settings as app_config

        monkeypatch.setattr(app_config, "gemini_api_key", "test-sleutel")
        boek = _comic(session, pages=3)
        pad = make_cbz(tmp_path / "grijs.cbz", pages=3)
        from bookpal.models import File, LibraryRoot

        root = LibraryRoot(name="R", path=str(tmp_path))
        session.add(root)
        session.flush()
        bestand = File(
            library_root_id=root.id,
            path=str(pad),
            size=pad.stat().st_size,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(bestand)
        session.flush()
        boek.file_id = bestand.id
        session.commit()

        gebruikt: list[str] = []
        plaat = io.BytesIO()
        Image.new("RGB", (40, 60), (40, 120, 40)).save(plaat, format="PNG")

        def onthoud(self, image, *, media_type):
            gebruikt.append(self.model)
            return plaat.getvalue()

        monkeypatch.setattr(
            "bookpal.translate.imagepage.GeminiPageTranslator.colorise_page", onthoud
        )

        # force omdat de proefpagina's zelf kleur hebben; hier gaat het om het
        # model dat gekozen wordt, niet om de vraag of het mag.
        eerste = client.post(f"/api/books/{boek.id}/pages/0/colour?force=true")
        assert eerste.status_code == 200, eerste.json()
        assert gebruikt == [app_config.gemini_image_model_fast]

        client.put("/api/translate/mode", json={"colour_mode": "image_pro"})
        client.post(f"/api/books/{boek.id}/pages/1/colour?force=true")
        assert gebruikt[-1] == app_config.gemini_image_model_pro


class TestTheAutomaticMode:
    """De stand bij "vanzelf" hoort ook echt te bepalen wat er gebeurt.

    Hij werd wel bewaard en getoond, maar nergens gelezen: de wachtrij pakte
    altijd de tekstvertaler. Een schakelaar die niets doet is erger dan geen
    schakelaar, want je denkt dat je iets hebt ingesteld.
    """

    def test_the_queue_carries_the_mode(self, session: Session):
        from bookpal.translate.preferences import set_mode

        set_mode(session, TranslateMode.IMAGE_FAST)
        queue = TranslationQueue()
        queue.submit(1, [0, 1], "nl", mode=TranslateMode.IMAGE_FAST)
        assert all(job.mode is TranslateMode.IMAGE_FAST for job in queue._jobs)

    def test_the_same_page_in_two_modes_is_two_jobs(self):
        """Anders zou een hertekende pagina een tekstvertaling verdringen."""
        queue = TranslationQueue()
        queue.submit(1, [0], "nl", mode=TranslateMode.TEXT)
        toegevoegd = queue.submit(1, [0], "nl", mode=TranslateMode.IMAGE_FAST)
        assert toegevoegd == 1
        assert len(queue._jobs) == 2

    def test_reading_ahead_follows_the_setting(
        self, session: Session, temp_settings, monkeypatch: pytest.MonkeyPatch
    ):
        from bookpal.translate.preferences import set_mode
        from bookpal.translate.queue import TranslationQueue as Q

        monkeypatch.setattr(app_settings, "gemini_api_key", "test-sleutel")
        boek = _comic(session, pages=10)
        session.commit()
        set_mode(session, TranslateMode.IMAGE_FAST)

        queue = Q()
        queue.notify_reading(boek.id, 0, "nl")
        assert queue._jobs, "er hoort iets vooruit gelezen te worden"
        assert all(job.mode is TranslateMode.IMAGE_FAST for job in queue._jobs)

    def test_the_counter_sees_every_mode(self, session: Session):
        """Anders staat de balk op nul zodra je in een andere stand werkt."""
        from bookpal.api.translate import _done_pages

        boek = _comic(session)
        session.commit()
        _store(session, boek, 0, "nl")
        session.add(
            Translation(
                book_id=boek.id,
                page_index=4,
                target_lang="nl",
                provider=TranslateMode.IMAGE_PRO.provider,
                payload={"full_page": True, "model": "gemini-3-pro-image"},
            )
        )
        session.commit()

        assert _done_pages(session, boek.id, "nl") == {0, 4}


class TestWhereSidecarsLive:
    """Naast de serie in je eigen bibliotheek, in een verborgen map.

    Belangrijk genoeg om vast te leggen: hier staat betaald werk, en een pad
    dat stilletjes verschuift betekent dat je er opnieuw voor betaalt.
    """

    def _serie(self, session: Session, **velden) -> Series:
        series = Series(title="Oishinbo", sort_title="oishinbo", **velden)
        session.add(series)
        session.flush()
        return series

    def _boek(self, session: Session, series: Series, **velden) -> Book:
        velden.setdefault("title", "Deel")
        book = Book(series_id=series.id, kind=BookKind.COMIC, **velden)
        session.add(book)
        session.flush()
        return book

    def test_volume_and_chapter_are_padded(self, session: Session, temp_settings):
        """Zodat een ls op leesvolgorde staat in plaats van 1, 10, 2."""
        series = self._serie(session)
        book = self._boek(session, series, volume="3", number="12", title="Iets")
        assert sidecar.chapter_slug(book) == "v03c012"

    def test_a_half_chapter_keeps_its_half(self, session: Session, temp_settings):
        series = self._serie(session)
        book = self._boek(session, series, number="12.5")
        assert sidecar.chapter_slug(book) == "c012.5"

    def test_something_unnumbered_falls_back_to_its_title(self, session: Session, temp_settings):
        series = self._serie(session)
        book = self._boek(session, series, title="Extra hoofdstuk")
        assert sidecar.chapter_slug(book) == "Extra hoofdstuk"

    def test_the_place_is_remembered(self, session: Session, temp_settings):
        """Een serie kan verhuizen; het betaalde werk mag niet meeverhuizen."""
        from bookpal.models import LibraryRoot

        root = LibraryRoot(name="Manga", path="/library/manga")
        session.add(root)
        session.flush()
        series = self._serie(session, library_root_id=root.id)
        book = self._boek(session, series, number="1")

        eerst = sidecar.chapter_dir(series, book)
        assert series.sidecar_path, "de plek hoort vastgelegd te worden"

        # Serie verhuist naar een andere root: het pad blijft waar het stond.
        series.library_root_id = None
        session.flush()
        assert sidecar.chapter_dir(series, book) == eerst

    def test_the_download_cache_is_never_chosen(self, session: Session, temp_settings):
        """Daar wordt opgeruimd, en dan is een betaalde vertaling weg."""
        from bookpal.models import LibraryRoot

        cache = LibraryRoot(name="Downloads", path=str(app_settings.download_dir))
        eigen = LibraryRoot(name="Manga", path="/library/manga")
        session.add_all([cache, eigen])
        session.flush()
        series = self._serie(session, library_root_id=cache.id)
        book = self._boek(session, series, number="1")

        pad = sidecar.chapter_dir(series, book)
        assert str(app_settings.download_dir) not in str(pad)
        assert "/library/manga" in str(pad)

    def test_the_hidden_folder_sits_between_them(self, session: Session, temp_settings):
        series = self._serie(session)
        book = self._boek(session, series, number="1")
        pad = sidecar.chapter_dir(series, book)
        assert pad.parent.name == sidecar.SIDECAR_DIRNAME
        assert pad.parent.parent.name == "Oishinbo"


class TestMovingTheOldOnes:
    def test_files_move_to_the_new_place(self, session: Session, temp_settings):
        series = Series(title="Oishinbo", sort_title="oishinbo")
        session.add(series)
        session.flush()
        book = Book(series_id=series.id, kind=BookKind.COMIC, number="12", title="Iets")
        session.add(book)
        session.commit()

        oud = sidecar.legacy_chapter_dir(series, book)
        oud.mkdir(parents=True, exist_ok=True)
        (oud / "p0001-nl.json").write_text('{"bubbles": []}', encoding="utf-8")

        verplaatst = sidecar.move_legacy(session)

        assert verplaatst == 1
        assert (sidecar.chapter_dir(series, book) / "p0001-nl.json").is_file()
        assert not oud.exists()

    def test_it_only_runs_once(self, session: Session, temp_settings):
        """Anders zou elke herstart de hele bibliotheek langslopen."""
        sidecar.move_legacy(session)
        assert sidecar.move_legacy(session) == 0

    def test_a_failed_move_is_not_ticked_off(self, session: Session, temp_settings, monkeypatch):
        """Wat er niet mee kwam is betaald werk; dat probeer je opnieuw."""
        from bookpal.models import Setting

        series = Series(title="Oishinbo", sort_title="oishinbo")
        session.add(series)
        session.flush()
        book = Book(series_id=series.id, kind=BookKind.COMIC, number="12", title="Iets")
        session.add(book)
        session.commit()
        oud = sidecar.legacy_chapter_dir(series, book)
        oud.mkdir(parents=True, exist_ok=True)
        (oud / "p0001-nl.json").write_text("{}", encoding="utf-8")

        def stuk(*_args, **_kwargs):
            raise OSError("andere schijf")

        monkeypatch.setattr("bookpal.translate.sidecar.shutil.move", stuk)
        sidecar.move_legacy(session)

        assert session.get(Setting, sidecar.MOVED_KEY) is None
        assert (oud / "p0001-nl.json").is_file(), "het origineel blijft staan"


class TestRecoveringOrphans:
    """Mappen die niet meer op naam te vinden waren, alsnog thuisbrengen.

    Hoofdstukken zijn onderweg hernoemd; die vertalingen waren daarmee ook in
    de oude indeling al onvindbaar. Er is wel voor betaald.
    """

    def _serie_met_boek(self, session: Session, titel: str, nummer: str) -> tuple[Series, Book]:
        series = Series(title=titel, sort_title=titel.lower())
        session.add(series)
        session.flush()
        book = Book(
            series_id=series.id,
            kind=BookKind.COMIC,
            title=f"Hoofdstuk {nummer}",
            number=nummer,
        )
        session.add(book)
        session.commit()
        return series, book

    def test_a_renamed_chapter_is_found_by_its_number(self, session: Session, temp_settings):
        series, book = self._serie_met_boek(session, "Shinya Shokudo", "39")
        # Zoals hij vroeger heette: op de titel van toen.
        oud = app_settings.sidecar_dir / "Shinya Shokudo" / "39 Yarō Abe"
        oud.mkdir(parents=True, exist_ok=True)
        (oud / "p0003-nl.json").write_text("{}", encoding="utf-8")

        sidecar.move_legacy(session)

        assert (sidecar.chapter_dir(series, book) / "p0003-nl.json").is_file()

    def test_an_edition_suffix_still_matches_the_series(self, session: Session, temp_settings):
        """De map heette naar de uitgave, de serie heet nu zonder."""
        series, book = self._serie_met_boek(session, "One Piece", "251")
        oud = app_settings.sidecar_dir / "One Piece (Official Colored)" / "251 Overture"
        oud.mkdir(parents=True, exist_ok=True)
        (oud / "p0002-nl.json").write_text("{}", encoding="utf-8")

        sidecar.move_legacy(session)

        assert (sidecar.chapter_dir(series, book) / "p0002-nl.json").is_file()

    def test_capitals_do_not_matter(self, session: Session, temp_settings):
        """Dezelfde serie heette ooit "Crayon Shin-chan" en nu "Crayon Shin-Chan"."""
        series, book = self._serie_met_boek(session, "Crayon Shin-Chan", "0")
        oud = app_settings.sidecar_dir / "Crayon Shin-chan" / "0 Vol.2 Ch.0"
        oud.mkdir(parents=True, exist_ok=True)
        (oud / "p0004-nl.json").write_text("{}", encoding="utf-8")

        sidecar.move_legacy(session)

        assert (sidecar.chapter_dir(series, book) / "p0004-nl.json").is_file()

    def test_something_unrecognisable_is_left_alone(self, session: Session, temp_settings):
        """Niet begrijpen is geen reden om iets weg te gooien."""
        self._serie_met_boek(session, "Shinya Shokudo", "39")
        oud = app_settings.sidecar_dir / "Iets Anders" / "geen nummer"
        oud.mkdir(parents=True, exist_ok=True)
        (oud / "p0001-nl.json").write_text("{}", encoding="utf-8")

        sidecar.move_legacy(session)

        assert (oud / "p0001-nl.json").is_file()


class TestTheColourBadgeKnows:
    """Wat het merkje meldt bepaalt welke plaat de lezer opvraagt."""

    def test_a_combination_that_can_be_made_counts_as_available(
        self, session: Session, temp_settings
    ):
        """Anders zie je de eerste keer de kale kleurversie met de oude tekst."""
        from bookpal.translate.service import has_colour_for_language

        samen = TestColourAndTranslationTogether()
        boek = _comic(session)
        session.commit()
        samen._kleur(session, boek)
        samen._hertekend(session, boek)

        assert has_colour_for_language(session, boek, 0, "nl") is True

    def test_without_colour_there_is_nothing_to_combine(self, session: Session, temp_settings):
        from bookpal.translate.service import has_colour_for_language

        samen = TestColourAndTranslationTogether()
        boek = _comic(session)
        session.commit()
        samen._hertekend(session, boek)

        assert has_colour_for_language(session, boek, 0, "nl") is False

    def test_without_a_redrawn_page_there_is_nothing_to_combine(
        self, session: Session, temp_settings
    ):
        from bookpal.translate.service import has_colour_for_language

        samen = TestColourAndTranslationTogether()
        boek = _comic(session)
        session.commit()
        samen._kleur(session, boek)

        assert has_colour_for_language(session, boek, 0, "nl") is False


class TestColourRepairsItself:
    """De ruwe plaat van het model is het enige waar geld in zit.

    Zolang die er ligt is elke bewerking opnieuw te maken: een andere taal, een
    betere samenstelling, of een bestand dat kwijt is.
    """

    def _boek_met_bestand(self, session: Session, tmp_path: Path) -> Book:
        from bookpal.models import File, LibraryRoot

        boek = _comic(session, pages=3)
        pad = make_cbz(tmp_path / "h.cbz", pages=3)
        root = LibraryRoot(name="R", path=str(tmp_path))
        session.add(root)
        session.flush()
        bestand = File(
            library_root_id=root.id,
            path=str(pad),
            size=pad.stat().st_size,
            mtime=0.0,
            extension=".cbz",
        )
        session.add(bestand)
        session.flush()
        boek.file_id = bestand.id
        session.commit()
        return boek

    def _plaat(self, kleur=(40, 160, 40)) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (40, 60), kleur).save(buffer, format="WEBP")
        return buffer.getvalue()

    def test_the_finished_page_is_rebuilt_from_the_raw_one(
        self, session: Session, temp_settings, tmp_path: Path
    ):
        from bookpal.translate.service import COLOUR_RAW_VARIANT, COLOUR_VARIANT, read_colour

        boek = self._boek_met_bestand(session, tmp_path)
        serie = session.get(Series, boek.series_id)
        sidecar.write_bytes(sidecar.variant_path(serie, boek, 0, COLOUR_RAW_VARIANT), self._plaat())

        assert read_colour(session, boek, 0) is not None
        assert sidecar.variant_path(serie, boek, 0, COLOUR_VARIANT).is_file()

    def test_an_old_language_version_can_restore_the_plain_one(
        self, session: Session, temp_settings, tmp_path: Path
    ):
        """De kleur erin komt van het model en klopt nog; alleen de letters niet."""
        from bookpal.translate.service import COLOUR_VARIANT, colour_variant, read_colour

        boek = self._boek_met_bestand(session, tmp_path)
        serie = session.get(Series, boek.series_id)
        sidecar.write_bytes(
            sidecar.variant_path(serie, boek, 0, colour_variant("nl")), self._plaat()
        )

        assert read_colour(session, boek, 0) is not None
        assert sidecar.variant_path(serie, boek, 0, COLOUR_VARIANT).is_file()

    def test_no_ghost_text_when_restoring_from_a_language_version(
        self, session: Session, temp_settings, tmp_path: Path
    ):
        """De letters van de vertaling mogen niet door het origineel heen."""
        from bookpal.translate.service import colour_variant, read_colour

        boek = self._boek_met_bestand(session, tmp_path)
        serie = session.get(Series, boek.series_id)
        # Een taalversie met een zwarte regel waar het origineel wit is.
        plaat = Image.new("RGB", (40, 60), (40, 160, 40))
        for x in range(40):
            plaat.putpixel((x, 5), (0, 0, 0))
        buffer = io.BytesIO()
        plaat.save(buffer, format="WEBP", lossless=True)
        sidecar.write_bytes(
            sidecar.variant_path(serie, boek, 0, colour_variant("nl")), buffer.getvalue()
        )

        hersteld = Image.open(io.BytesIO(read_colour(session, boek, 0))).convert("RGB")
        origineel = Image.open(io.BytesIO(render_for_translation(session, boek, 0)[0])).convert(
            "RGB"
        )
        rood, groen, blauw = hersteld.getpixel((20, int(5 * hersteld.height / 60)))
        was = origineel.getpixel((20, int(5 * origineel.height / 60)))
        assert max(rood, groen, blauw) > 60 or max(was) < 60, (
            "hier stond geen inkt in het origineel, dus hier hoort niets zwart te zijn"
        )

    def test_the_raw_plate_is_not_mistaken_for_a_language(
        self, session: Session, temp_settings, tmp_path: Path
    ):
        """ "kleur-ruw" ziet eruit als "kleur-<taal>" en is het niet."""
        from bookpal.translate.service import COLOUR_RAW_VARIANT, _any_language_colour

        boek = self._boek_met_bestand(session, tmp_path)
        serie = session.get(Series, boek.series_id)
        sidecar.write_bytes(sidecar.variant_path(serie, boek, 0, COLOUR_RAW_VARIANT), self._plaat())

        assert _any_language_colour(serie, boek, 0) is None

    def test_nothing_at_all_stays_nothing(self, session: Session, temp_settings, tmp_path: Path):
        from bookpal.translate.service import read_colour

        boek = self._boek_met_bestand(session, tmp_path)
        assert read_colour(session, boek, 0) is None
