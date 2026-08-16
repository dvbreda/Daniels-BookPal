import XCTest

/// De panelenstand op een echte mangapagina.
///
/// De server kent het panels-endpoint mogelijk nog niet (nog niet uitgerold),
/// dus dit is meteen de proef op de terugval: de app rekent de panelen dan zelf
/// uit met dezelfde XY-cut.
final class PanelenSmokeTest: XCTestCase {

    func test_panel_mode_shows_a_panel_and_taps_move_through_them() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-reader.viewMode", "panelen", "-reader.grid", "0"]
        app.launch()
        naarBibliotheek(app)

        XCTAssertTrue(
            app.navigationBars["Bibliotheek"].waitForExistence(timeout: 40),
            "bibliotheek kwam niet in beeld"
        )

        let tegel = app.buttons
            .matching(NSPredicate(format: "label BEGINSWITH 'Oishinbo'"))
            .firstMatch
        guard tegel.waitForExistence(timeout: 40) else { throw XCTSkip("Oishinbo niet gevonden") }
        tegel.tap()

        let hoofdstuk = app.cells.buttons.firstMatch
        XCTAssertTrue(hoofdstuk.waitForExistence(timeout: 40), "geen hoofdstuk")
        hoofdstuk.tap()

        let teller = app.staticTexts["paginateller"]
        XCTAssertTrue(teller.waitForExistence(timeout: 40), "de lezer opende niet")

        // Even wachten tot de panelen gevonden zijn (server of zelf uitgerekend).
        sleep(6)

        // Door naar een pagina met echte panelen: de eerste is een titelplaat
        // en die is als proef op de zoom waardeloos. Rechts is nu altijd
        // verder, ook bij manga.
        let verderNaarPanelen = app.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5))
        for _ in 0..<3 {
            verderNaarPanelen.tap()
            sleep(3)
        }
        let eerste = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        eerste.name = "panelen"
        eerste.lifetime = .keepAlways
        add(eerste)

        // Verder tikken. Oishinbo leest rechts-naar-links, dus "verder" zit
        // links — rechts is terug, en op het eerste paneel gebeurt daar terecht
        // niets.
        let verder = app.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.5))
        let beginTeller = teller.label
        verder.tap()
        sleep(3)
        let tweede = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        tweede.name = "panelen-volgende"
        tweede.lifetime = .keepAlways
        add(tweede)

        // De lezer staat er nog en is niet omgevallen op een pagina zonder
        // panelen; dat is wat deze stand het snelst zou breken.
        XCTAssertTrue(teller.exists, "de lezer verdween na een paneeltik")
        // De teller noemt in deze stand ook het paneel, dus hij verandert of
        // je nu binnen de pagina opschuift of naar de volgende springt. Blijft
        // hij gelijk, dan deed de tik niets.
        print("panelen: van «\(beginTeller)» naar «\(teller.label)»")
        XCTAssertNotEqual(teller.label, beginTeller, "verder tikken deed niets")
        XCTAssertTrue(
            teller.label.contains("paneel") || teller.label.contains("hele plaat"),
            "de teller zegt niet waar in de pagina je bent"
        )
    }
}
