import Testing

@testable import BookPal

/// Gespiegeld aan `web/src/reader/grid.test.ts`. De leesrichting is hier het
/// hele punt: cel 0 zit bij manga rechtsboven, en dat is precies het soort ding
/// dat er op het scherm "bijna goed" uitziet.
struct RasterTests {
    @Test func test_western_reading_runs_left_to_right() {
        let cellen = Raster.volgorde(rijen: 2, kolommen: 2, rechtsNaarLinks: false)
        #expect(cellen.map(\.kolom) == [0, 1, 0, 1])
        #expect(cellen.map(\.rij) == [0, 0, 1, 1])
    }

    @Test func test_manga_starts_at_the_top_right() {
        let cellen = Raster.volgorde(rijen: 2, kolommen: 2, rechtsNaarLinks: true)
        #expect(cellen.first == Rastercel(rij: 0, kolom: 1))
        #expect(cellen.map(\.kolom) == [1, 0, 1, 0])
    }

    @Test func test_the_scale_follows_the_largest_side() {
        // Bij 3×2 wil je niet dat een cel horizontaal past maar verticaal half
        // leeg blijft — dan lees je alsnog niets.
        let sprong = Raster.sprong(naar: Rastercel(rij: 0, kolom: 0), rijen: 3, kolommen: 2)
        #expect(sprong.schaal == 3)
    }

    @Test func test_the_top_left_cell_shifts_down_and_right() {
        let sprong = Raster.sprong(naar: Rastercel(rij: 0, kolom: 0), rijen: 2, kolommen: 2)
        #expect(sprong.verschuifX == 0.25)
        #expect(sprong.verschuifY == 0.25)
    }

    @Test func test_the_bottom_right_cell_shifts_the_other_way() {
        let sprong = Raster.sprong(naar: Rastercel(rij: 1, kolom: 1), rijen: 2, kolommen: 2)
        #expect(sprong.verschuifX == -0.25)
        #expect(sprong.verschuifY == -0.25)
    }

    @Test func test_a_tap_lands_in_the_right_cell() {
        #expect(Raster.cel(opX: 0.1, y: 0.1, rijen: 2, kolommen: 2) == Rastercel(rij: 0, kolom: 0))
        #expect(Raster.cel(opX: 0.9, y: 0.9, rijen: 2, kolommen: 2) == Rastercel(rij: 1, kolom: 1))
    }

    @Test func test_a_tap_on_the_very_edge_stays_inside_the_grid() {
        // Precies op 1.0 tikken zou anders een cel opleveren die niet bestaat.
        #expect(Raster.cel(opX: 1.0, y: 1.0, rijen: 2, kolommen: 2) == Rastercel(rij: 1, kolom: 1))
    }

    @Test func test_a_cell_can_be_found_back_in_the_reading_order() {
        let index = Raster.index(
            van: Rastercel(rij: 1, kolom: 0), rijen: 2, kolommen: 2, rechtsNaarLinks: false
        )
        #expect(index == 2)
    }
}

/// Gespiegeld aan `web/src/reader/bubbles.test.ts`.
struct BallonnenTests {
    @Test func test_a_box_grows_outward_on_all_sides() {
        let vlak = Ballonnen.rekOp([0.2, 0.2, 0.4, 0.4], groei: 0.5)
        #expect(vlak[0] == 0.1)
        #expect(vlak[2].isApproximately(0.5))
    }

    @Test func test_growing_never_runs_off_the_page() {
        let vlak = Ballonnen.rekOp([0.0, 0.0, 1.0, 1.0], groei: 0.5)
        #expect(vlak == [0, 0, 1, 1])
    }

    @Test func test_a_short_line_in_a_big_box_is_not_shrunk() {
        // Groter dan de basismaat wordt het nooit; anders zou een kort woord
        // ineens beeldvullend worden.
        #expect(Ballonnen.letterschaal(vlak: [0, 0, 0.5, 0.5], tekens: 5) == 1)
    }

    @Test func test_a_long_line_in_a_small_box_shrinks() {
        let schaal = Ballonnen.letterschaal(vlak: [0, 0, 0.1, 0.1], tekens: 200)
        #expect(schaal < 1)
        #expect(schaal > 0)
    }

    @Test func test_an_empty_box_does_not_divide_by_zero() {
        #expect(Ballonnen.letterschaal(vlak: [0.5, 0.5, 0.5, 0.5], tekens: 10) == 1)
    }
}

/// De bronkeuze moet gelijk zijn aan `pageSource` in de web-lezer: het gaat om
/// betaald werk, en uit elkaar lopen betekent dat je op je telefoon iets anders
/// ziet dan in de browser.
struct PaginakeuzeTests {
    private func kleur(available: Bool, translated: Bool = false) -> ColourInfo {
        ColourInfo(available: available, native: false, translated: translated)
    }

    @Test func test_without_anything_switched_on_you_get_the_original() {
        let keuze = Paginakeuze.kies(
            vertaling: false, kleurAan: false, heeftHertekend: true,
            kleur: kleur(available: true), taal: "nl"
        )
        #expect(keuze == .origineel)
    }

    @Test func test_colour_wins_over_a_redrawn_page() {
        // Dit ging aan de webkant een keer mis: de lezer koos de hertekende
        // pagina zodra die bestond en kwam nooit bij de kleur uit.
        let keuze = Paginakeuze.kies(
            vertaling: true, kleurAan: true, heeftHertekend: true,
            kleur: kleur(available: true), taal: "nl"
        )
        #expect(keuze == .kleur(taal: nil))
    }

    @Test func test_a_coloured_translated_page_is_asked_for_by_language() {
        let keuze = Paginakeuze.kies(
            vertaling: true, kleurAan: true, heeftHertekend: false,
            kleur: kleur(available: true, translated: true), taal: "nl"
        )
        #expect(keuze == .kleur(taal: "nl"))
    }

    @Test func test_colour_switched_on_without_colour_available_falls_through() {
        let keuze = Paginakeuze.kies(
            vertaling: true, kleurAan: true, heeftHertekend: true,
            kleur: kleur(available: false), taal: "nl"
        )
        #expect(keuze == .hertekend)
    }

    @Test func test_our_own_bubbles_go_over_a_coloured_page() {
        // De ingekleurde pagina is van het origineel gemaakt, dus daar staan nog
        // de oorspronkelijke letters in. Daarom kunnen kleur en de tekststand
        // samen.
        #expect(Paginakeuze.kleur(taal: nil).tekentBallonnen)
        #expect(Paginakeuze.origineel.tekentBallonnen)
    }

    @Test func test_our_own_bubbles_do_not_go_over_a_redrawn_page() {
        #expect(!Paginakeuze.hertekend.tekentBallonnen)
    }
}

extension Double {
    func isApproximately(_ ander: Double, marge: Double = 1e-9) -> Bool {
        abs(self - ander) < marge
    }
}
