import SwiftUI

@main
struct BookPalApp: App {
    @State private var instellingen = Instellingen()

    var body: some Scene {
        WindowGroup {
            Hoofdscherm()
                .environment(instellingen)
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
