import SwiftUI

/// Zoeken bij een bron, volgen, en zien wat je volgt.
///
/// Wat hier gebeurt kost geen geld, maar verandert wél iets: volgen maakt
/// hoofdstukken aan in je bibliotheek, en ophalen kost schijfruimte op de NAS.
/// Daarom zegt elke knop wat hij doet en staat er bij een abonnement hoeveel er
/// al binnen is.
struct BronnenView: View {
    @Environment(Instellingen.self) private var instellingen

    @State private var bronnen: [Bron] = []
    @State private var gekozenBron: Int?
    @State private var zoek = ""
    @State private var treffers: [Zoektreffer] = []
    @State private var abonnementen: [Abonnement] = []
    @State private var zoekt = false
    @State private var bezig = false
    @State private var melding: String?
    @State private var fout: String?
    @State private var teVolgen: Zoektreffer?

    var body: some View {
        List {
            if let melding {
                Section { Text(melding).font(.callout).foregroundStyle(.secondary) }
            }
            if let fout {
                Section { Text(fout).font(.callout).foregroundStyle(.red) }
            }

            zoekSectie
            if !treffers.isEmpty { trefferSectie }
            abonnementSectie
        }
        .navigationTitle("Bronnen")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $zoek, prompt: "Zoek een reeks")
        .onSubmit(of: .search) { Task { await zoekNu() } }
        .task { await haal() }
        .refreshable { await haal() }
        .sheet(item: $teVolgen) { treffer in
            VolgSheet(treffer: treffer, bron: gekozenBron ?? 0) { melding in
                self.melding = melding
                Task { await haal() }
            }
        }
    }

    private var zoekSectie: some View {
        Section {
            Picker("Bron", selection: $gekozenBron) {
                Text("Kies een bron").tag(Int?.none)
                ForEach(bronnen.filter(\.enabled)) { bron in
                    Text(bron.name).tag(Int?.some(bron.id))
                }
            }
            if zoekt {
                HStack { ProgressView(); Text("Zoeken…").foregroundStyle(.secondary) }
            }
        } header: {
            Text("Zoeken")
        } footer: {
            Text("Typ in het zoekveld en druk op enter. Elke bron zoekt in zijn eigen catalogus.")
        }
    }

    private var trefferSectie: some View {
        Section("\(treffers.count) treffers") {
            ForEach(treffers) { treffer in
                Button {
                    teVolgen = treffer
                } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(treffer.title).font(.body)
                        HStack(spacing: 8) {
                            if let jaar = treffer.year { Text(String(jaar)) }
                            if let status = treffer.status { Text(status) }
                            if !treffer.languages.isEmpty {
                                Text(treffer.languages.prefix(4).joined(separator: "/"))
                            }
                        }
                        .font(.caption2)
                        .foregroundStyle(.secondary)

                        if treffer.alGevolgd {
                            Label("volg je al", systemImage: "checkmark.circle.fill")
                                .font(.caption2)
                                .foregroundStyle(.green)
                        } else if let bestaand = treffer.existingSeriesTitle {
                            // Hetzelfde ding onder een andere naam: dan wordt dit
                            // een uitgave van die serie in plaats van een tweede.
                            Label("wordt een uitgave van «\(bestaand)»", systemImage: "arrow.triangle.merge")
                                .font(.caption2)
                                .foregroundStyle(.orange)
                        }
                    }
                }
                .disabled(treffer.alGevolgd)
            }
        }
    }

    private var abonnementSectie: some View {
        Section {
            if abonnementen.isEmpty {
                Text("Je volgt nog niets.").foregroundStyle(.secondary)
            } else {
                ForEach(abonnementen) { abo in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(abo.seriesTitle).font(.body)
                        HStack(spacing: 8) {
                            Text(abo.isPermanent ? "alles bewaren" : "\(abo.readaheadN) vooruit")
                            Text(abo.language.uppercased())
                            Text("\(abo.chaptersLocal) van \(abo.chaptersTotal) binnen")
                        }
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        if abo.chaptersTotal > 0 {
                            ProgressView(
                                value: Double(abo.chaptersLocal),
                                total: Double(abo.chaptersTotal)
                            )
                        }
                    }
                    .swipeActions {
                        Button(role: .destructive) {
                            Task { await stop(abo) }
                        } label: {
                            Label("Stoppen", systemImage: "trash")
                        }
                        Button {
                            Task { await ververs(abo) }
                        } label: {
                            Label("Bijwerken", systemImage: "arrow.clockwise")
                        }
                        .tint(.blue)
                    }
                }
            }

            Button {
                Task { await ronde() }
            } label: {
                HStack {
                    Label("Nu bijwerken", systemImage: "arrow.clockwise")
                    if bezig { Spacer(); ProgressView() }
                }
            }
            .disabled(bezig)
        } header: {
            Text("Wat je volgt")
        } footer: {
            Text(
                "Bijwerken haalt nieuwe hoofdstukken op en leest een paar vooruit. "
                    + "Dat gebeurt ook vanzelf op een interval; dit is de knop om er niet op "
                    + "te hoeven wachten. Veeg over een serie om hem bij te werken of te stoppen."
            )
        }
    }

    // MARK: - Gedrag

    private func haal() async {
        guard let client = instellingen.client else { return }
        async let b = try? client.bronnen()
        async let a = try? client.abonnementen()
        bronnen = await b ?? []
        abonnementen = await a ?? []
        if gekozenBron == nil { gekozenBron = bronnen.first(where: \.enabled)?.id }
    }

    private func zoekNu() async {
        guard let client = instellingen.client, let bron = gekozenBron, !zoek.isEmpty else {
            return
        }
        zoekt = true
        fout = nil
        defer { zoekt = false }
        do {
            treffers = try await client.zoek(bron: bron, term: zoek)
            if treffers.isEmpty { melding = "Niets gevonden voor «\(zoek)»." }
        } catch {
            fout = error.localizedDescription
        }
    }

    private func ronde() async {
        guard let client = instellingen.client else { return }
        bezig = true
        fout = nil
        defer { bezig = false }
        do {
            melding = try await client.draaiRonde().samenvatting
            await haal()
        } catch {
            fout = error.localizedDescription
        }
    }

    private func ververs(_ abo: Abonnement) async {
        guard let client = instellingen.client else { return }
        try? await client.ververs(abonnement: abo.id)
        melding = "«\(abo.seriesTitle)» bijgewerkt."
        await haal()
    }

    private func stop(_ abo: Abonnement) async {
        guard let client = instellingen.client else { return }
        try? await client.stopAbonnement(abo.id)
        melding = "Je volgt «\(abo.seriesTitle)» niet meer. Wat al binnen is blijft staan."
        await haal()
    }
}

