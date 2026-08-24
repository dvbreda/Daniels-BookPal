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
    private static let elders = "serveradres.elders"
    private static let eldersAan = "serveradres.eldersAan"
    private static let offlineSleutel = "alleenOffline"
    private static let profielSleutel = "beeldprofiel"
    static let standaardAdres = "http://192.168.68.98:1997"

    var adres: String {
        didSet { UserDefaults.standard.set(adres, forKey: Self.adresSleutel) }
    }

    /// Een tweede adres voor buiten je netwerk, bijvoorbeeld via ZeroTier.
    ///
    /// Apart van het gewone adres en niet in plaats daarvan: thuis is het
    /// directe adres sneller, en een tunnel die er even uit ligt hoort je
    /// bibliotheek niet onbereikbaar te maken. Vandaar de schakelaar — jij
    /// bepaalt welke gebruikt wordt.
    var adresElders: String {
        didSet { UserDefaults.standard.set(adresElders, forKey: Self.elders) }
    }

    var gebruikElders: Bool {
        didSet { UserDefaults.standard.set(gebruikElders, forKey: Self.eldersAan) }
    }

    /// Doen alsof er geen NAS is. Bedoeld om te kunnen zien wat er offline
    /// werkelijk klaarstaat — anders merk je pas in de trein dat de helft
    /// ontbreekt.
    var alleenOffline: Bool {
        didSet { UserDefaults.standard.set(alleenOffline, forKey: Self.offlineSleutel) }
    }

    init() {
        adresElders = UserDefaults.standard.string(forKey: Self.elders) ?? ""
        gebruikElders = UserDefaults.standard.bool(forKey: Self.eldersAan)
        alleenOffline = UserDefaults.standard.bool(forKey: Self.offlineSleutel)
        adres = UserDefaults.standard.string(forKey: Self.adresSleutel) ?? Self.standaardAdres
        profiel = UserDefaults.standard.string(forKey: Self.profielSleutel)
            ?? Client.standaardProfiel
    }

    /// De client voor het huidige adres, of `nil` als er onzin staat.
    ///
    /// Geeft `nil` terug in offlinestand. Dat is geen omweg maar precies de
    /// bedoeling: elk scherm valt dan terug op wat er op dit toestel staat, en
    /// zo zie je thuis al wat je onderweg zou zien.
    var client: Client? {
        guard !alleenOffline else { return nil }
        let gekozen = gebruikElders && !adresElders.isEmpty ? adresElders : adres
        guard let url = URL(string: gekozen.trimmingCharacters(in: .whitespaces)),
              url.scheme != nil, url.host() != nil
        else { return nil }
        return Client(basis: url)
    }
}
