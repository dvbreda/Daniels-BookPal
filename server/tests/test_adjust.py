"""Bijsnijden en contrast: de leesinstellingen die het beeld zelf raken."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from bookpal.images.adjust import Adjustments, autocrop, boost_contrast
from tests.fixtures import make_cbz


def _page_with_border(border: int = 40, fill: int = 255) -> Image.Image:
    """Een 'pagina' met een egale rand en een donker vlak in het midden."""
    image = Image.new("L", (200, 300), fill)
    image.paste(Image.new("L", (200 - 2 * border, 300 - 2 * border), 20), (border, border))
    return image


class TestAutocrop:
    def test_a_white_border_is_removed(self):
        cropped = autocrop(_page_with_border(border=40))
        assert cropped.size == (120, 220)

    def test_a_grey_border_is_removed_too(self):
        """Een gescande rand is zelden zuiver wit."""
        cropped = autocrop(_page_with_border(border=30, fill=238))
        assert cropped.size == (140, 240)

    def test_a_page_without_a_border_is_left_alone(self):
        image = Image.new("L", (100, 150), 255)
        image.paste(Image.new("L", (100, 150), 20), (0, 0))
        assert autocrop(image).size == (100, 150)

    def test_an_empty_page_is_not_eaten(self):
        """Volledig egaal: er valt niets te winnen en alles te verliezen."""
        image = Image.new("L", (80, 120), 255)
        assert autocrop(image).size == (80, 120)

    def test_it_never_trims_more_than_a_quarter(self):
        """Een titelblad met een klein logo mag niet tot dat logo inkrimpen."""
        image = Image.new("L", (200, 300), 255)
        image.paste(Image.new("L", (10, 10), 0), (95, 145))
        cropped = autocrop(image)
        assert cropped.size == (100, 150)

    def test_a_colour_page_still_crops(self):
        image = Image.new("RGB", (200, 300), (255, 255, 255))
        image.paste(Image.new("RGB", (120, 220), (10, 20, 30)), (40, 40))
        assert autocrop(image).size == (120, 220)


class TestContrast:
    def test_a_flat_scan_gets_stretched(self):
        """Een grijzige scan hoort na bewerking echt zwart en wit te bevatten."""
        flat = Image.new("L", (50, 50), 128)
        flat.paste(Image.new("L", (25, 50), 160), (25, 0))
        boosted = boost_contrast(flat, 150)
        low, high = boosted.getextrema()
        assert low == 0 and high == 255

    def test_the_mode_is_preserved(self):
        assert boost_contrast(Image.new("L", (10, 10), 100), 120).mode == "L"


class TestAdjustments:
    def test_untouched_settings_do_nothing(self):
        assert Adjustments().active is False
        assert Adjustments().cache_key == ""

    def test_different_settings_get_different_cache_keys(self):
        """Anders overschrijft een bijgesneden pagina de onbewerkte."""
        keys = {
            Adjustments().cache_key,
            Adjustments(crop=True).cache_key,
            Adjustments(contrast=130).cache_key,
            Adjustments(crop=True, contrast=130).cache_key,
        }
        assert len(keys) == 4


@pytest.fixture
def bordered(client: TestClient, tmp_path: Path) -> tuple[TestClient, int]:
    """Een strip met een echte witrand — anders valt er niets te croppen."""
    root = tmp_path / "randen"
    make_cbz(root / "Storm 01.cbz", pages=3, border=60)
    response = client.post("/api/libraries", json={"name": "Randen", "path": str(root)})
    assert response.status_code == 201
    scan = client.post(f"/api/libraries/{response.json()['id']}/scan")
    assert scan.status_code == 200, scan.text
    book_id = int(client.get("/api/books").json()["items"][0]["id"])
    return client, book_id


class TestPageApi:
    def _comic_id(self, client: TestClient) -> int:
        items = client.get("/api/books").json()["items"]
        return int(next(item for item in items if item["kind"] == "comic")["id"])

    def test_cropping_actually_shrinks_the_page(
        self, bordered: tuple[TestClient, int]
    ):
        client, book_id = bordered
        plain = client.get(f"/api/books/{book_id}/pages/0")
        cropped = client.get(f"/api/books/{book_id}/pages/0", params={"crop": True})
        assert cropped.status_code == 200
        assert _size(cropped.content)[0] < _size(plain.content)[0]

    def test_contrast_changes_the_page(self, bordered: tuple[TestClient, int]):
        client, book_id = bordered
        plain = client.get(f"/api/books/{book_id}/pages/0")
        harder = client.get(f"/api/books/{book_id}/pages/0", params={"contrast": 160})
        assert harder.status_code == 200
        assert harder.content != plain.content

    def test_the_default_is_untouched(self, scanned: TestClient):
        book_id = self._comic_id(scanned)
        plain = scanned.get(f"/api/books/{book_id}/pages/0")
        explicit = scanned.get(
            f"/api/books/{book_id}/pages/0", params={"crop": False, "contrast": 100}
        )
        assert explicit.content == plain.content

    def test_an_absurd_contrast_is_refused(self, scanned: TestClient):
        book_id = self._comic_id(scanned)
        assert scanned.get(
            f"/api/books/{book_id}/pages/0", params={"contrast": 900}
        ).status_code == 422

    def test_both_variants_are_cached_separately(self, bordered: tuple[TestClient, int]):
        """De tweede aanvraag komt uit de cache, en niet uit die van de ander."""
        client, book_id = bordered
        first = client.get(f"/api/books/{book_id}/pages/0", params={"crop": True})
        second = client.get(f"/api/books/{book_id}/pages/0", params={"crop": True})
        plain = client.get(f"/api/books/{book_id}/pages/0")
        assert second.headers["X-BookPal-Cache"] == "hit"
        assert second.content == first.content
        assert plain.content != first.content


def _size(data: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(data)) as image:
        return image.size
