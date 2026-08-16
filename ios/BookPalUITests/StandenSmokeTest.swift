import XCTest

/// De leesstanden: bladeren, het weergavepaneel en de doorlopende weergave.
///
/// De pager is van `TabView` naar een `ScrollView` gegaan om `scrollDisabled`
/// te kunnen gebruiken (ingezoomd hoort bladeren uit te staan). Dat is een
/// herschrijving van het bladeren zelf, dus die moet aantoonbaar nog werken.
final class StandenSmokeTest: XCTestCase {

    func test_paging_and_the_display_panel_work() throws {
        let app = XCUIApplication()
        // Met een bekende beginstand starten. De lezer bewaart zijn standen in
        // UserDefaults, dus een vorige testronde die doorlopend aanzette liet de
        // volgende in die stand beginnen — en dan veeg je horizontaal in een
        // verticale scroller en lijkt bladeren stuk. Argumenten met een streepje
        // ervoor komen in het argumentendomein en overrulen wat er bewaard is,
        // zonder dat de app er iets voor hoeft te weten.
        app.launchArguments = [
            "-reader.viewMode", "paginas",
            "-reader.grid", "0",
            "-reader.doublePage", "NO",
        ]
        app.launch()
        naarBibliotheek(app)

        XCTAssertTrue(
            app.navigationBars["Bibliotheek"].waitForExistence(timeout: 40),
            "bibliotheek kwam niet in beeld"
        )

        // Claire: westers, dus links-naar-rechts — vegen naar links bladert door.
        let tegel = app.buttons
            .matching(NSPredicate(format: "label BEGINSWITH 'Claire'"))
            .firstMatch
        guard tegel.waitForExistence(timeout: 40) else { throw XCTSkip("Claire niet gevonden") }
        tegel.tap()

        let hoofdstuk = app.cells.buttons.firstMatch
        XCTAssertTrue(hoofdstuk.waitForExistence(timeout: 40), "geen hoofdstuk")
        hoofdstuk.tap()

        let teller = app.staticTexts["paginateller"]
        XCTAssertTrue(teller.waitForExistence(timeout: 30), "de lezer opende niet")
        let begin = teller.label

        // 1. Bladeren doet echt iets. Met een sleep over coördinaten en niet met
        //    `swipeLeft()`: die laatste mikt op het midden van de app en landt
        //    soms op de balk in plaats van op de pagina.
        let rechts = app.coordinate(withNormalizedOffset: CGVector(dx: 0.85, dy: 0.5))
        let links = app.coordinate(withNormalizedOffset: CGVector(dx: 0.15, dy: 0.5))
        rechts.press(forDuration: 0.05, thenDragTo: links)
        sleep(3)

        let na = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        na.name = "bladeren"
        na.lifetime = .keepAlways
        add(na)
        print("bladeren: van «\(begin)» naar «\(teller.label)»")
        XCTAssertNotEqual(teller.label, begin, "vegen bladerde niet")

        // 2. Het weergavepaneel gaat open en kent de standen.
        app.buttons["Weergave"].tap()
        let paneel = app.navigationBars["Weergave"]
        XCTAssertTrue(paneel.waitForExistence(timeout: 10), "weergavepaneel ging niet open")
        for knop in ["Doorlopend", "Breedte", "Hoogte", "Passend"] {
            XCTAssertTrue(app.buttons[knop].exists, "«\(knop)» ontbreekt in het paneel")
        }
        XCTAssertTrue(app.switches["Bijsnijden"].exists, "bijsnijden ontbreekt")

        // 3. Doorlopende weergave aanzetten en sluiten.
        app.buttons["Doorlopend"].tap()
        app.buttons["Klaar"].tap()
        sleep(4)

        let plaat = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        plaat.name = "doorlopend"
        plaat.lifetime = .keepAlways
        add(plaat)

        // In doorlopende weergave is er beeld en werkt scrollen.
        app.swipeUp()
        sleep(2)
        XCTAssertTrue(app.images.firstMatch.exists, "doorlopende weergave toonde geen beeld")
    }
}
