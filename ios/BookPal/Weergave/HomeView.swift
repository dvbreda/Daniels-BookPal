import SwiftUI

/// De startpagina: rails met waar je gebleven bent en wat er nieuw is.
///
/// Dit is wat je op een telefoon als eerste wilt zien. Het bibliotheekraster is
/// om iets te zóeken; de startpagina is om verder te lezen, en dat is negen van
/// de tien keer waarvoor je de app opent. De rails komen kant-en-klaar van de
/// server, inclusief welke er zijn — lege rails stuurt hij niet mee, want een
/// kop zonder inhoud is ruis.
struct HomeView: View {
    @Environment(Instellingen.self) private var instellingen

    @State private var rails: [HomeRail] = []
    @State private var laadt = false
    @State private var fout: String?
    @State private var teOpenen: Book?
    /// Toont dit de laatst bekende stand, en niet een verse? Zie
    /// `Bibliotheekcache` — dat is zo bij geen netwerk of een NAS die niet
    /// reageert.
    @State private var vanCache = false
    @AppStorage("home.soort") private var soortRuw = Soortfilter.alles.rawValue

    private var soort: Soortfilter { Soortfilter(rawValue: soortRuw) ?? .alles }

    /// De rails na filteren. Een rail die daardoor leeg raakt valt weg — een kop
    /// zonder inhoud is ruis, dezelfde regel die de server zelf aanhoudt.
    private var zichtbaar: [HomeRail] {
        rails.compactMap { rail in
            let items = rail.items.filter(soort.past)
            return items.isEmpty ? nil : HomeRail(key: rail.key, title: rail.title, items: items)
        }
    }

    var body: some View {
        Group {
            if let fout {
                ContentUnavailableView {
                    Label("Geen verbinding", systemImage: "wifi.exclamationmark")
                } description: {
                    Text(fout)
                } actions: {
                    Button("Opnieuw proberen") { Task { await haal() } }
                }
            } else if zichtbaar.isEmpty && laadt {
                ProgressView("Ophalen…")
            } else {
                VStack(spacing: 0) {
                    if vanCache { Offlinebanner() }
                    soortbalk
                    if zichtbaar.isEmpty {
                        ContentUnavailableView(
                            soort == .alles ? "Nog niets te lezen" : "Niets in «\(soort.naam)»",
                            systemImage: "book",
                            description: Text(
                                soort == .alles
                                    ? "Zodra je iets opent verschijnt het hier."
                                    : "Kies een andere soort om meer te zien."
                            )
                        )
                        .frame(maxHeight: .infinity)
                    } else {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 24) {
                                ForEach(zichtbaar) { rail in
                                    railView(rail)
                                }
                            }
                            .padding(.vertical)
                        }
                    }
                }
            }
        }
        .navigationTitle("BookPal")
        .task { await haal() }
        .refreshable { await haal() }
        .navigationDestination(item: $teOpenen) { boek in
            if boek.kind == .epub {
                EpubLezerView(boek: boek)
            } else {
                LezerView(boek: boek)
            }
        }
    }

    private var soortbalk: some View {
        HStack(spacing: 8) {
            ForEach(Soortfilter.allCases) { keuze in
                Button {
                    soortRuw = keuze.rawValue
                } label: {
                    Text(keuze.naam)
                        .font(.subheadline)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 6)
                        .background(
                            Capsule().fill(
                                soort == keuze ? Color.accentColor : Color(.secondarySystemBackground)
                            )
                        )
                        .foregroundStyle(soort == keuze ? .white : .primary)
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
        .padding(.horizontal)
        .padding(.bottom, 8)
    }

    private func railView(_ rail: HomeRail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(rail.title)
                .font(.title3.weight(.semibold))
                .padding(.horizontal)
            ScrollView(.horizontal) {
                HStack(alignment: .top, spacing: 12) {
                    ForEach(rail.items) { item in
                        tegel(item)
                    }
                }
                .padding(.horizontal)
            }
            .scrollIndicators(.hidden)
        }
    }

    private func tegel(_ item: HomeItem) -> some View {
        Button {
            Task { await open(item) }
        } label: {
            VStack(alignment: .leading, spacing: 6) {
                ZStack(alignment: .bottom) {
                    if let client = instellingen.client {
                        OmslagView(
                            url: client.boekOmslagURL(boek: item.bookID),
                            titel: item.seriesTitle
                        )
                    }
                    // De balk over de omslag en niet eronder: zo blijft de tegel
                    // even hoog, ook bij een boek waar je nog niet in bent.
                    if item.percent > 0 && !item.finished {
                        ProgressView(value: min(item.percent, 100), total: 100)
                            .tint(.white)
                            .padding(.horizontal, 6)
                            .padding(.bottom, 5)
                    }
                }
                Text(item.seriesTitle)
                    .font(.caption)
                    .lineLimit(1)
                Text(item.ondertitel)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                if !item.hasFile {
                    Label("nog online", systemImage: "cloud")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(width: 110)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func haal() async {
        guard let client = instellingen.client else {
            fout = ClientFout.geenAdres.localizedDescription
            return
        }
        laadt = true
        defer { laadt = false }
        let (resultaat, terugval) = await Bibliotheekcache.metTerugval(sleutel: "home") {
            try await client.home()
        }
        vanCache = terugval
        if let resultaat {
            rails = resultaat.rails
            fout = nil
            // Verse verbinding met de NAS is precies het moment om te kijken
            // of er onderweg iets is gemaakt dat nog niet is aangekomen, en
            // of er iets op de NAS ligt wat de telefoon nog niet heeft.
            Task { await SidecarSync.gedeeld.synchroniseerIndienNodig(client) }
        } else if rails.isEmpty {
            fout = ClientFout.netwerk(URLError(.notConnectedToInternet)).localizedDescription
        }
    }

    /// De tegel geeft alleen een boek-id; de lezer heeft het hele boek nodig
    /// (leesrichting, paginacount, voortgang). Dus eerst ophalen, dan openen —
    /// en zonder NAS valt dat terug op de laatste keer dat dit boek wél
    /// opgehaald is (`Bibliotheekcache`), meestal het moment dat je 'm voor het
    /// laatst las.
    private func open(_ item: HomeItem) async {
        guard let client = instellingen.client, item.hasFile else { return }
        let sleutel = "boek-\(item.bookID)"
        let (boek, _) = await Bibliotheekcache.metTerugval(sleutel: sleutel) {
            try await client.boek(item.bookID)
        }
        teOpenen = boek
    }
}