/// Hoe je een reeks gaat volgen: taal, en of alles bewaard blijft.
private struct VolgSheet: View {
    let treffer: Zoektreffer
    let bron: Int
    let klaar: (String) -> Void

    @Environment(Instellingen.self) private var instellingen
    @Environment(\.dismiss) private var sluit

    @State private var taal = "en"
    @State private var permanent = false
    @State private var vooruit = 3
    @State private var bezig = false
    @State private var fout: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(treffer.title).font(.headline)
                    if let beschrijving = treffer.description, !beschrijving.isEmpty {
                        Text(beschrijving)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(6)
                    }
                }

                Section("Taal") {
                    Picker("Taal", selection: $taal) {
                        ForEach(treffer.languages.isEmpty ? ["en"] : treffer.languages, id: \.self) {
                            Text($0.uppercased()).tag($0)
                        }
                    }
                }

                Section {
                    Toggle("Alles bewaren", isOn: $permanent)
                    if !permanent {
                        Stepper("\(vooruit) hoofdstukken vooruit", value: $vooruit, in: 0...20)
                    }
                } header: {
                    Text("Wat er opgehaald wordt")
                } footer: {
                    Text(
                        permanent
                            ? "Elk hoofdstuk blijft op de NAS staan."
                            : "Er wordt vooruitgelezen vanaf waar je bent; wat je al gelezen hebt "
                                + "wordt weer opgeruimd. Het hoofdstuk blijft zichtbaar, alleen "
                                + "het bestand gaat weg."
                    )
                }

                if let fout {
                    Section { Text(fout).font(.callout).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Volgen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuleren") { sluit() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Volgen") { Task { await volg() } }.disabled(bezig)
                }
            }
            .task {
                taal = treffer.languages.first ?? "en"
            }
        }
    }

    private func volg() async {
        guard let client = instellingen.client else { return }
        bezig = true
        defer { bezig = false }
        do {
            try await client.volg(
                bron: bron,
                ref: treffer.ref,
                taal: taal,
                policy: permanent ? "permanent" : "readahead",
                vooruit: vooruit
            )
            klaar("Je volgt «\(treffer.title)» nu. De hoofdstukken komen binnen bij de volgende ronde.")
            sluit()
        } catch {
            fout = error.localizedDescription
        }
    }
}
