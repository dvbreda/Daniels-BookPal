import SwiftUI

/// De losse filters: soort, herkomst en map.
///
/// Bewust geen regelbouwer zoals de web-app die heeft. Die hoort daar thuis —
/// een geneste `and`/`or`/`not`-boom maak je op een groot scherm, niet met je
/// duim. Wat je hier wél wilt is snel filteren en het daarna weer weghalen; wat
/// je vaker nodig hebt maak je in de web-app een keer als tab, en die staan
/// hierboven in de balk.
struct FilterSheet: View {
    @Binding var filter: Bibliotheekfilter
    let roots: [LibraryRoot]

    @Environment(\.dismiss) private var sluit

    var body: some View {
        NavigationStack {
            Form {
                Section("Soort") {
                    Picker("Soort", selection: $filter.soort) {
                        Text("Alles").tag(BookKind?.none)
                        Text("Strips").tag(BookKind?.some(.comic))
                        Text("Epub").tag(BookKind?.some(.epub))
                        Text("Pdf").tag(BookKind?.some(.pdf))
                    }
                    .pickerStyle(.segmented)
                }

                Section {
                    Picker("Herkomst", selection: $filter.herkomst) {
                        Text("Alles").tag(Herkomst?.none)
                        ForEach(Herkomst.allCases) { herkomst in
                            Text(herkomst.naam).tag(Herkomst?.some(herkomst))
                        }
                    }
                } header: {
                    Text("Herkomst")
                } footer: {
                    Text(
                        "Afgeleid uit ComicInfo, de bron en de standaard van de map. "
                            + "Zo blijven strips uit Europa en manga uit Japan uit elkaar."
                    )
                }

                Section("Map") {
                    Picker("Map", selection: $filter.rootID) {
                        Text("Alle mappen").tag(Int?.none)
                        ForEach(roots.filter(\.enabled)) { root in
                            Text(root.naam).tag(Int?.some(root.id))
                        }
                    }
                }

                if filter.aantalLos > 0 {
                    Section {
                        Button("Filters wissen", role: .destructive) {
                            filter.wisLos()
                        }
                    }
                }
            }
            .navigationTitle("Filteren")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Klaar") { sluit() }
                }
            }
        }
    }
}
