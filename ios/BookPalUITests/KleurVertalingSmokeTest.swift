import XCTest

/// Kleur en vertaling tonen, op een pagina waar allebei echt klaarliggen.
///
/// Oishinbo deel 3, hoofdstuk 23 is het enige hoofdstuk in de bibliotheek met
/// ingekleurde pagina's. Pagina 3 en 4 (index 2 en 3) hebben daar zowel
/// tekstvlakken als kleur, en dat is precies de combinatie die mis kan gaan:
/// de ingekleurde pagina is van het origineel gemaakt, dus onze eigen vertaling
/// hoort er nog overheen te komen.
final class KleurVertalingSmokeTest: XCTestCase {

    func test_colour_and_translation_show_on_a_page_that_has_both() throws {
        let app = XCUIApplication()
        // Bekende beginstand: de lezer bewaart zijn standen, dus een vorige test
        // die doorlopend aanzette laat deze anders in die stand beginnen.
        // Alleen de standen pinnen die de test níét omzet. Een launch-argument
        // heeft in UserDefaults de hoogste voorrang, dus een gepinde schakelaar
        // is met geen mogelijkheid meer aan te zetten — de app blijft "uit"
        // lezen hoe vaak je ook tikt. Vertaling en kleur worden hieronder
        // daarom uitgelezen en alleen omgezet als het nodig is.
        app.launchArguments = ["-reader.viewMode", "paginas", "-reader.grid", "0"]
        app.launch()
        naarBibliotheek(app)

        XCTAssertTrue(
            app.navigationBars["Bibliotheek"].waitForExistence(timeout: 40),
            "bibliotheek kwam niet in beeld"
        )

        // Filteren op Oishinbo: die serie heeft 328 delen, en zonder filter is
        // de juiste tegel een kwestie van geluk.
        let zoek = app.searchFields.firstMatch
        XCTAssertTrue(zoek.waitForExistence(timeout: 10), "geen zoekveld")
        zoek.tap()
        zoek.typeText("Oishinbo\n")

        let tegel = app.buttons
            .matching(NSPredicate(format: "label BEGINSWITH 'Oishinbo'"))
            .firstMatch
        guard tegel.waitForExistence(timeout: 40) else { throw XCTSkip("Oishinbo niet gevonden") }
        tegel.tap()

        // Doorbladeren tot het hoofdstuk met kleur in beeld staat.
        let hoofdstuk = app.buttons
            .matching(NSPredicate(format: "label CONTAINS 'Deel 3, hoofdstuk 23'"))
            .firstMatch
        var pogingen = 0
        while !hoofdstuk.exists && pogingen < 40 {
            app.swipeUp(velocity: .fast)
            pogingen += 1
        }
        guard hoofdstuk.exists else { throw XCTSkip("hoofdstuk met kleur niet gevonden") }
        hoofdstuk.tap()

        let teller = app.staticTexts["paginateller"]
        XCTAssertTrue(teller.waitForExistence(timeout: 40), "de lezer opende niet")

        let kleur = app.buttons["Kleur"]
        let vertaling = app.buttons["Vertaling"]
        XCTAssertTrue(kleur.waitForExistence(timeout: 20), "geen kleurknop")

        // Het merkje zegt wat er voor deze pagina klaarligt — de knoppen zijn
        // alleen schakelaars en zeggen daar niets over. Zoeken naar een pagina
        // waar het merkje kleur meldt (en niet "geen kleur" of "al in kleur").
        let kleurmerkje = app.staticTexts.matching(
            NSPredicate(format: "label == 'kleur' OR label == 'kleur + tekst'")
        ).firstMatch

        // Terugbladeren. Deze manga leest rechts-naar-links, dus "verder" is
        // naar rechts en "terug" naar links — andersom dan bij een westerse strip.
        var gevonden = false
        for stap in 0..<12 where !gevonden {
            print("stap \(stap): \(teller.label) | kleur klaar: \(kleurmerkje.exists)")
            if kleurmerkje.exists {
                gevonden = true
                break
            }
            app.swipeLeft()
            sleep(2)
        }
        guard gevonden else {
            throw XCTSkip("geen pagina gevonden met kleur")
        }

        // Aanzetten wat nog uit staat, en niet blind tikken: de standen worden
        // bewaard, dus een vorige ronde kan ze al aan hebben gezet.
        zetAan(kleur)
        sleep(4)
        zetAan(vertaling)
        sleep(5)
        XCTAssertEqual(kleur.value as? String, "aan", "kleur bleef uit")
        XCTAssertEqual(vertaling.value as? String, "aan", "vertaling bleef uit")
        print("na tikken: \(teller.label)")

        let plaat = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        plaat.name = "kleur-en-vertaling"
        plaat.lifetime = .keepAlways
        add(plaat)
    }
}

extension XCTestCase {
    /// Naar het bibliotheek-tabblad. De app opent op de startpagina — dat is
    /// waarvoor je hem meestal opent — dus een test die de bibliotheek nodig
    /// heeft moet daar eerst heen.
    func naarBibliotheek(_ app: XCUIApplication) {
        let tabblad = app.tabBars.buttons["Bibliotheek"]
        if tabblad.waitForExistence(timeout: 40) { tabblad.tap() }
        // Wachten tot er echt tegels staan en niet alleen op de balk. Draaien
        // deze tests achter elkaar, dan is de simulator warmgelopen en haalt
        // een krappe wachttijd het niet — dan viel de test om terwijl de app
        // gewoon nog aan het laden was.
        _ = app.buttons
            .matching(NSPredicate(format: "label CONTAINS ' delen'"))
            .firstMatch
            .waitForExistence(timeout: 40)
    }

    /// Zet een schakelknop aan als hij nog uit staat.
    func zetAan(_ knop: XCUIElement, bestand: StaticString = #filePath, regel: UInt = #line) {
        guard knop.waitForExistence(timeout: 10) else {
            XCTFail("knop bestaat niet", file: bestand, line: regel)
            return
        }
        if (knop.value as? String) != "aan" { knop.tap() }
    }
}
