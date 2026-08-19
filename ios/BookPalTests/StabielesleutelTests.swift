import Testing

@testable import BookPal

/// De offline-stand valt of staat hiermee.
///
/// Eerst gebruikten beide caches `hashValue` in de bestandsnaam. Swift zaait de
/// string-hash per processtart opnieuw, dus na het herstarten van de app was
/// alles wat er stond onvindbaar: er werd van alles bewaard en nooit iets
/// teruggevonden. Op het toestel zag je dan een netwerkfout in plaats van je
/// gecachte bibliotheek.
struct StabielesleutelTests {
    /// Vastgepind op een letterlijke waarde. Een test die alleen zichzelf
    /// vergelijkt zou ook slagen met `hashValue`, want binnen één proces is
    /// die óók stabiel — juist dát maakte de fout zo onzichtbaar.
    @Test func the_key_is_pinned_to_a_literal_value() {
        #expect(Stabielesleutel.naam("home") == "z4tiy2tmkh2m")
        #expect(Stabielesleutel.naam("7-h2") == "2n3qdue1ktbwb")
    }

    @Test func different_keys_give_different_names() {
        #expect(Stabielesleutel.naam("boek-1") != Stabielesleutel.naam("boek-2"))
    }

    @Test func the_same_key_always_gives_the_same_name() {
        #expect(Stabielesleutel.naam("series-alles-") == Stabielesleutel.naam("series-alles-"))
    }

    /// De sleutel bevat leestekens (een dubbele punt achter een taalcode) en
    /// wordt een bestandsnaam; die mag geen schuine streep opleveren.
    @Test func the_name_is_safe_as_a_filename() {
        for sleutel in ["12-k-nl", "3-o-web-crop:1", "boek/met/streep"] {
            let naam = Stabielesleutel.naam(sleutel)
            #expect(!naam.contains("/"))
            #expect(!naam.isEmpty)
        }
    }
}
