"""Een heel hoofdstuk in één keer, via de batch-API.

Wat hier telt is niet of Gemini antwoordt — dat is hun kant — maar of wij het
antwoord op precies dezelfde plek wegzetten als het losse werk, en of je nooit
zonder bedrag aan een hoofdstuk begint.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from bookpal.config import settings as app_settings
from bookpal.models import Book, BookKind, File, LibraryRoot, Series
from bookpal.translate import batch, sidecar
from bookpal.translate.base import TranslationError
from bookpal.translate.modes import TranslateMode
from bookpal.translate.service import colour_variant
from tests.fixtures import make_cbz


@pytest.fixture(autouse=True)
def _schoon():
    batch.reset()
    yield
    batch.reset()


def _boek(session: Session, tmp_path: Path, pages: int = 4) -> Book:
    series = Series(title="Reeks", sort_title="reeks")
    session.add(series)
    session.flush()
    boek = Book(series_id=series.id, kind=BookKind.COMIC, title="Deel", page_count=pages)
    session.add(boek)
    session.flush()
    pad = make_cbz(tmp_path / "b.cbz", pages=pages)
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


def _beeld_antwoord(width: int = 40, height: int = 60) -> dict:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 40)).save(buffer, format="PNG")
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
                            }
                        }
                    ]
                }
            }
        ]
    }


def _tekst_antwoord() -> dict:
    regels = (
        '[{"box_2d": [10, 10, 90, 90], "source": "HI", "translation": "Hoi", "kind": "speech"}]'
    )
    return {"candidates": [{"content": {"parts": [{"text": regels}]}}]}


class TestThePlan:
    def test_it_counts_what_is_left_to_do(self, session: Session, temp_settings, tmp_path: Path):
        boek = _boek(session, tmp_path, pages=6)
        gepland = batch.plan(session, boek, kind=batch.KLEUREN)
        assert gepland.pages == [0, 1, 2, 3, 4, 5]

    def test_pages_that_are_done_drop_out(self, session: Session, temp_settings, tmp_path: Path):
        """Anders betaal je een tweede keer voor wat er al ligt."""
        boek = _boek(session, tmp_path, pages=4)
        serie = session.get(Series, boek.series_id)
        sidecar.write_bytes(sidecar.variant_path(serie, boek, 1, colour_variant(None)), b"x")

        assert batch.plan(session, boek, kind=batch.KLEUREN).pages == [0, 2, 3]

    def test_it_starts_where_you_are(self, session: Session, temp_settings, tmp_path: Path):
        boek = _boek(session, tmp_path, pages=6)
        assert batch.plan(session, boek, kind=batch.KLEUREN, from_page=4).pages == [4, 5]

    def test_the_price_is_half_of_the_normal_rate(
        self, session: Session, temp_settings, tmp_path: Path
    ):
        from bookpal.api.translate import _COSTS

        boek = _boek(session, tmp_path, pages=3)
        gepland = batch.plan(session, boek, kind=batch.KLEUREN)
        vol = _COSTS[str(gepland.mode)]
        assert gepland.price_per_page == pytest.approx(vol * batch.BATCH_FACTOR, abs=0.0005)
        assert gepland.total == pytest.approx(3 * gepland.price_per_page, abs=0.001)

    def test_each_kind_has_its_own_model(self, session: Session, temp_settings, tmp_path: Path):
        """Tekst hoort nooit stiekem door een beeldmodel te gaan."""
        boek = _boek(session, tmp_path)
        assert batch.plan(session, boek, kind=batch.TEKST).mode is TranslateMode.TEXT
        assert batch.plan(session, boek, kind=batch.HERTEKEND).mode.is_image
        assert batch.plan(session, boek, kind=batch.KLEUREN).mode.is_image

    def test_an_unknown_kind_is_refused(self, session: Session, temp_settings, tmp_path: Path):
        boek = _boek(session, tmp_path)
        with pytest.raises(TranslationError):
            batch.plan(session, boek, kind="onzin")


class TestStarting:
    def test_nothing_to_do_is_not_started(self, session: Session, temp_settings, tmp_path: Path):
        boek = _boek(session, tmp_path)
        leeg = batch.BatchPlan(
            kind=batch.KLEUREN, mode=TranslateMode.IMAGE_FAST, pages=[], price_per_page=0.03
        )
        with pytest.raises(TranslationError):
            batch.start(boek.id, leeg)

    def test_only_one_at_a_time(self, session: Session, temp_settings, tmp_path: Path, monkeypatch):
        """Twee batches tegelijk maken het niet sneller en de melding onduidelijk."""
        monkeypatch.setattr(app_settings, "gemini_api_key", "test-sleutel")
        bezig = batch.BatchState(
            kind=batch.KLEUREN, book_id=1, mode=TranslateMode.IMAGE_FAST, pages=[0]
        )
        batch._current = bezig
        gepland = batch.BatchPlan(
            kind=batch.KLEUREN, mode=TranslateMode.IMAGE_FAST, pages=[0], price_per_page=0.03
        )
        with pytest.raises(TranslationError):
            batch.start(1, gepland)

    def test_without_a_key_nothing_happens(self, session: Session, temp_settings, tmp_path: Path):
        gepland = batch.BatchPlan(
            kind=batch.KLEUREN, mode=TranslateMode.IMAGE_FAST, pages=[0], price_per_page=0.03
        )
        with pytest.raises(TranslationError):
            batch.start(1, gepland)


class TestStoring:
    """De batch hoort exact dezelfde bestanden achter te laten als het losse werk."""

    def _state(self, boek: Book, kind: str, mode: TranslateMode) -> batch.BatchState:
        return batch.BatchState(kind=kind, book_id=boek.id, mode=mode, pages=[0])

    def test_a_colour_page_lands_where_the_reader_looks(
        self, session: Session, temp_settings, tmp_path: Path
    ):
        boek = _boek(session, tmp_path)
        serie = session.get(Series, boek.series_id)
        origineel = io.BytesIO()
        Image.new("RGB", (40, 60), (255, 255, 255)).save(origineel, format="PNG")

        batch._store_one(
            session,
            boek,
            serie,
            self._state(boek, batch.KLEUREN, TranslateMode.IMAGE_FAST),
            0,
            origineel.getvalue(),
            _beeld_antwoord(),
        )

        pad = sidecar.variant_path(serie, boek, 0, colour_variant(None))
        assert pad.is_file(), "de lezer kijkt op deze plek"

    def test_a_redrawn_page_lands_under_its_own_mode(
        self, session: Session, temp_settings, tmp_path: Path
    ):
        boek = _boek(session, tmp_path)
        serie = session.get(Series, boek.series_id)
        origineel = io.BytesIO()
        Image.new("RGB", (40, 60), (255, 255, 255)).save(origineel, format="PNG")

        batch._store_one(
            session,
            boek,
            serie,
            self._state(boek, batch.HERTEKEND, TranslateMode.IMAGE_PRO),
            0,
            origineel.getvalue(),
            _beeld_antwoord(),
        )

        pad = sidecar.image_path(
            serie, boek, 0, app_settings.translate_lang, TranslateMode.IMAGE_PRO
        )
        assert pad.is_file()

    def test_text_bubbles_land_as_json(self, session: Session, temp_settings, tmp_path: Path):
        boek = _boek(session, tmp_path)
        serie = session.get(Series, boek.series_id)

        batch._store_one(
            session,
            boek,
            serie,
            self._state(boek, batch.TEKST, TranslateMode.TEXT),
            0,
            b"",
            _tekst_antwoord(),
        )

        pad = sidecar.json_path(serie, boek, 0, app_settings.translate_lang)
        assert pad.is_file()
        assert "Hoi" in pad.read_text(encoding="utf-8")

    def test_one_bad_page_does_not_lose_the_others(
        self, session: Session, temp_settings, tmp_path: Path
    ):
        """Er is voor die andere pagina's betaald."""
        boek = _boek(session, tmp_path)
        serie = session.get(Series, boek.series_id)
        state = batch.BatchState(
            kind=batch.TEKST, book_id=boek.id, mode=TranslateMode.TEXT, pages=[0, 1]
        )
        payload = {
            "response": {
                "inlinedResponses": {
                    "inlinedResponses": [
                        {"error": {"message": "filter"}},
                        {"response": _tekst_antwoord()},
                    ]
                }
            }
        }

        batch._store(state, {0: b"", 1: b""}, payload)

        assert state.done == 1
        assert state.failed == 1
        assert sidecar.json_path(serie, boek, 1, app_settings.translate_lang).is_file()


