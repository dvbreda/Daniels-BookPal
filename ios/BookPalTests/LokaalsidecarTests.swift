import Foundation
import Testing

@testable import BookPal

/// De namen moeten letterlijk gelijk zijn aan wat de server verwacht.
///
/// De upload gaat naar `/api/sidecars/{boek}/{naam}`, en dáár loopt de naam
/// langs een strenge regex (`inventory._NAAM`) die alleen de vormen doorlaat
/// die de server zelf ook schrijft. Eén teken ernaast en de pagina wordt
/// geweigerd — met als gevolg dat betaald werk op de telefoon blijft hangen.
struct LokaalsidecarTests {
    @Test func test_the_redrawn_name_matches_the_server_format() {
        #expect(
            Lokaalsidecar.hertekendNaam(pagina: 7, taal: "nl", zwaar: false)
                == "p0007-nl-image_fast.webp"
        )
        #expect(
            Lokaalsidecar.hertekendNaam(pagina: 7, taal: "nl", zwaar: true)
                == "p0007-nl-image_pro.webp"
        )
    }

    @Test func test_the_colour_name_matches_the_server_format() {
        #expect(Lokaalsidecar.kleurNaam(pagina: 0) == "p0000-kleur.webp")
    }

    @Test func test_page_numbers_are_padded_to_four_digits() {
        // Met nullen ervoor, zodat een `ls` in leesvolgorde staat — dezelfde
        // reden als op de server.
        #expect(Lokaalsidecar.kleurNaam(pagina: 3).hasPrefix("p0003"))
        #expect(Lokaalsidecar.kleurNaam(pagina: 42).hasPrefix("p0042"))
        #expect(Lokaalsidecar.kleurNaam(pagina: 1234).hasPrefix("p1234"))
    }

    /// Het patroon dat de server aanhoudt, hier nagebouwd: als deze test
    /// slaagt maar de server weigert, is de regex daar veranderd.
    @Test func test_the_names_pass_the_server_side_pattern() throws {
        let patroon = try NSRegularExpression(
            pattern: #"^p(\d{4})-([a-z]{2}|[a-z]{2}-image_(?:fast|pro)|kleur|kleur-ruw|kleur-[a-z]{2})\.(json|webp)$"#
        )
        for naam in [
            Lokaalsidecar.hertekendNaam(pagina: 7, taal: "nl", zwaar: false),
            Lokaalsidecar.hertekendNaam(pagina: 12, taal: "en", zwaar: true),
            Lokaalsidecar.kleurNaam(pagina: 0),
        ] {
            let bereik = NSRange(naam.startIndex..., in: naam)
            #expect(patroon.firstMatch(in: naam, range: bereik) != nil, "\(naam) werd geweigerd")
        }
    }
}

/// De modelnamen moeten gelijk blijven aan `server/bookpal/config.py`.
struct LokaalVertalerTests {
    @Test func test_the_model_names_match_the_server() {
        #expect(LokaalVertaler.model(zwaar: false) == "gemini-3.1-flash-image")
        #expect(LokaalVertaler.model(zwaar: true) == "gemini-3-pro-image")
    }
}
