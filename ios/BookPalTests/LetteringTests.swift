import Testing
import UIKit

@testable import BookPal

/// De striplettering moet echt geladen zijn.
///
/// Dit is precies het soort fout dat je anders pas op het apparaat ziet: klopt
/// de PostScript-naam niet, of zit het bestand niet in `UIAppFonts`, dan valt
/// SwiftUI stil terug op het systeemfont. Geen foutmelding, geen crash — alleen
/// ballonnen die er ineens uitzien als een tekstverwerker.
struct LetteringTests {
    @Test func test_every_style_of_the_comic_lettering_is_available() {
        for naam in [Striplettering.regular, Striplettering.vet, Striplettering.cursief] {
            #expect(
                UIFont(name: naam, size: 12) != nil,
                "lettertype «\(naam)» is niet geladen — staat het in UIAppFonts?"
            )
        }
    }

    @Test func test_bold_wins_when_a_shout_is_both_bold_and_italic() {
        // Er is geen vet-cursieve snede. Vet wint, want dat oordeel van het
        // model bleef in alle metingen stabiel en italic niet.
        #expect(Striplettering.naam(vet: true, cursief: true, kreet: true) == Striplettering.vet)
    }

    @Test func test_only_a_shout_is_set_in_bold() {
        // Vet is in een strip voorbehouden aan "BOEM" en "WAT!?". Een hele
        // alinea vet is geen nadruk meer maar geschreeuw.
        #expect(Striplettering.naam(vet: true, cursief: false, kreet: true) == Striplettering.vet)
        #expect(
            Striplettering.naam(vet: true, cursief: false, kreet: false) == Striplettering.regular
        )
    }

    @Test func test_a_plain_bubble_gets_the_plain_cut() {
        #expect(
            Striplettering.naam(vet: false, cursief: false, kreet: false) == Striplettering.regular
        )
    }

    @Test func test_an_italic_bubble_gets_the_italic_cut() {
        // Cursief blijft ook bij lopende tekst: dat is echte nadruk in een zin,
        // geen geschreeuw.
        #expect(
            Striplettering.naam(vet: false, cursief: true, kreet: false) == Striplettering.cursief
        )
    }
}

/// De opgemeten pasmaat. Dit verving een schatting die bij lange zinnen buiten
/// de ballon liep.
struct PassendeGrootteTests {
    private let vlak = CGSize(width: 200, height: 100)

    @Test func test_a_long_text_gets_a_smaller_size_than_a_short_one() {
        let kort = Ballonnen.passendeGrootte(
            "Hoi!", in: vlak, fontnaam: Striplettering.regular, maximum: 40
        )
        let lang = Ballonnen.passendeGrootte(
            String(repeating: "een lange zin ", count: 12),
            in: vlak, fontnaam: Striplettering.regular, maximum: 40
        )
        #expect(lang < kort)
    }

    @Test func test_the_result_never_exceeds_the_maximum() {
        let grootte = Ballonnen.passendeGrootte(
            "A", in: vlak, fontnaam: Striplettering.regular, maximum: 20
        )
        #expect(grootte <= 20)
    }

    @Test func test_the_measured_text_actually_fits_the_box() {
        let tekst = String(repeating: "WAT EEN BEELDJE! DIE GA IK PASSEN! ", count: 4)
        let grootte = Ballonnen.passendeGrootte(
            tekst, in: vlak, fontnaam: Striplettering.regular, maximum: 40
        )
        let font = UIFont(name: Striplettering.regular, size: grootte)
        let kader = (tekst as NSString).boundingRect(
            with: CGSize(width: vlak.width, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: font as Any],
            context: nil
        )
        #expect(kader.height <= vlak.height)
    }

    @Test func test_a_box_of_nothing_does_not_crash() {
        let grootte = Ballonnen.passendeGrootte(
            "iets", in: .zero, fontnaam: Striplettering.regular, maximum: 40
        )
        #expect(grootte > 0)
    }
}

/// De begrenzing: korte kreten mogen groot, lopende tekst niet.
struct BegrenzingTests {
    @Test func test_a_short_shout_may_fill_its_balloon() {
        // "EH?" of "HAHA" groot zetten is juist hoe een strip gelettered is.
        let uit = Ballonnen.begrens([40], tekens: ["EH?".count], leesmaat: 15)
        #expect(uit == [40])
    }

    @Test func test_a_long_line_is_capped_at_the_reading_size() {
        let lang = String(repeating: "een hele zin ", count: 5)
        let uit = Ballonnen.begrens([40], tekens: [lang.count], leesmaat: 15)
        #expect(uit == [15])
    }

    @Test func test_a_long_line_that_already_fits_small_is_left_alone() {
        // Nooit naar bóven bijstellen: groter dan wat past loopt de ballon uit.
        let lang = String(repeating: "een hele zin ", count: 5)
        let uit = Ballonnen.begrens([9], tekens: [lang.count], leesmaat: 15)
        #expect(uit == [9])
    }

    @Test func test_each_balloon_is_judged_on_its_own_length() {
        let uit = Ballonnen.begrens(
            [40, 40], tekens: ["HAHA".count, 200], leesmaat: 15
        )
        #expect(uit == [40, 15])
    }

    @Test func test_no_balloons_is_handled() {
        #expect(Ballonnen.begrens([], tekens: [], leesmaat: 15).isEmpty)
    }
}
