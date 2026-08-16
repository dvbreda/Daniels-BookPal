import Foundation
import Observation

/// Welke series voorrang krijgen in de offline opslag, en hoeveel ruimte er
/// in totaal voor staat.
///
/// Twee soorten voorrang, en je hoeft er maar één van zelf te regelen. Een
/// abonnement heb je al bewust ingesteld — "dit wil ik bijhouden" — dus een
/// boek dat daarvandaan komt (`Book.fromSource`) is vanzelf beschermd, zodra
/// je het één keer geopend hebt. Alles daarnaast zet je zelf aan met het
/// vinkje bij een serie: voor wat je herleest, of waarvan je zeker wilt weten
/// dat het er staat zonder NAS.
@MainActor
@Observable
final class Prioriteiten {
    static let gedeeld = Prioriteiten()

    private static let seriesSleutel = "offline.prioriteitSeries"
    private static let boekenSleutel = "offline.beschermdeBoeken"
    private static let limietSleutel = "offline.limietMB"

    /// 2 GB. Ruim genoeg voor een paar hoofdstukken vooruit, klein genoeg om
    /// niet stilletjes de hele telefoon te vullen.
    static let standaardLimietMB = 2000

    private(set) var eigenGekozen: Set<Int>
    private(set) var beschermdeBoeken: Set<Int>

    var limietMB: Int {
        didSet { UserDefaults.standard.set(limietMB, forKey: Self.limietSleutel) }
    }

    var limietBytes: Int64 { Int64(limietMB) * 1_000_000 }

    private init() {
        eigenGekozen = Set(UserDefaults.standard.array(forKey: Self.seriesSleutel) as? [Int] ?? [])
        beschermdeBoeken = Set(UserDefaults.standard.array(forKey: Self.boekenSleutel) as? [Int] ?? [])
        let limiet = UserDefaults.standard.integer(forKey: Self.limietSleutel)
        limietMB = limiet > 0 ? limiet : Self.standaardLimietMB
    }

    func isPrioriteit(serieID: Int) -> Bool { eigenGekozen.contains(serieID) }

    func zet(serieID: Int, prioriteit: Bool) {
        if prioriteit { eigenGekozen.insert(serieID) } else { eigenGekozen.remove(serieID) }
        UserDefaults.standard.set(Array(eigenGekozen), forKey: Self.seriesSleutel)
    }

    /// Dit boek nooit opruimen — voor een boek dat van een abonnement komt.
    /// Geen `didSet`-omweg: dit gebeurt bij elke pagina die je leest, en dan
    /// mag het niet elke keer de hele verzameling terugschrijven als er niets
    /// veranderd is.
    func markeerAltijdBewaren(boek: Int) {
        guard !beschermdeBoeken.contains(boek) else { return }
        beschermdeBoeken.insert(boek)
        UserDefaults.standard.set(Array(beschermdeBoeken), forKey: Self.boekenSleutel)
    }
}
