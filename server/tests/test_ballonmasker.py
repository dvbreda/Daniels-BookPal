"""Alleen de ballonnen van het model, de tekening van de tekenaar.

De platen zijn hier gebouwd en niet echt: een test op een echte scan zegt niets
zodra die scan verandert, en de gevallen die ertoe doen — het Japans dat
doorheen bleef staan, de afgekapte vertaling, de crème rechthoek — zijn
allemaal na te bouwen met een paar rechthoeken.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from bookpal.db import session_scope
from bookpal.models import Book, Series
from bookpal.translate.ballonmasker import (
    inktvloer,
    naar_webp,
    stel_samen,
    zwartpunt,
)
from bookpal.translate.base import Bubble

BREED, HOOG = 400, 600


def _bubble(x0: float, y0: float, x1: float, y1: float) -> Bubble:
    return Bubble(x0=x0, y0=y0, x1=x1, y1=y1, source="bron", translation="doel")


def _pagina(
    *, papier: tuple[int, int, int] = (255, 255, 255), tekst: str = "oud", inkt: int = 0
) -> Image.Image:
    """Een plaat met één ballon linksboven en een 'tekening' rechtsonder.

    ``inkt`` is hoe zwart de donkerste inkt van deze 'scan' is — de rand van
    de ballon meegerekend. Een verwassen scan heeft nergens echt zwart, en dat
    is precies wat de zwartpuntcorrectie moet zien.
    """
    beeld = Image.new("RGB", (BREED, HOOG), papier)
    tekenaar = ImageDraw.Draw(beeld)
    donker = (inkt, inkt, inkt)
    # De ballon: wit vlak met een donkere rand en donkere letters erin.
    tekenaar.ellipse((40, 40, 240, 180), fill=(255, 255, 255), outline=donker, width=3)
    if tekst:
        tekenaar.rectangle((70, 70, 220, 160), fill=donker)
    # De tekening: rastertoon die nooit aangeraakt mag worden. Bewust minder
    # oppervlak dan er inkt is, anders landt het 2e percentiel op het raster
    # en meet `inktvloer` de verkeerde laag.
    for y in range(430, 520, 8):
        tekenaar.line((60, y, 340, y), fill=(120, 120, 120), width=1)
    return beeld


class TestInktvloer:
    def test_a_washed_out_scan_measures_higher_than_a_clean_one(self):
        """De maat is relatief, niet absoluut: het 2e percentiel van een plaat
        met veel rastertoon ligt bij die rastertoon en niet bij de inkt.

        Waar het om gaat is dat een verwassen scan (Oishinbo meet 35) hoger
        uitkomt dan een schone (Shin-Chan meet 2), want dát bepaalt of de
        correctie aangaat.
        """
        assert inktvloer(_pagina(inkt=60)) > inktvloer(_pagina(inkt=0))


class TestZwartpunt:
    def test_a_scan_that_is_already_black_is_left_alone(self):
        """Zelfkalibrerend: geen correctie waar niets te corrigeren valt."""
        plaat = _pagina(inkt=0)
        assert zwartpunt(plaat, 2) is plaat

    def test_a_washed_out_scan_gets_its_blacks_pulled_down(self):
        plaat = _pagina(inkt=60)
        na = zwartpunt(plaat, 60)
        assert min(na.convert("L").getdata()) < min(plaat.convert("L").getdata())

    def test_the_paper_stays_white(self):
        """Alleen het zwartpunt; anders vergrijst de hele plaat."""
        na = zwartpunt(_pagina(inkt=60), 60)
        assert max(na.convert("L").getdata()) == 255

    def test_colour_survives(self):
        """Deze correctie deed eerst convert('L') en maakte kleurenpagina's grijs."""
        gekleurd = Image.new("RGB", (40, 40), (200, 40, 40))
        na = zwartpunt(gekleurd, 30)
        rood, groen, _ = na.split()
        assert max(rood.getdata()) > max(groen.getdata())


class TestSamenstellen:
    def test_the_artwork_is_left_untouched(self):
        """Het hele punt: de rastertoon van de tekenaar blijft staan."""
        origineel = _pagina()
        hertekend = Image.new("RGB", (BREED, HOOG), (255, 255, 255))
        samen, _ = stel_samen(origineel, hertekend, [_bubble(0.1, 0.06, 0.6, 0.3)])

        # Ver van de ballon, midden in de 'tekening'.
        for punt in ((100, 500), (300, 450), (200, 540)):
            assert samen.getpixel(punt) == origineel.getpixel(punt), punt

    def test_the_old_text_is_covered(self):
        """Anders staat het Japans dwars door de vertaling heen."""
        origineel = _pagina(tekst="oud", inkt=0)
        # Het model levert dezelfde ballon, maar leeg.
        hertekend = _pagina(tekst="", inkt=0)
        samen, _ = stel_samen(origineel, hertekend, [_bubble(0.1, 0.06, 0.6, 0.3)])
        assert samen.getpixel((140, 100))[0] > 200

    def test_a_bubble_outside_the_page_is_skipped(self):
        origineel = _pagina()
        _, meting = stel_samen(origineel, _pagina(), [_bubble(1.5, 1.5, 2.0, 2.0)])
        assert meting.vakken == 0

    def test_without_bubbles_nothing_from_the_model_is_used(self):
        """Geen tekstvlakken bekend: dan is er niets te vervangen."""
        origineel = _pagina()
        hertekend = Image.new("RGB", (BREED, HOOG), (10, 200, 10))
        samen, meting = stel_samen(origineel, hertekend, [])
        assert meting.vakken == 0
        assert samen.getpixel((140, 100)) != (10, 200, 10)

    def test_a_differently_sized_plate_is_scaled_first(self):
        """Het model levert een andere maat terug (750 erin, 864 eruit)."""
        origineel = _pagina()
        hertekend = _pagina().resize((BREED * 2, HOOG * 2))
        samen, _ = stel_samen(origineel, hertekend, [_bubble(0.1, 0.06, 0.6, 0.3)])
        assert samen.size == origineel.size

    def test_a_cream_plate_does_not_leave_a_beige_patch(self):
        """Het model zet een plaat soms op een beige veld, en dan stond er een
        crème rechthoek op wit papier."""
        origineel = _pagina(papier=(255, 255, 255))
        creme = _pagina(papier=(250, 244, 228), tekst="")
        samen, _ = stel_samen(origineel, creme, [_bubble(0.1, 0.06, 0.6, 0.3)])

        # In de ballon hoort het papier weer wit te zijn, niet beige.
        rood, groen, blauw = samen.getpixel((140, 70))
        assert rood - blauw < 12, f"nog steeds beige: {(rood, groen, blauw)}"

    def test_the_measurement_reports_what_it_did(self):
        _, meting = stel_samen(_pagina(inkt=60), _pagina(), [_bubble(0.1, 0.06, 0.6, 0.3)])
        assert meting.vakken == 1
        assert meting.inktvloer > 2


