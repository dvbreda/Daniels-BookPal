"""Paneeldetectie zonder model.

De pagina's worden hier getekend in plaats van meegeleverd — dezelfde afspraak
als voor de rest van de suite: er staat geen leesmateriaal in de repo. Een
getekende pagina heeft bovendien een bekend antwoord, en dat is precies wat je
van een test wilt.

Op echte pagina's uit de eigen bibliotheek gemeten (Oishinbo deel 3, hoofdstuk
23): 3 tot 8 panelen per pagina in ongeveer 110 ms, met een plaat ernaast om te
controleren dat de vakken om de panelen zaten.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from bookpal.images.panels import Panel, detect, reading_order


def pagina(vakken: list[tuple[int, int, int, int]], maat=(600, 900)) -> bytes:
    """Een witte pagina met gevulde panelen op de gevraagde plekken.

    De panelen worden gevuld en niet met een lijntje aangeduid. Dat lijkt een
    detail maar is het niet: een goot mag tot 5% inkt bevatten (zie
    GOOT_VULLING), dus elke rij bínnen een paneel moet daar duidelijk boven
    zitten. Met een dun lijntje of ruime arcering haalt hij dat niet, gaat het
    paneel zelf aan stukken, en test de fixture iets anders dan een
    stripbladzijde. Echte tekening is dicht.
    """
    beeld = Image.new("L", maat, 255)
    tekenaar = ImageDraw.Draw(beeld)
    for vak in vakken:
        x0, y0, x1, y1 = vak
        tekenaar.rectangle([x0 + 8, y0 + 8, x1 - 8, y1 - 8], fill=110)
        tekenaar.rectangle(vak, outline=0, width=6)
    buffer = io.BytesIO()
    beeld.save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_page_of_four_panels_is_split_into_four() -> None:
    beeld = pagina(
        [(40, 40, 280, 420), (320, 40, 560, 420), (40, 470, 280, 860), (320, 470, 560, 860)]
    )
    assert len(detect(beeld)) == 4


def test_a_page_of_two_rows_is_split_into_two() -> None:
    beeld = pagina([(40, 40, 560, 420), (40, 470, 560, 860)])
    assert len(detect(beeld)) == 2


def test_a_splash_without_gutters_stays_one_panel() -> None:
    """Een pagina zonder goten ís één paneel; dat is geen mislukking."""
    beeld = pagina([(20, 20, 580, 880)])
    panelen = detect(beeld)
    assert len(panelen) == 1
    assert panelen[0].as_list() == [0.0, 0.0, 1.0, 1.0]


def test_an_empty_page_falls_back_to_the_whole_page() -> None:
    beeld = Image.new("L", (400, 600), 255)
    buffer = io.BytesIO()
    beeld.save(buffer, format="PNG")
    panelen = detect(buffer.getvalue())
    assert len(panelen) == 1


def test_panels_stay_inside_the_page() -> None:
    beeld = pagina([(40, 40, 280, 420), (320, 40, 560, 420)])
    for paneel in detect(beeld):
        assert 0.0 <= paneel.x0 < paneel.x1 <= 1.0
        assert 0.0 <= paneel.y0 < paneel.y1 <= 1.0


def test_western_reading_runs_left_to_right() -> None:
    links = Panel(0.05, 0.05, 0.45, 0.45)
    rechts = Panel(0.55, 0.05, 0.95, 0.45)
    volgorde = reading_order([rechts, links], right_to_left=False)
    assert volgorde[0] is links


def test_manga_starts_at_the_top_right() -> None:
    """Bij manga leest de rechterkolom eerst — dat is de hele reden dat deze
    functie apart staat en eigen tests heeft."""
    links = Panel(0.05, 0.05, 0.45, 0.45)
    rechts = Panel(0.55, 0.05, 0.95, 0.45)
    volgorde = reading_order([links, rechts], right_to_left=True)
    assert volgorde[0] is rechts


def test_a_row_lower_on_the_page_comes_later() -> None:
    boven = Panel(0.05, 0.05, 0.95, 0.45)
    onder = Panel(0.05, 0.55, 0.95, 0.95)
    volgorde = reading_order([onder, boven], right_to_left=False)
    assert volgorde == [boven, onder]


def test_panels_that_are_slightly_offset_stay_in_the_same_row() -> None:
    """Een paneel dat een paar pixels hoger begint hoort niet ineens een eigen
    rij te worden — anders klopt de leesvolgorde bij elke onregelmatige pagina
    niet meer."""
    links = Panel(0.05, 0.05, 0.45, 0.45)
    rechts = Panel(0.55, 0.07, 0.95, 0.47)
    volgorde = reading_order([rechts, links], right_to_left=False)
    assert volgorde == [links, rechts]


def test_a_detected_page_reads_top_row_first() -> None:
    beeld = pagina(
        [(40, 40, 280, 420), (320, 40, 560, 420), (40, 470, 560, 860)]
    )
    panelen = detect(beeld)
    assert len(panelen) == 3
    # De onderste strook hoort als laatste te komen.
    assert panelen[-1].y0 > panelen[0].y0
