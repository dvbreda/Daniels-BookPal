import SwiftUI

@main
struct BookPalApp: App {
    @State private var instellingen = Instellingen()
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
    var body: some View {
        TabView {
            Tab("Verder", systemImage: "book") {
                NavigationStack { HomeView() }
            }
            Tab("Bibliotheek", systemImage: "books.vertical") {
                BibliotheekView()
            }
        }
    }
}
