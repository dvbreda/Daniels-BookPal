import Foundation

/// Een bestandsnaam die dezelfde blijft na het opnieuw opstarten.
///
/// Niet `hashValue`: Swift zaait de string-hash per processtart opnieuw, dus
/// dezelfde sleutel levert bij de volgende start een ander getal op. Wat op
/// schijf stond was daarmee onvindbaar — de caches waren in de praktijk
/// alleen-schrijven, en precies dát maakte de offline-stand waardeloos: er
/// stond van alles klaar, maar niets werd ooit teruggevonden.
///
/// FNV-1a, 64 bits: klein, stabiel en zonder afhankelijkheden. Botsingen zijn
/// hier ongevaarlijk — dan lees je een andere pagina van dezelfde soort terug
/// en haal je hem hooguit opnieuw op.
enum Stabielesleutel {
    static func naam(_ sleutel: String) -> String {
        var hash: UInt64 = 0xcbf2_9ce4_8422_2325
        for byte in sleutel.utf8 {
            hash ^= UInt64(byte)
            hash &*= 0x100_0000_01b3
        }
        return String(hash, radix: 36)
    }
}
