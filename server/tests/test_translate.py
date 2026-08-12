"""Bubbelvertaling (M8): wat er van een pagina gemaakt wordt, en wat de lezer
ermee kan als het misgaat."""

from __future__ import annotations

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
from bookpal.translate.service import find, plan_pages, translate_page, translated_pages


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
        kost een fractie van de bytes."""
        page = _png(800, 1200)
        layer = render_layer((800, 1200), [Bubble(0.1, 0.1, 0.4, 0.2, "HI", "HOI")])
        assert len(layer) < len(page)

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
    def test_the_path_is_named_after_series_and_chapter(self, session: Session):
        series = Series(title="Shinya Shokudo", sort_title="shinya")
        session.add(series)
        session.flush()
        book = Book(series_id=series.id, kind=BookKind.COMIC, title="Deel", number="03")
        session.add(book)
        session.flush()

        path = sidecar.json_path(series, book, 7, "nl")
        assert "Shinya Shokudo" in str(path)
        assert "03 Deel" in str(path)
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
