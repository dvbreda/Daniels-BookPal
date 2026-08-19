import Foundation
import Observation

/// Welke series voorrang krijgen in de offline opslag, en hoeveel ruimte er
/// in totaal voor staat.
///
/// Eén soort voorrang, en die zet je zelf: het vinkje bij een serie in
/// Instellingen -> Offline. Dat is geen "download deze serie" maar "ruim deze
/// als laatste op".
///
/// Een abonnement krijgt bewust géén voorrang. Wat daarvandaan komt is altijd
/// opnieuw op te halen zolang je verbinding hebt, dus het zou zonde zijn om er
/// schaarse offline-ruimte aan te geven die je liever aan je eigen bestanden
/// besteedt. De sidecars ervan komen wél altijd mee — die zijn duur betaald en
/// klein.
@MainActor
@Observable
final class Prioriteiten {
    static let gedeeld = Prioriteiten()

    private static let seriesSleutel = "offline.prioriteitSeries"
    private static let limietSleutel = "offline.limietMB"

    /// 2 GB. Ruim genoeg voor een paar hoofdstukken vooruit, klein genoeg om
    /// niet stilletjes de hele telefoon te vullen.
    static let standaardLimietMB = 2000

    private(set) var eigenGekozen: Set<Int>

    var limietMB: Int {
        didSet { UserDefaults.standard.set(limietMB, forKey: Self.limietSleutel) }
    }

    var limietBytes: Int64 { Int64(limietMB) * 1_000_000 }

    private init() {
        eigenGekozen = Set(UserDefaults.standard.array(forKey: Self.seriesSleutel) as? [Int] ?? [])
        let limiet = UserDefaults.standard.integer(forKey: Self.limietSleutel)
        limietMB = limiet > 0 ? limiet : Self.standaardLimietMB
    }

    func isPrioriteit(serieID: Int) -> Bool { eigenGekozen.contains(serieID) }

    func zet(serieID: Int, prioriteit: Bool) {
        if prioriteit { eigenGekozen.insert(serieID) } else { eigenGekozen.remove(serieID) }
        UserDefaults.standard.set(Array(eigenGekozen), forKey: Self.seriesSleutel)
    }

}
