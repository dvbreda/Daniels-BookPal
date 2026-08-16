import Testing

@testable import BookPal

/// Het origineel leesbaar maken in het paneeltje, zonder informatie weg te
/// gooien.
struct KapitalenTests {
    @Test func test_shouting_lettering_becomes_a_normal_sentence() {
        #expect(
            Kapitalen.normaliseer("WAIT, YOU'RE PRESIDENT NARISAWA!")
                == "Wait, you're president narisawa!"
        )
    }

    @Test func test_a_sentence_that_is_already_normal_is_left_alone() {
        // Omzetten zou hier juist informatie weggooien: die hoofdletters staan
        // er met een reden.
        let zin = "Wait, You're President Narisawa!"
        #expect(Kapitalen.normaliseer(zin) == zin)
    }

    @Test func test_every_sentence_gets_its_own_capital() {
        #expect(
            Kapitalen.normaliseer("OH DEAR. TENPACHI'S FULL TODAY TOO. AGAIN!")
                == "Oh dear. Tenpachi's full today too. Again!"
        )
    }

    @Test func test_the_english_i_stays_a_capital() {
        // "i know" leest verkeerder dan het probleem dat we oplosten.
        #expect(Kapitalen.normaliseer("HAAH, I KNOW.") == "Haah, I know.")
    }

    @Test func test_a_short_shout_is_not_touched() {
        // "EH?" is een kreet, geen schreeuw; daar valt niets te normaliseren.
        #expect(Kapitalen.normaliseer("EH?") == "EH?")
    }

    @Test func test_text_without_letters_survives() {
        #expect(Kapitalen.normaliseer("...!?") == "...!?")
    }

    @Test func test_empty_text_survives() {
        #expect(Kapitalen.normaliseer("") == "")
    }
}
