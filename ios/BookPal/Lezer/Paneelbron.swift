import Foundation
import UIKit

/// Waar de panelen van een pagina vandaan komen.
///
/// **De server eerst.** Die rekent één keer, cachet het, en web en Kobo krijgen
/// hetzelfde antwoord — dezelfde reden als bij de beeldprofielen. Levert hij
/// niets (offline, of een server die het endpoint nog niet kent), dan rekent de
/// app het zelf uit met dezelfde XY-cut. Zo werkt de panelenstand altijd, en
/// blijft de server toch de bron.
@MainActor
@Observable
final class Paneelbron {
    private let client: Client
    private let boek: Int
    private let rechtsNaarLinks: Bool
    private var gevonden: [Int: [Paneel]] = [:]
    private var lopend: Set<Int> = []

    init(client: Client, boek: Int, rechtsNaarLinks: Bool) {
        self.client = client
        self.boek = boek
        self.rechtsNaarLinks = rechtsNaarLinks
    }

    /// Wat we van deze pagina weten. Nog niets betekent: de hele pagina, zodat
    /// de lezer nooit vastloopt op iets dat nog moet komen.
    func panelen(_ index: Int) -> [Paneel] {
        gevonden[index] ?? [Paneel.helePagina]
    }

    func kent(_ index: Int) -> Bool { gevonden[index] != nil }

    /// - Parameter beeld: de al geladen pagina, voor de terugval. Zonder beeld
    ///   wordt er alleen aan de server gevraagd.
    func onderzoek(_ index: Int, beeld: UIImage?) async {
        guard gevonden[index] == nil, !lopend.contains(index) else { return }
        lopend.insert(index)
        defer { lopend.remove(index) }

        if let vanServer = try? await client.panelen(boek: boek, index: index),
           !vanServer.isEmpty {
            gevonden[index] = vanServer
            return
        }
        guard let beeld else { return }
        // Zelf uitrekenen kost tientallen milliseconden op een pagina; buiten de
        // hoofdthread, want de lezer moet blijven reageren.
        let rtl = rechtsNaarLinks
        gevonden[index] = await Task.detached(priority: .userInitiated) {
            Panelen.vind(in: beeld, rechtsNaarLinks: rtl)
        }.value
    }
}
