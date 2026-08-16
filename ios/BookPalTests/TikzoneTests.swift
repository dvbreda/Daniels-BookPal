import Testing

@testable import BookPal

/// Links terug, rechts verder — en bij manga andersom.
struct TikzoneTests {
    @Test func test_the_left_edge_goes_back_in_a_western_comic() {
        #expect(Tikzone.voor(x: 0.05, rechtsNaarLinks: false) == .vorige)
    }

    @Test func test_the_right_edge_goes_forward_in_a_western_comic() {
        #expect(Tikzone.voor(x: 0.95, rechtsNaarLinks: false) == .volgende)
    }

    @Test func test_manga_is_mirrored() {
        // Bij manga begint de pagina rechts, dus links is juist verder.
        #expect(Tikzone.voor(x: 0.05, rechtsNaarLinks: true) == .volgende)
        #expect(Tikzone.voor(x: 0.95, rechtsNaarLinks: true) == .vorige)
    }

    @Test func test_the_middle_toggles_the_bar() {
        #expect(Tikzone.voor(x: 0.5, rechtsNaarLinks: false) == .balk)
        #expect(Tikzone.voor(x: 0.5, rechtsNaarLinks: true) == .balk)
    }

    @Test func test_the_middle_strip_is_wide_enough_to_hit_without_aiming() {
        // Een derde van de breedte: raak te tikken zonder te mikken, en smal
        // genoeg om het bladeren niet in de weg te zitten.
        #expect(Tikzone.voor(x: 0.4, rechtsNaarLinks: false) == .balk)
        #expect(Tikzone.voor(x: 0.6, rechtsNaarLinks: false) == .balk)
    }

    @Test func test_just_outside_the_middle_already_turns_the_page() {
        #expect(Tikzone.voor(x: 0.2, rechtsNaarLinks: false) == .vorige)
        #expect(Tikzone.voor(x: 0.8, rechtsNaarLinks: false) == .volgende)
    }
}

/// De rastervormen en het doorlopen ervan met de knop in de balk.
struct RastervormTests {
    @Test func test_stepping_through_ends_at_off() {
        // De knop loopt door de standen en komt weer bij "uit" uit, zodat je
        // hem zonder het paneel kunt uitzetten.
        var vorm = Rastervorm.keuzes.last!
        vorm = Rastervorm.volgende(na: vorm)
        #expect(vorm == .uit)
    }

    @Test func test_stepping_from_off_starts_at_the_first_shape() {
        #expect(Rastervorm.volgende(na: .uit) == Rastervorm.keuzes[0])
    }

    @Test func test_the_number_of_cells_is_rows_times_columns() {
        #expect(Rastervorm(rijen: 3, kolommen: 2).cellen == 6)
        #expect(Rastervorm.uit.cellen == 0)
    }

    @Test func test_there_are_more_shapes_than_the_three_we_started_with() {
        #expect(Rastervorm.keuzes.count > 3)
    }
}

/// De weergaveknop loopt door alle drie de standen.
struct WeergavestandTests {
    @Test func test_the_button_cycles_through_all_three() {
        // Panelen zijn een gewone leesstand; je hoort er niet voor in een
        // instellingenpaneel te hoeven duiken.
        var stand = Weergavestand.paginas
        var gezien: [Weergavestand] = [stand]
        for _ in 0..<2 {
            stand = stand.volgende
            gezien.append(stand)
        }
        #expect(Set(gezien).count == 3)
    }

    @Test func test_cycling_comes_back_to_where_it_started() {
        var stand = Weergavestand.paginas
        for _ in 0..<Weergavestand.allCases.count { stand = stand.volgende }
        #expect(stand == .paginas)
    }
}

/// Dubbeltikken wisselt tussen de twee uitersten van hoe je een strip leest.
struct DubbeltikTests {
    @Test func test_panel_zoom_and_continuous_swap() {
        #expect(Weergavestand.panelen.naDubbeltik == .doorlopend)
        #expect(Weergavestand.doorlopend.naDubbeltik == .panelen)
    }

    @Test func test_from_pages_you_land_in_panel_zoom_first() {
        // Vanuit de gewone paginastand is inzoomen op panelen wat je bedoelt;
        // doorlopend is een stap verder weg.
        #expect(Weergavestand.paginas.naDubbeltik == .panelen)
    }

    @Test func test_tapping_twice_brings_you_back() {
        #expect(Weergavestand.panelen.naDubbeltik.naDubbeltik == .panelen)
    }
}
