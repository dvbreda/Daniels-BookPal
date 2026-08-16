import Foundation
import Observation

/// Wat de app onthoudt tussen sessies. Voorlopig alleen het serveradres — de
/// rest van de voorkeuren woont op de server, zodat elk apparaat dezelfde
/// instellingen ziet.
@MainActor
@Observable
final class Instellingen {
    /// De taal waarin de server vertaalt. Staat daar in `BOOKPAL_TRANSLATE_LANG`
    /// en is per omgeving vast, dus hier een constante in plaats van een
    /// instelling die met de server uit de pas kan lopen.
    var taal: String { "nl" }

    /// Het gekozen beeldprofiel. Standaard `web`; zie `Client.standaardProfiel`
    /// voor waarom dat de goede keuze is voor deze bibliotheek.
    var profiel: String {
        didSet { UserDefaults.standard.set(profiel, forKey: Self.profielSleutel) }
    }

    private static let adresSleutel = "serveradres"
    private static let profielSleutel = "beeldprofiel"
    static let standaardAdres = "http://192.168.68.98:1997"

    var adres: String {
        didSet { UserDefaults.standard.set(adres, forKey: Self.adresSleutel) }
    }

    init() {
        adres = UserDefaults.standard.string(forKey: Self.adresSleutel) ?? Self.standaardAdres
        profiel = UserDefaults.standard.string(forKey: Self.profielSleutel)
            ?? Client.standaardProfiel
    }

    /// De client voor het huidige adres, of `nil` als er onzin staat.
    var client: Client? {
        guard let url = URL(string: adres.trimmingCharacters(in: .whitespaces)),
              url.scheme != nil, url.host() != nil
        else { return nil }
        return Client(basis: url)
    }
}
