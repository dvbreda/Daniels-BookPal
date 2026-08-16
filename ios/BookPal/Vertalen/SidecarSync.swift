import Foundation
import Observation

/// Sidecars die de telefoon zelf maakte naar de NAS duwen, en alles wat er op
/// de NAS al ligt naar de telefoon halen.
///
/// Twee kanten, en geen van beide hoeft een beslissing te nemen over wie er
/// wint bij een botsing: de server laat vanzelf staan wat er al ligt (zie
/// `bookpal.api.sidecars`), dus dit hoeft alleen te weten wat er aan élke
/// kant nog ontbreekt. Na een geslaagde upload verdwijnt het lokale bestand:
/// het staat dan op de NAS, en de NAS is de opslag — de telefoon is alleen de
/// tussenstop voor onderweg.
///
/// **Meer dan twee apparaten.** Er kan straks ook een iPad meedoen, en een
/// Kobo. Dat werkt zonder dat hier iets over "de andere kant" bekend hoeft te
/// zijn, omdat er geen enkele beslissing op twee-kanten-tegelijk berust: elk
/// apparaat vergelijkt alleen zichzelf met de NAS, en de NAS neemt nooit iets
/// aan bovenop wat er al ligt. Wie het als eerste aflevert wint, en de rest
/// krijgt `stored: false` terug — geen verlies, want het werk is identiek.
/// Verwijderen na een upload mag daarom ook als een ander apparaat je net
/// voor was: wat je had staat er dan nog steeds, alleen niet meer van jou.
@MainActor
@Observable
final class SidecarSync {
    static let gedeeld = SidecarSync()

    private(set) var bezig = false
    private(set) var laatsteVerslag: String?
    private var laatsteAutomatischeRun: Date?

    private init() {}

    /// Voor de knop "nu synchroniseren" in Instellingen: altijd doen, ook als
    /// er net nog een automatische ronde is geweest.
    func synchroniseer(_ client: Client) async {
        guard !bezig else { return }
        bezig = true
        defer { bezig = false }
        laatsteAutomatischeRun = Date()

        guard let server = try? await client.sidecarManifest() else {
            laatsteVerslag = "Geen verbinding met de NAS."
            return
        }

        let lokaal = Lokaalsidecar.alles()
        let serverSleutels = Set(server.items.map { "\($0.bookID)/\($0.name)" })
        let lokaleSleutels = Set(lokaal.map { "\($0.boek)/\($0.naam)" })

        var geupload = 0
        var voorgeweest = 0
        for regel in lokaal where !serverSleutels.contains("\(regel.boek)/\(regel.naam)") {
            guard let data = Lokaalsidecar.lees(naam: regel.naam, boek: regel.boek) else { continue }
            guard let antwoord = try? await client.sidecarPlaatsen(
                boek: regel.boek, naam: regel.naam, data: data
            ) else { continue }
            Lokaalsidecar.verwijder(naam: regel.naam, boek: regel.boek)
            if antwoord.stored { geupload += 1 } else { voorgeweest += 1 }
        }

        var opgehaald = 0
        for item in server.items where !lokaleSleutels.contains("\(item.bookID)/\(item.name)") {
            guard let data = try? await client.sidecarOphalen(boek: item.bookID, naam: item.name)
            else { continue }
            Lokaalsidecar.bewaar(data, naam: item.name, boek: item.bookID)
            opgehaald += 1
        }

        var delen: [String] = []
        if geupload > 0 { delen.append("\(geupload) naar de NAS gestuurd") }
        if opgehaald > 0 { delen.append("\(opgehaald) opgehaald") }
        // Apart benoemen: dit is geen mislukking maar een ander apparaat dat
        // dezelfde pagina al had afgeleverd.
        if voorgeweest > 0 { delen.append("\(voorgeweest) stond er al van elders") }
        laatsteVerslag = delen.isEmpty ? "Alles was al gelijk." : delen.joined(separator: ", ") + "."
    }

    /// Voor op de achtergrond, bij elke geslaagde verse aanroep: niet vaker
    /// dan eens per vijf minuten, anders doet elke pull-to-refresh een volle
    /// inventarisatie van alles wat er op de NAS staat.
    func synchroniseerIndienNodig(_ client: Client) async {
        if let laatste = laatsteAutomatischeRun, Date().timeIntervalSince(laatste) < 300 { return }
        await synchroniseer(client)
    }
}
