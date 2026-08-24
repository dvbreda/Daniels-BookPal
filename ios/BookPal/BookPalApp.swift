import SwiftUI

@main
struct BookPalApp: App {
    @State private var instellingen = Instellingen()

    init() {
        // Ruimer dan de standaard van iOS, en op schijf. `AsyncImage` leest
        // hieruit, dus dit is wat een omslag zonder NAS alsnog laat zien —
        // zonder dit is de hele bibliotheek offline een raster grijze vakjes.
        // Omslagen zijn klein (320px), dus 300 MB is er ruim genoeg voor.
        URLCache.shared = URLCache(
            memoryCapacity: 32 * 1024 * 1024,
            diskCapacity: 300 * 1024 * 1024
        )
    }
    @Environment(\.scenePhase) private var fase

    var body: some Scene {
        WindowGroup {
            Hoofdscherm()
                .environment(instellingen)
                // Zodra de app in beeld is en de NAS bereikbaar: bijwerken.
                // Eerst wat jij onderweg gemaakt hebt naar de NAS, dan alle
                // sidecars terug, dan pagina's tot de limiet. `Voorraad` slaat
                // over wat er al ligt en houdt zelf een interval aan, dus het
                // schakelen tussen apps kost niets.
                .onChange(of: fase) { _, nieuw in
                    guard nieuw == .active, let client = instellingen.client else { return }
                    Voorraad.gedeeld.startIndienNodig(client)
                }
                // Naar de achtergrond: netjes stoppen. Doorgaan zou iOS toch
                // afkappen, en een halve ronde is geen probleem — de volgende
                // keer gaat hij verder waar hij was.
                .onChange(of: fase) { _, nieuw in
                    if nieuw == .background { Voorraad.gedeeld.stop() }
                }
        }
    }
}

/// Start op de startpagina en niet op het bibliotheekraster.
///
/// Het raster is om iets te zóeken; de startpagina is om verder te lezen, en dat
/// is negen van de tien keer waarvoor je de app opent. Hetzelfde onderscheid dat
/// de web-app maakt sinds de rails er zijn.
struct Hoofdscherm: View {
    @Environment(Instellingen.self) private var instellingen
    private var bieb: Bieb { Bieb.gedeeld }

    var body: some View {
        TabView {
            Tab("Verder", systemImage: "book") {
                NavigationStack { HomeView() }
            }
            Tab("Bibliotheek", systemImage: "books.vertical") {
                BibliotheekView()
            }
            // Alleen als de bieb antwoordt: een tab naar een dode poort is
            // erger dan geen tab.
            if let adres = bieb.adres {
                Tab("Bieb", systemImage: "sparkles") {
                    NavigationStack { BiebView(adres: adres) }
                }
            }
        }
        .task { await bieb.zoek(bij: instellingen.client?.basis) }
    }
}
