import Testing
import UIKit

@testable import BookPal

/// Gespiegeld aan `server/tests/test_panels.py`.
///
/// Dat is hier geen nettigheid maar het hele punt: dit is een tweede
/// implementatie van hetzelfde algoritme, en die lopen uit elkaar zodra je er
/// één aanpast. De pagina's worden getekend, net als aan de serverkant — een
/// getekende pagina heeft een bekend antwoord, en er staat geen leesmateriaal
/// in de repo.
struct PanelenTests {
    /// Een witte pagina met zwarte kaders op de gevraagde plekken.
    private func pagina(
        _ vakken: [CGRect], maat: CGSize = CGSize(width: 600, height: 900)
    ) -> UIImage {
        UIGraphicsImageRenderer(size: maat).image { context in
            UIColor.white.setFill()
            context.fill(CGRect(origin: .zero, size: maat))
            UIColor.black.setStroke()
            for vak in vakken {
                // Gevuld en niet met een lijntje aangeduid: een goot mag tot 5%
                // inkt bevatten, dus een rij bínnen een paneel moet daar
                // duidelijk boven zitten. Met een dun lijntje gaat het paneel
                // zelf aan stukken. Zie dezelfde uitleg in test_panels.py.
                UIColor(white: 110.0 / 255.0, alpha: 1).setFill()
                UIBezierPath(rect: vak.insetBy(dx: 8, dy: 8)).fill()
                let pad = UIBezierPath(rect: vak)
                pad.lineWidth = 6
                pad.stroke()
            }
        }
    }

    @Test func test_a_page_of_four_panels_is_split_into_four() {
        let beeld = pagina([
            CGRect(x: 40, y: 40, width: 240, height: 380),
            CGRect(x: 320, y: 40, width: 240, height: 380),
            CGRect(x: 40, y: 470, width: 240, height: 390),
            CGRect(x: 320, y: 470, width: 240, height: 390),
        ])
        #expect(Panelen.vind(in: beeld, rechtsNaarLinks: false).count == 4)
    }

    @Test func test_a_page_of_two_rows_is_split_into_two() {
        let beeld = pagina([
            CGRect(x: 40, y: 40, width: 520, height: 380),
            CGRect(x: 40, y: 470, width: 520, height: 390),
        ])
        #expect(Panelen.vind(in: beeld, rechtsNaarLinks: false).count == 2)
    }

    @Test func test_a_splash_without_gutters_stays_one_panel() {
        let beeld = pagina([CGRect(x: 20, y: 20, width: 560, height: 860)])
        let panelen = Panelen.vind(in: beeld, rechtsNaarLinks: false)
        #expect(panelen.count == 1)
        #expect(panelen[0].isHelePagina)
    }

    @Test func test_panels_stay_inside_the_page() {
        let beeld = pagina([
            CGRect(x: 40, y: 40, width: 240, height: 380),
            CGRect(x: 320, y: 40, width: 240, height: 380),
        ])
        for paneel in Panelen.vind(in: beeld, rechtsNaarLinks: false) {
            #expect(paneel.x0 >= 0 && paneel.x1 <= 1 && paneel.x0 < paneel.x1)
            #expect(paneel.y0 >= 0 && paneel.y1 <= 1 && paneel.y0 < paneel.y1)
        }
    }

    @Test func test_western_reading_runs_left_to_right() {
        let links = Paneel(x0: 0.05, y0: 0.05, x1: 0.45, y1: 0.45)
        let rechts = Paneel(x0: 0.55, y0: 0.05, x1: 0.95, y1: 0.45)
        #expect(Panelen.leesvolgorde([rechts, links], rechtsNaarLinks: false)[0] == links)
    }

    @Test func test_manga_starts_at_the_top_right() {
        let links = Paneel(x0: 0.05, y0: 0.05, x1: 0.45, y1: 0.45)
        let rechts = Paneel(x0: 0.55, y0: 0.05, x1: 0.95, y1: 0.45)
        #expect(Panelen.leesvolgorde([links, rechts], rechtsNaarLinks: true)[0] == rechts)
    }

    @Test func test_panels_that_are_slightly_offset_stay_in_the_same_row() {
        // Een paneel dat een paar pixels hoger begint hoort geen eigen rij te
        // worden — anders klopt de volgorde bij elke onregelmatige pagina niet.
        let links = Paneel(x0: 0.05, y0: 0.05, x1: 0.45, y1: 0.45)
        let rechts = Paneel(x0: 0.55, y0: 0.07, x1: 0.95, y1: 0.47)
        #expect(Panelen.leesvolgorde([rechts, links], rechtsNaarLinks: false) == [links, rechts])
    }

    @Test func test_a_row_lower_on_the_page_comes_later() {
        let boven = Paneel(x0: 0.05, y0: 0.05, x1: 0.95, y1: 0.45)
        let onder = Paneel(x0: 0.05, y0: 0.55, x1: 0.95, y1: 0.95)
        #expect(Panelen.leesvolgorde([onder, boven], rechtsNaarLinks: false) == [boven, onder])
    }
}

/// Heen en terug door de panelen, over de paginagrens heen.
struct PaneelpadTests {
    private func drie(_ pagina: Int) -> Int { 3 }

    @Test func test_stepping_forward_stays_on_the_page_while_there_are_panels() {
        let pad = Paneelpad(pagina: 2, paneel: 0)
        #expect(pad.volgende(aantal: drie, paginas: 10) == Paneelpad(pagina: 2, paneel: 1))
    }