class TestWegschrijven:
    def test_it_becomes_a_readable_webp(self):
        data = naar_webp(_pagina())
        assert data[:4] == b"RIFF"
        with Image.open(__import__("io").BytesIO(data)) as terug:
            assert terug.size == (BREED, HOOG)


class TestAlsLeesstand:
    """De samengestelde versie is wat de lezer standaard krijgt.

    Op de gescande collectie en niet op een verzonnen boek: het samenstellen
    heeft het origineel nodig, en dat komt uit een echt bestand.
    """

    def _klaarzetten(self, tekstvlakken: bool) -> int:
        from bookpal.translate import sidecar
        from bookpal.translate.modes import TranslateMode
        from bookpal.translate.service import _record

        with session_scope() as s:
            reeks = s.scalar(select(Series).where(Series.title == "Storm"))
            boek = s.scalar(select(Book).where(Book.series_id == reeks.id, Book.number == "1"))
            sidecar.write_bytes(
                sidecar.image_path(reeks, boek, 0, "nl", TranslateMode.IMAGE_FAST),
                naar_webp(_pagina(tekst="")),
            )
            _record(s, boek, 0, "nl", TranslateMode.IMAGE_FAST.provider, {"full_page": True})
            if tekstvlakken:
                # Zowel op schijf als in de index: `bubbles_for` leest de rij,
                # en met een lege payload valt er niets te maskeren.
                vlakken = {
                    "bubbles": [
                        {
                            "box": [0.1, 0.06, 0.6, 0.3],
                            "source": "oud",
                            "translation": "nieuw",
                            "kind": "speech",
                        }
                    ]
                }
                sidecar.write_json(sidecar.json_path(reeks, boek, 0, "nl"), vlakken)
                _record(s, boek, 0, "nl", TranslateMode.TEXT.provider, vlakken)
            return boek.id

    def test_without_bubbles_the_model_plate_is_served(self, scanned: TestClient):
        """Niets te maskeren: dan is de plaat van het model beter dan een fout."""
        from bookpal.translate.modes import TranslateMode
        from bookpal.translate.service import read_masked_page, read_page_image

        boek_id = self._klaarzetten(tekstvlakken=False)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            gemaskeerd = read_masked_page(s, boek, 0, "nl", TranslateMode.IMAGE_FAST)
            ruw = read_page_image(s, boek, 0, "nl", TranslateMode.IMAGE_FAST)
        assert gemaskeerd == ruw

    def test_the_composed_version_is_cached_on_disk(self, scanned: TestClient):
        """Op een N100 wil je dit niet bij elke paginawissel opnieuw doen."""
        from bookpal.translate import sidecar
        from bookpal.translate.modes import TranslateMode
        from bookpal.translate.service import MASKER_VARIANT, read_masked_page

        boek_id = self._klaarzetten(tekstvlakken=True)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            reeks = s.get(Series, boek.series_id)
            pad = sidecar.variant_path(reeks, boek, 0, f"{MASKER_VARIANT}-nl")
            assert not pad.is_file()

            eerste = read_masked_page(s, boek, 0, "nl", TranslateMode.IMAGE_FAST)
            assert pad.is_file()
            assert read_masked_page(s, boek, 0, "nl", TranslateMode.IMAGE_FAST) == eerste

    def test_the_paid_plate_is_never_replaced_on_disk(self, scanned: TestClient):
        """Het masker is rekenwerk; de plaat is het geld."""
        from bookpal.translate import sidecar
        from bookpal.translate.modes import TranslateMode
        from bookpal.translate.service import read_masked_page

        boek_id = self._klaarzetten(tekstvlakken=True)
        with session_scope() as s:
            boek = s.get(Book, boek_id)
            reeks = s.get(Series, boek.series_id)
            plaat = sidecar.image_path(reeks, boek, 0, "nl", TranslateMode.IMAGE_FAST)
            voor = plaat.read_bytes()
            read_masked_page(s, boek, 0, "nl", TranslateMode.IMAGE_FAST)
            assert plaat.read_bytes() == voor

    def test_a_missing_plate_gives_nothing(self, scanned: TestClient):
        from bookpal.translate.modes import TranslateMode
        from bookpal.translate.service import read_masked_page

        with session_scope() as s:
            reeks = s.scalar(select(Series).where(Series.title == "Storm"))
            boek = s.scalar(select(Book).where(Book.series_id == reeks.id, Book.number == "1"))
            assert read_masked_page(s, boek, 0, "nl", TranslateMode.IMAGE_FAST) is None
