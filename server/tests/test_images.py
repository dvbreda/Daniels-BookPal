from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from bookpal.config import settings
from bookpal.formats import open_book
from bookpal.formats.base import UnsupportedOperation
from bookpal.images import (
    cache_size_bytes,
    get_profile,
    process_image,
    profile_names,
    prune_cache,
    render_cover,
    render_page,
    render_remote_cover,
    source_id_for,
    to_eink_gray,
)
from bookpal.images.profiles import ImageProfile
from tests.fixtures import make_cbz, make_epub, make_pdf, page_png


def open_bytes(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


class TestProcessing:
    def test_downscales_to_max_width(self):
        source = page_png(0, size=(2000, 3000))
        out = process_image(source, get_profile("web"))
        assert open_bytes(out).width == 1600

    def test_never_upscales(self):
        """Opschalen kost bytes zonder detail toe te voegen."""
        source = page_png(0, size=(400, 600))
        out = process_image(source, get_profile("web"))
        assert open_bytes(out).width == 400

    def test_respects_height_limit(self):
        # Een lange webtoon-strook moet op hoogte begrensd worden, niet alleen
        # op breedte.
        source = page_png(0, size=(1000, 4000))
        profile = ImageProfile("t", max_width=1000, max_height=1000, format="png")
        out = process_image(source, profile)
        image = open_bytes(out)
        assert image.height == 1000
        assert image.width == 250

    def test_webp_output(self):
        out = process_image(page_png(0), get_profile("web"))
        assert open_bytes(out).format == "WEBP"

    def test_aspect_ratio_is_kept(self):
        source = page_png(0, size=(1000, 1500))
        out = process_image(source, get_profile("thumb"))
        image = open_bytes(out)
        assert image.width == 320
        assert image.height == 480


class TestEink:
    def test_kobo_profile_is_grayscale_and_panel_sized(self):
        source = page_png(0, size=(2000, 3000))
        out = process_image(source, get_profile("kobo-clara"))
        image = open_bytes(out)
        assert image.mode == "L"
        # Past binnen 1072x1448 met behoud van verhouding.
        assert image.width <= 1072
        assert image.height <= 1448
        assert image.format == "PNG"

    def test_dithering_limits_the_number_of_gray_levels(self):
        # Een verloop zou zonder dithering banden geven; met dithering blijven
        # er precies 16 waarden over die het oog tot een verloop mengt.
        gradient = Image.new("L", (256, 64))
        for x in range(256):
            for y in range(64):
                gradient.putpixel((x, y), x)
        dithered = to_eink_gray(gradient.convert("RGB"), levels=16)
        # Mode "L" is één byte per pixel, dus de ruwe bytes zijn de grijswaarden.
        assert len(set(dithered.tobytes())) <= 16

    def test_all_kobo_profiles_produce_gray(self):
        source = page_png(0, size=(1600, 2400))
        for name in profile_names():
            if not name.startswith("kobo-"):
                continue
            image = open_bytes(process_image(source, get_profile(name)))
            assert image.mode == "L", name


class TestRendering:
    def test_page_is_cached_on_second_call(self, temp_settings: Path, tmp_path: Path):
        path = make_cbz(tmp_path / "a.cbz", pages=3)
        with open_book(path) as book:
            source = source_id_for(path)
            first = render_page(book, 0, get_profile("web"), source_id=source)
            second = render_page(book, 0, get_profile("web"), source_id=source)

        assert first.from_cache is False
        assert second.from_cache is True
        assert first.data == second.data

    def test_profiles_do_not_share_a_cache_entry(self, temp_settings: Path, tmp_path: Path):
        path = make_cbz(tmp_path / "b.cbz", pages=1)
        with open_book(path) as book:
            source = source_id_for(path)
            web = render_page(book, 0, get_profile("web"), source_id=source)
            kobo = render_page(book, 0, get_profile("kobo-clara"), source_id=source)
        assert web.media_type == "image/webp"
        assert kobo.media_type == "image/png"
        assert open_bytes(kobo.data).mode == "L"

    def test_changed_file_invalidates_the_cache(self, temp_settings: Path, tmp_path: Path):
        path = make_cbz(tmp_path / "c.cbz", pages=2)
        first_id = source_id_for(path)
        with open_book(path) as book:
            render_page(book, 0, get_profile("web"), source_id=first_id)

        make_cbz(path, pages=5, comicinfo=None)
        second_id = source_id_for(path)
        assert second_id != first_id
        with open_book(path) as book:
            again = render_page(book, 0, get_profile("web"), source_id=second_id)
        assert again.from_cache is False

    def test_cover_from_cbz(self, temp_settings: Path, tmp_path: Path):
        path = make_cbz(tmp_path / "d.cbz", pages=3)
        with open_book(path) as book:
            cover = render_cover(book, get_profile("cover"), source_id=source_id_for(path))
        assert cover is not None
        assert open_bytes(cover.data).width <= 640

    def test_cover_from_epub(self, temp_settings: Path, tmp_path: Path):
        path = make_epub(tmp_path / "e.epub", with_cover=True)
        with open_book(path) as book:
            cover = render_cover(book, get_profile("cover"), source_id=source_id_for(path))
        assert cover is not None

    def test_epub_without_cover_returns_none(self, temp_settings: Path, tmp_path: Path):
        path = make_epub(tmp_path / "f.epub", with_cover=False)
        with open_book(path) as book:
            assert render_cover(book, get_profile("cover"), source_id=source_id_for(path)) is None

    def test_pdf_renders_at_profile_width(self, temp_settings: Path, tmp_path: Path):
        path = make_pdf(tmp_path / "g.pdf", pages=2)
        profile = ImageProfile("smal", max_width=300, format="png")
        with open_book(path) as book:
            rendered = render_page(book, 0, profile, source_id=source_id_for(path))
        assert open_bytes(rendered.data).width == pytest.approx(300, abs=2)


class TestRemoteCover:
    """De omslag van een bron (M5/M7) — 'pagina 1' is bij scanlaties vaak een
    credits-pagina van de vertaalgroep, dus dit gaat via dezelfde pipeline als
    elke andere afbeelding, maar met een URL in plaats van een lokaal bestand."""

    def _stub_get(self, monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
        def fake_get(url: str, **kwargs: object) -> httpx.Response:
            calls.append(url)
            # raise_for_status() eist een request-object; een productie-
            # httpx.get() heeft dat altijd, deze losse Response niet vanzelf.
            return httpx.Response(200, content=page_png(0), request=httpx.Request("GET", url))

        monkeypatch.setattr("bookpal.images.pipeline.httpx.get", fake_get)

    def test_fetches_and_processes_through_the_normal_pipeline(
        self, temp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[str] = []
        self._stub_get(monkeypatch, calls)

        rendered = render_remote_cover(
            "https://uploads.mangadex.org/covers/x/y.jpg",
            get_profile("thumb"),
            source_id="series-cover:1:https://uploads.mangadex.org/covers/x/y.jpg",
        )
        assert calls == ["https://uploads.mangadex.org/covers/x/y.jpg"]
        assert rendered.from_cache is False
        assert open_bytes(rendered.data).width <= 320

    def test_second_call_is_a_cache_hit_and_skips_the_network(
        self, temp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ):
        calls: list[str] = []
        self._stub_get(monkeypatch, calls)
        profile = get_profile("thumb")

        render_remote_cover("https://example.test/cover.jpg", profile, source_id="s:1:url")
        again = render_remote_cover("https://example.test/cover.jpg", profile, source_id="s:1:url")

        assert len(calls) == 1
        assert again.from_cache is True

    def test_a_changed_cover_url_gets_its_own_cache_entry(
        self, temp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """De cache-sleutel bevat de URL zelf: als de bron een nieuwe omslag
        levert, mag de oude niet blijven hangen."""
        calls: list[str] = []
        self._stub_get(monkeypatch, calls)
        profile = get_profile("thumb")

        render_remote_cover("https://example.test/oud.jpg", profile, source_id="s:1:oud")
        render_remote_cover("https://example.test/nieuw.jpg", profile, source_id="s:1:nieuw")

        assert len(calls) == 2

    def test_a_network_error_is_reported_clearly(
        self, temp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ):
        def fake_get(url: str, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("geen verbinding")

        monkeypatch.setattr("bookpal.images.pipeline.httpx.get", fake_get)

        with pytest.raises(UnsupportedOperation):
            render_remote_cover("https://example.test/x.jpg", get_profile("thumb"), source_id="s")

    def test_a_4xx_response_is_reported_clearly(
        self, temp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ):
        def fake_get(url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(404, content=b"niet gevonden", request=httpx.Request("GET", url))

        monkeypatch.setattr("bookpal.images.pipeline.httpx.get", fake_get)

        with pytest.raises(UnsupportedOperation):
            render_remote_cover("https://example.test/x.jpg", get_profile("thumb"), source_id="s")


class TestCachePruning:
    def test_prunes_until_under_the_limit(self, temp_settings: Path, tmp_path: Path):
        path = make_cbz(tmp_path / "h.cbz", pages=8)
        with open_book(path) as book:
            source = source_id_for(path)
            for index in range(8):
                render_page(book, index, get_profile("web"), source_id=source)

        before = cache_size_bytes()
        assert before > 0
        removed = prune_cache(max_bytes=before // 2)
        assert removed > 0
        assert cache_size_bytes() <= before // 2

    def test_no_pruning_when_within_budget(self, temp_settings: Path, tmp_path: Path):
        path = make_cbz(tmp_path / "i.cbz", pages=2)
        with open_book(path) as book:
            render_page(book, 0, get_profile("web"), source_id=source_id_for(path))
        assert prune_cache(max_bytes=100 * 1024 * 1024) == 0

    def test_cache_lives_under_the_configured_dir(self, temp_settings: Path, tmp_path: Path):
        path = make_cbz(tmp_path / "j.cbz", pages=1)
        with open_book(path) as book:
            render_page(book, 0, get_profile("web"), source_id=source_id_for(path))
        assert any(settings.cache_dir.rglob("*.webp"))


class TestProfileLookup:
    def test_default(self):
        assert get_profile(None).name == "web"

    def test_unknown_profile_raises(self):
        with pytest.raises(KeyError):
            get_profile("kobo-bestaatniet")