    @Test func test_every_page_starts_with_the_whole_page() {
        // Eerst zien hoe de bladzijde in elkaar zit, dan pas inzoomen — net als
        // wanneer je een strip op papier omslaat.
        let pad = Paneelpad(pagina: 2, paneel: 2)
        let volgende = pad.volgende(aantal: drie, paginas: 10)
        #expect(volgende == Paneelpad(pagina: 3, paneel: Paneelpad.overzicht))
        #expect(volgende?.isOverzicht == true)
    }

    @Test func test_from_the_overview_you_step_into_the_first_panel() {
        let pad = Paneelpad(pagina: 2, paneel: Paneelpad.overzicht)
        #expect(pad.volgende(aantal: drie, paginas: 10) == Paneelpad(pagina: 2, paneel: 0))
    }

    @Test func test_going_back_from_the_first_panel_lands_on_the_overview() {
        let pad = Paneelpad(pagina: 2, paneel: 0)
        #expect(pad.vorige(aantal: drie)?.isOverzicht == true)
    }

    @Test func test_going_back_from_an_overview_lands_on_the_last_panel_before_it() {
        // Je leest die pagina achterstevoren in, dus je hoort op het laatste
        // paneel uit te komen en niet op het overzicht.
        let pad = Paneelpad(pagina: 3, paneel: Paneelpad.overzicht)
        #expect(pad.vorige(aantal: drie) == Paneelpad(pagina: 2, paneel: 2))
    }

    @Test func test_the_end_of_the_book_has_no_next() {
        let pad = Paneelpad(pagina: 9, paneel: 2)
        #expect(pad.volgende(aantal: drie, paginas: 10) == nil)
    }

    @Test func test_the_start_of_the_book_has_no_previous() {
        let pad = Paneelpad(pagina: 0, paneel: Paneelpad.overzicht)
        #expect(pad.vorige(aantal: drie) == nil)
    }

    @Test func test_a_page_that_is_not_examined_yet_counts_as_one_panel() {
        // Zo loop je nooit vast op iets dat nog moet laden.
        let pad = Paneelpad(pagina: 0, paneel: 0)
        #expect(
            pad.volgende(aantal: { _ in 1 }, paginas: 3)
                == Paneelpad(pagina: 1, paneel: Paneelpad.overzicht)
        )
    }
}

/// Een echte scan heeft geen spierwit papier maar vergeeld papier met korrel.
///
/// Dit is precies waar de eerste versie op stukliep: de app tekende naar
/// `linearGray`, waardoor papier van 245 onder de inktdrempel zakte en de hele
/// pagina als inkt gold — geen goten, geen panelen. Op getekende pagina's met
/// spierwit papier viel dat niet op.
struct VuilPapierTests {
    private func vuilePagina(_ vakken: [CGRect]) -> UIImage {
        let maat = CGSize(width: 600, height: 900)
        return UIGraphicsImageRenderer(size: maat).image { context in
            // Vergeeld papier, niet 255.
            UIColor(white: 245.0 / 255.0, alpha: 1).setFill()
            context.fill(CGRect(origin: .zero, size: maat))
            UIColor.black.setStroke()
            for vak in vakken {
                // Gevuld en niet met een lijntje aangeduid: een goot mag tot 5%
                // inkt bevatten, dus een rij bínnen een paneel moet daar
                // duidelijk boven zitten. Met een dun lijntje gaat het paneel
                // zelf aan stukken. Zie dezelfde uitleg in test_panels.py.
                UIColor(white: 110.0 / 255.0, alpha: 1).setFill()
                UIBezierPath(rect: vak.insetBy(dx: 8, dy: 8)).fill()
                let pad = UIBezierPath(rect: vak)
                pad.lineWidth = 6
                pad.stroke()
            }
        }
    }

    @Test func test_panels_are_still_found_on_off_white_paper() {
        let beeld = vuilePagina([
            CGRect(x: 40, y: 40, width: 240, height: 380),
            CGRect(x: 320, y: 40, width: 240, height: 380),
            CGRect(x: 40, y: 470, width: 240, height: 390),
            CGRect(x: 320, y: 470, width: 240, height: 390),
        ])
        #expect(Panelen.vind(in: beeld, rechtsNaarLinks: false).count == 4)
    }
}

/// De marge rondom een paneel bij het inzoomen.
struct PaneelmargeTests {
    private let paneel = Paneel(x0: 0.3, y0: 0.3, x1: 0.5, y1: 0.5)

    @Test func test_no_margin_leaves_the_panel_alone() {
        #expect(paneel.metMarge(0, verhouding: 1.4) == paneel)
    }

    @Test func test_the_margin_widens_the_panel_on_both_sides() {
        let ruim = paneel.metMarge(0.05, verhouding: 1)
        #expect(ruim.x0 == 0.25)
        #expect(ruim.x1 == 0.55)
    }

    @Test func test_a_tall_page_gets_a_smaller_margin_in_page_units() {
        // De marge is een deel van de bréédte. Op een pagina die anderhalf keer
        // zo hoog is als breed moet hij verticaal dus kleiner zijn in
        // paginadelen, anders ziet hij er dikker uit dan aan de zijkanten.
        let ruim = paneel.metMarge(0.06, verhouding: 1.5)
        #expect(abs((paneel.y0 - ruim.y0) - 0.04) < 1e-9)
        #expect(abs((paneel.x0 - ruim.x0) - 0.06) < 1e-9)
    }

    @Test func test_the_margin_never_runs_off_the_page() {
        let randpaneel = Paneel(x0: 0.0, y0: 0.0, x1: 0.4, y1: 0.4)
        let ruim = randpaneel.metMarge(0.10, verhouding: 1.4)
        #expect(ruim.x0 == 0)
        #expect(ruim.y0 == 0)
    }

    @Test func test_the_whole_page_cannot_grow() {
        #expect(Paneel.helePagina.metMarge(0.10, verhouding: 1.4) == .helePagina)
    }
}

