import XCTest

/// Eén doorloop van bibliotheek naar lezer, tegen de echte NAS.
///
/// Bewust geen nagebootste server: wat hier stuk kan gaan is juist de aansluiting
/// op de echte API — een veld dat anders heet, een datum die niet te lezen is,
/// een pagina die als 409 terugkomt. Een test met verzonnen JSON zou dat alles
/// vrolijk doorstaan.
///
/// Heeft een bereikbare NAS nodig, dus draai hem apart:
///
///     xcodebuild test -only-testing:BookPalUITests ...
final class LezenSmokeTest: XCTestCase {

    func test_the_library_leads_to_a_readable_page() throws {
        let app = XCUIApplication()
        // Bekende beginstand, zodat een vorige test met doorlopend of raster aan
        // deze niet laat struikelen.
        app.launchArguments = ["-reader.viewMode", "paginas", "-reader.grid", "0"]
        app.launch()
        naarBibliotheek(app)

        // 1. De bibliotheek komt binnen van de NAS.
        XCTAssertTrue(
            app.navigationBars["Bibliotheek"].waitForExistence(timeout: 40),
            "bibliotheek kwam niet in beeld"
        )

        // Een serietegel en niet `buttons.firstMatch`: die eerste is het tandwiel
        // in de navigatiebalk, want dat staat vóór het raster in de boom. Elke
        // tegel noemt zijn aantal delen, dus daar is hij aan te herkennen.
        let tegel = app.buttons
            .matching(NSPredicate(format: "label CONTAINS ' delen'"))
            .firstMatch
        XCTAssertTrue(tegel.waitForExistence(timeout: 40), "geen enkele serietegel getoond")
        tegel.tap()

        // 2. De serie toont zijn hoofdstukken.
        XCTAssertTrue(
            app.cells.firstMatch.waitForExistence(timeout: 40),
            "serie leverde geen hoofdstukken op"
        )
        // 3. Een hoofdstuk openen. `cells.buttons` en niet `cells`: de eerste cel
        //    is de sectiekop ("5 delen") en een rij zonder bestand is geen
        //    navigatielink — alleen wat je echt kunt openen is een knop.
        let teller = app.staticTexts["paginateller"]
        let hoofdstukken = app.cells.buttons

        for poging in 0..<3 {
            let rij = hoofdstukken.element(boundBy: poging)
            guard rij.exists, rij.isHittable else { continue }
            rij.tap()

            if teller.waitForExistence(timeout: 30) {
                // 4. Er staat een pagina in beeld: de spread-indeling heeft
                //    gewerkt en er is beeld uit `/pages/{n}` gekomen.
                XCTAssertTrue(teller.label.contains(" van "), "de teller staat er raar bij")

                // Even wachten op het beeld en er een plaat van bewaren. Dat de
                // teller er staat bewijst nog niet dát de pagina zichtbaar is —
                // een zwarte pagina onder een correcte teller is precies de fout
                // die dit anders zou missen.
                sleep(3)
                let plaat = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                plaat.name = "lezer"
                plaat.lifetime = .keepAlways
                add(plaat)
                return
            }
            if app.navigationBars.buttons.firstMatch.exists {
                app.navigationBars.buttons.firstMatch.tap()
            }
        }

        print("=== schermboom op het moment van falen ===")
        print(app.debugDescription)
        XCTFail("geen enkel hoofdstuk opende een leesbare pagina")
    }
}
