import XCTest

/// Een epub openen en er tekst uit zien komen, tegen de echte NAS.
///
/// Juist hier is een nagebootste server waardeloos: wat stuk kan is het echte
/// bestand — een spine die anders in elkaar zit, een plaatje met een pad dat
/// omhoog wijst, tekst in een codering die niet UTF-8 is.
final class EpubSmokeTest: XCTestCase {

    func test_an_epub_opens_and_shows_its_text() throws {
        let app = XCUIApplication()
        app.launch()
        naarBibliotheek(app)

        XCTAssertTrue(
            app.navigationBars["Bibliotheek"].waitForExistence(timeout: 40),
            "bibliotheek kwam niet in beeld"
        )

        // "Down to Earth" is de epub-serie in de bibliotheek.
        let tegel = app.buttons
            .matching(NSPredicate(format: "label BEGINSWITH 'Down to Earth'"))
            .firstMatch
        guard tegel.waitForExistence(timeout: 40) else {
            throw XCTSkip("geen epub-serie in de bibliotheek gevonden")
        }
        tegel.tap()

        // Het eerste boek openen; daarna moet het epub-bestand opgehaald en
        // uitgepakt worden, en dat mag even duren.
        let boek = app.cells.buttons.firstMatch
        XCTAssertTrue(boek.waitForExistence(timeout: 20), "serie leverde geen boeken op")
        boek.tap()

        // De hoofdstukkenlijst noemt hoeveel het er zijn.
        let kop = app.staticTexts
            .matching(NSPredicate(format: "label CONTAINS 'hoofdstukken'"))
            .firstMatch
        XCTAssertTrue(kop.waitForExistence(timeout: 120), "epub gaf geen hoofdstukken")

        // Een hoofdstuk openen en er tekst uit zien komen.
        let hoofdstuk = app.cells.buttons.firstMatch
        XCTAssertTrue(hoofdstuk.waitForExistence(timeout: 40), "geen hoofdstuk om te openen")
        hoofdstuk.tap()

        sleep(4)
        let plaat = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        plaat.name = "epub"
        plaat.lifetime = .keepAlways
        add(plaat)

        // Er moet echte boektekst staan, niet alleen navigatie-chroom.
        let tekstblokken = app.textViews
        XCTAssertTrue(
            tekstblokken.firstMatch.waitForExistence(timeout: 30),
            "het hoofdstuk toonde geen tekst"
        )
    }
}