class TestSurvivingARestart:
    def test_a_running_batch_is_remembered(self, session: Session, temp_settings, tmp_path: Path):
        """Bij Google draait hij door; zonder de naam laten we betaald werk liggen."""
        from bookpal.models import Setting

        state = batch.BatchState(
            kind=batch.KLEUREN,
            book_id=7,
            mode=TranslateMode.IMAGE_FAST,
            pages=[0, 1],
            operation="batches/abc",
        )
        batch._remember(state)

        row = session.get(Setting, batch.STATE_KEY)
        assert row is not None
        assert row.value["operation"] == "batches/abc"

    def test_a_finished_batch_is_forgotten(self, session: Session, temp_settings):
        from bookpal.models import Setting

        state = batch.BatchState(
            kind=batch.KLEUREN,
            book_id=7,
            mode=TranslateMode.IMAGE_FAST,
            pages=[0],
            operation="batches/abc",
        )
        batch._remember(state)
        batch._forget()

        session.expire_all()
        assert session.get(Setting, batch.STATE_KEY) is None

    def test_nothing_stored_means_nothing_to_resume(self, session: Session, temp_settings):
        assert batch.resume() is None

    def test_nonsense_is_thrown_away(self, session: Session, temp_settings):
        """Een half geschreven stand mag het opstarten niet blokkeren."""
        from bookpal.models import Setting

        session.add(Setting(key=batch.STATE_KEY, value={"operation": "batches/x"}))
        session.commit()

        assert batch.resume() is None
        session.expire_all()
        assert session.get(Setting, batch.STATE_KEY) is None
