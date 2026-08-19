import SwiftUI

/// Wat er op je toestel komt te staan, en welke series voorgaan.
///
/// Het budget is één pot voor de hele bibliotheek. Raakt die vol, dan gaat de
/// langst niet bekeken pagina het eerst — behálve van series die je hier
/// aanvinkt. Dat vinkje is dus geen "download deze serie", het is "ruim deze
/// als laatste op".
///
/// De sidecars staan hier bewust niet bij als keuze: die zijn klein (tekstvlakken
/// zijn JSON, een hertekende plaat een paar honderd kilobyte) en ze zijn duur
/// betaald. Die komen altijd mee, ongeacht wat je aanvinkt.
struct OfflineView: View {
    @Environment(Instellingen.self) private var instellingen

    @State private var series: [Series] = []
    @State private var fout: String?
    @State private var gebruikt: Int64 = 0
    @State private var zoek = ""

    private var prioriteiten: Prioriteiten { Prioriteiten.gedeeld }

    private var zichtbaar: [Series] {
        guard !zoek.isEmpty else { return series }
        return series.filter { $0.title.localizedCaseInsensitiveContains(zoek) }
    }

    var body: some View {
        List {
            ruimteSectie
            if let fout {
                Section { Text(fout).font(.callout).foregroundStyle(.red) }
            }
            serieSectie
        }
        .navigationTitle("Offline")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $zoek, prompt: "Zoek een serie")
        .task { await haal() }
    }

    private var ruimteSectie: some View {
        Section {
            LabeledContent(
                "In gebruik",
                value: ByteCountFormatter.string(fromByteCount: gebruikt, countStyle: .file)
            )
            VStack(alignment: .leading, spacing: 6) {
                Text("Limiet: \(prioriteiten.limietMB) MB")
                Slider(
                    value: Binding(
                        get: { Double(prioriteiten.limietMB) },
                        set: { prioriteiten.limietMB = Int($0) }
                    ),
                    in: 500...20000,
                    step: 500
                )
            }
            if prioriteiten.limietBytes > 0 {
                ProgressView(
                    value: min(Double(gebruikt), Double(prioriteiten.limietBytes)),
                    total: Double(prioriteiten.limietBytes)
                )
            }
        } header: {
            Text("Ruimte op dit toestel")
        } footer: {
            Text(
                "Eén pot voor je hele bibliotheek. Raakt hij vol, dan gaat de langst niet "
                    + "bekeken pagina het eerst — behalve van de series die je hieronder aanvinkt."
            )
        }
    }

    private var serieSectie: some View {
        Section {
            if series.isEmpty {
                Text("Nog geen series opgehaald.").foregroundStyle(.secondary)
            }
            ForEach(zichtbaar) { serie in
                Button {
                    prioriteiten.zet(
                        serieID: serie.id, prioriteit: !prioriteiten.isPrioriteit(serieID: serie.id)
                    )
                } label: {
                    HStack {
                        Image(
                            systemName: prioriteiten.isPrioriteit(serieID: serie.id)
                                ? "checkmark.square.fill" : "square"
                        )
                        .foregroundStyle(
                            prioriteiten.isPrioriteit(serieID: serie.id)
                                ? AnyShapeStyle(.tint) : AnyShapeStyle(.secondary)
                        )
                        VStack(alignment: .leading, spacing: 2) {
                            Text(serie.title).foregroundStyle(.primary)
                            Text("\(serie.bookCount) delen")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        } header: {
            Text("Voorrang bij het opruimen")
        } footer: {
            Text(
                "Vertalingen en ingekleurde pagina's komen altijd mee, van elke serie — die zijn "
                    + "klein en duur betaald, dus die tellen niet mee in deze keuze."
            )
        }
    }

    private func haal() async {
        gebruikt = await Paginacache.gedeeld.omvang
        guard let client = instellingen.client else { return }
        // Zonder NAS is de laatst bekende lijst genoeg om vinkjes te zetten.
        let (resultaat, _) = await Bibliotheekcache.metTerugval(sleutel: "series-alles-") {
            try await client.series(filter: .alles)
        }
        if let resultaat {
            series = resultaat.items.sorted { $0.sortTitle < $1.sortTitle }
        } else {
            fout = "Geen verbinding, en er staat nog geen bibliotheek op dit toestel."
        }
    }
}
