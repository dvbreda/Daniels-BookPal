import Testing

@testable import BookPal

/// Dezelfde gevallen als `web/src/reader/spreads.test.ts`. Als de twee lezers
/// uit elkaar lopen hoort dat hier op te vallen, niet op het apparaat.
struct SpreadsTests {
    @Test func test_single_mode_gives_loose_pages() {
        #expect(Spreads.bouw(paginas: 3, dubbel: false, verhoudingen: [:]) == [[0], [1], [2]])
    }

    @Test func test_the_cover_stands_alone_and_the_rest_pairs_up() {
        #expect(Spreads.bouw(paginas: 5, dubbel: true, verhoudingen: [:]) == [[0], [1, 2], [3, 4]])
    }

    @Test func test_a_landscape_page_fills_the_screen_by_itself() {
        // Een uitklapper of dubbelpagina hoort niet naast iets anders.
        let spreads = Spreads.bouw(paginas: 6, dubbel: true, verhoudingen: [3: 1.6])
        #expect(spreads == [[0], [1, 2], [3], [4, 5]])
    }

    @Test func test_a_portrait_page_never_pairs_with_a_landscape_one() {
        let spreads = Spreads.bouw(paginas: 4, dubbel: true, verhoudingen: [1: 0.7, 2: 1.5])
        #expect(spreads == [[0], [1], [2], [3]])
    }

    @Test func test_an_odd_last_page_stays_alone() {
        #expect(Spreads.bouw(paginas: 4, dubbel: true, verhoudingen: [:]) == [[0], [1, 2], [3]])
    }

    @Test func test_the_cover_can_join_in_when_there_is_no_cover_convention() {
        // Webtoons kennen geen omslagpagina.
        let spreads = Spreads.bouw(
            paginas: 4, dubbel: true, verhoudingen: [:], omslagAlleen: false
        )
        #expect(spreads == [[0, 1], [2, 3]])
    }

    @Test func test_portrait_is_assumed_while_the_ratio_is_unknown() {
        #expect(Spreads.bouw(paginas: 3, dubbel: true, verhoudingen: [:]) == [[0], [1, 2]])
    }

    @Test func test_an_empty_book_is_handled() {
        #expect(Spreads.bouw(paginas: 0, dubbel: true, verhoudingen: [:]).isEmpty)
    }

    @Test func test_a_one_page_book_is_handled() {
        #expect(Spreads.bouw(paginas: 1, dubbel: true, verhoudingen: [:]) == [[0]])
    }

    @Test func test_western_comics_are_left_untouched() {
        #expect(Spreads.volgordeVoorScherm([1, 2], rechtsNaarLinks: false) == [1, 2])
    }

    @Test func test_manga_is_mirrored_so_the_right_page_is_read_first() {
        #expect(Spreads.volgordeVoorScherm([1, 2], rechtsNaarLinks: true) == [2, 1])
    }

    @Test func test_a_single_page_is_unchanged_by_mirroring() {
        #expect(Spreads.volgordeVoorScherm([5], rechtsNaarLinks: true) == [5])
    }

    @Test func test_the_place_is_remembered_across_a_mode_switch() {
        let spreads = [[0], [1, 2], [3, 4], [5]]
        #expect(Spreads.spreadVanPagina(spreads, pagina: 4) == 2)
    }

    @Test func test_an_unknown_page_falls_back_to_the_start() {
        #expect(Spreads.spreadVanPagina([[0], [1]], pagina: 99) == 0)
    }

    @Test func test_preloading_goes_forward_and_one_spread_back() {
        let spreads = [[0], [1, 2], [3, 4], [5, 6]]
        #expect(Spreads.vooruitLaden(spreads, huidige: 1, vooruit: 2) == [3, 4, 5, 6, 0])
    }

    @Test func test_preloading_does_not_run_past_the_end() {
        let spreads = [[0], [1], [2]]
        #expect(Spreads.vooruitLaden(spreads, huidige: 2, vooruit: 3) == [1])
    }

    @Test func test_percent_counts_the_last_page_of_the_spread() {
        let spreads = [[0], [1, 2], [3, 4]]
        #expect(Spreads.percentVoor(spreads, spreadIndex: 1, paginas: 10) == 30)
    }

    @Test func test_percent_is_a_hundred_at_the_end() {
        let spreads = [[0], [1, 2], [3, 4]]
        #expect(Spreads.percentVoor(spreads, spreadIndex: 2, paginas: 5) == 100)
    }

    @Test func test_percent_is_zero_without_pages() {
        #expect(Spreads.percentVoor([[0]], spreadIndex: 0, paginas: 0) == 0)
    }
}
