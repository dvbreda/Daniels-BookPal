import SwiftUI

struct SerieView: View {
    let serieID: Int

    @Environment(Instellingen.self) private var instellingen
    @State private var detail: SeriesDetail?
    @State private var verder: VerderLezen?
    @State private var fout: String?
    @State private var bezig = false

    /// Dezelfde sleutel als de web-app: wie daar gelezen hoofdstukken verbergt,
    /// wil dat hier ook.
    @AppStorage("series.hideRead") private var verbergGelezen = false
    /// Omslagen of een lijst. Bij een tijdschrift wil je de covers zien — die
    /// dragen daar de herkenning, want "nummer 412" zegt je niets en die ene
    /// kaft wel. Bij een reeks waar elk deel er hetzelfde uitziet is een lijst
    /// juist rustiger, dus het is een keuze en geen automatisme.
    @AppStorage("series.coverGrid") private var omslagen = false

    private var boeken: [Book] {
        guard let detail else { return [] }
        return verbergGelezen
            ? detail.books.filter { !($0.progress?.finished ?? false) }
            : detail.books
    }

    var body: some View {
        Group {
            if let fout {
                ContentUnavailableView(
                    "Niet gelukt", systemImage: "exclamationmark.triangle", description: Text(fout)
                )
            } else if let detail {
                lijst(detail)
            } else {
                ProgressView("Serie ophalen…")
            }
        }
        .navigationTitle(detail?.title ?? "Serie")
        .navigationBarTitleDisplayMode(.inline)
        // Weg met de tabbalk: hier lees je, en dan is elke pixel onderin
        // strip in plaats van navigatie.
        .toolbar(.hidden, for: .tabBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Toggle(isOn: $omslagen) {
                    Label("Omslagen", systemImage: omslagen ? "square.grid.2x2.fill" : "square.grid.2x2")
                }
                .toggleStyle(.button)
                .labelStyle(.iconOnly)
            }
            ToolbarItem(placement: .topBarTrailing) {
                Toggle(isOn: $verbergGelezen) {
                    Label("Gelezen verbergen", systemImage: verbergGelezen ? "eye.slash" : "eye")
                }
                .toggleStyle(.button)
                .labelStyle(.iconOnly)
            }
        }
        .task { await haal() }
        .refreshable { await haal() }
    }

    @ViewBuilder
    private func lijst(_ detail: SeriesDetail) -> some View {
        List {
            if let verder { verderSectie(verder) }

            if let samenvatting = detail.summary, !samenvatting.isEmpty {
                Section {
                    Text(samenvatting).font(.callout).foregroundStyle(.secondary)
                }
            }

            if boeken.isEmpty && verbergGelezen {
                Section {
                    Text("Alles gelezen. Zet het oogje uit om ze weer te zien.")
                        .foregroundStyle(.secondary)
                }
            } else if omslagen {
                Section(kop(detail)) { omslagraster }
                    .listRowInsets(EdgeInsets(top: 8, leading: 12, bottom: 8, trailing: 12))
            } else {
                Section(kop(detail)) {
                    ForEach(boeken) { boek in
                        rij(boek)
                    }
                }
            }
        }
        .listStyle(.plain)
    }

    /// De omslagen naast elkaar, met het nummer en de verschijningsdatum
    /// eronder. Geen voortgangsbalk: die past niet in een tegel van honderd
    /// punten breed, en bij een tijdschrift blader je toch zelden halverwege
    /// weg.
    private var omslagraster: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 10)], spacing: 14) {
            ForEach(boeken) { boek in
                NavigationLink {
                    if boek.kind == .epub { EpubLezerView(boek: boek) } else { LezerView(boek: boek) }
                } label: {
                    omslagtegel(boek)
                }
                .buttonStyle(.plain)
                .disabled(!boek.isReadable && !(boek.kind == .epub && boek.hasFile))
            }
        }
    }

    private func omslagtegel(_ boek: Book) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            ZStack(alignment: .topTrailing) {
                if let client = instellingen.client {
                    OmslagView(url: client.boekOmslagURL(boek: boek.id), titel: boek.label)
                }
                if boek.progress?.finished == true {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                        .background(Circle().fill(.background))
                        .padding(5)
                }
            }
            Text(kort(boek))
                .font(.caption2)
                .lineLimit(1)
            if let verschenen = boek.verschenen {
                Text(verschenen)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            } else if !boek.hasFile {
                Text("nog online").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .contentShape(Rectangle())
    }

    /// Kort label onder een omslag: het nummer als dat er is, anders de titel.
    /// In een tegel van honderd punten past geen "Deel 3, hoofdstuk 12 — …".
    private func kort(_ boek: Book) -> String {
        if let nummer = boek.number {
            return boek.volume.map { "jg \($0) · \(nummer)" } ?? "nr \(nummer)"
        }
        return boek.title
    }

    private func kop(_ detail: SeriesDetail) -> String {
        let totaal = detail.books.count
        if verbergGelezen && boeken.count != totaal {
            return "\(boeken.count) van \(totaal) delen"
        }
        return "\(totaal) delen"
    }

    private func verderSectie(_ verder: VerderLezen) -> some View {
        Section {
            if let boek = detail?.books.first(where: { $0.id == verder.bookID }), boek.isReadable {
                NavigationLink {
                    LezerView(boek: boek)
                } label: {
                    label(verder)
                }
            } else if let boek = detail?.books.first(where: { $0.id == verder.bookID }),
                      boek.kind == .epub, boek.hasFile {
                NavigationLink {
                    EpubLezerView(boek: boek)
                } label: {
                    label(verder)
                }
            } else {
                // Nog niet opgehaald: bij een serie die je vooral online volgt
                // is dat de normale situatie.
                label(verder).foregroundStyle(.secondary)
            }

            if verder.unreadBefore > 0 {
                Button {
                    Task { await markeerEerdere(verder.bookID) }
                } label: {
                    Label(
                        "Markeer \(verder.unreadBefore) eerdere als gelezen",
                        systemImage: "checkmark.circle"
                    )
                    .font(.callout)
                }
                .disabled(bezig)
            }
        }
    }

    private func label(_ verder: VerderLezen) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(verder.resuming ? "Lees verder" : "Beginnen")
                .font(.headline)
            Text(verder.title + (verder.hasFile ? "" : " — moet nog opgehaald"))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func rij(_ boek: Book) -> some View {
        Group {
            if boek.isReadable {
                NavigationLink { LezerView(boek: boek) } label: { inhoudVanRij(boek) }
            } else if boek.kind == .epub, boek.hasFile {
                NavigationLink { EpubLezerView(boek: boek) } label: { inhoudVanRij(boek) }
            } else {
                // Een hoofdstuk zonder bestand is geen fout: dat is er wel, het
                // moet alleen nog opgehaald worden.
                inhoudVanRij(boek).foregroundStyle(.secondary)
            }
        }
        .swipeActions(edge: .leading) {
            let gelezen = boek.progress?.finished ?? false
            Button {
                Task { await zetGelezen(boek, !gelezen) }
            } label: {
                Label(
                    gelezen ? "Ongelezen" : "Gelezen",
                    systemImage: gelezen ? "arrow.uturn.backward" : "checkmark"
                )
            }
            .tint(gelezen ? .orange : .green)
        }
    }

    private func inhoudVanRij(_ boek: Book) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                if boek.progress?.finished == true {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.green)
                }
                Text(boek.label).font(.body)
            }
            HStack(spacing: 8) {
                if let paginas = boek.pageCount {
                    Text("\(paginas) pagina's")
                }
                if let uitgave = boek.editionLabel {
                    Text(uitgave)
                }
                if !boek.hasFile {
                    Label("nog online", systemImage: "cloud")
                } else if boek.kind == .epub {
                    Label("epub", systemImage: "book")
                }
                if boek.rightToLeft {
                    Text("rechts-naar-links")
                }
            }
            .font(.caption2)
            .foregroundStyle(.secondary)

            if let voortgang = boek.progress, voortgang.percent > 0, !voortgang.finished {
                ProgressView(value: min(voortgang.percent, 100), total: 100)
            }
        }
        .padding(.vertical, 2)
    }

    // MARK: - Gedrag

    private func haal() async {
        guard let client = instellingen.client else {
            fout = ClientFout.geenAdres.localizedDescription
            return
        }
        do {
            detail = try await client.serie(serieID)
            // Mag ontbreken: bij een uitgelezen serie is er niets om verder te
            // lezen, en dat is geen fout.
            verder = try? await client.verderLezen(serie: serieID)
            fout = nil
        } catch {
            fout = error.localizedDescription
        }
    }

    private func zetGelezen(_ boek: Book, _ gelezen: Bool) async {
        guard let client = instellingen.client else { return }
        bezig = true
        defer { bezig = false }
        try? await client.zetGelezen(boek: boek.id, gelezen: gelezen)
        await haal()
    }

    private func markeerEerdere(_ boek: Int) async {
        guard let client = instellingen.client else { return }
        bezig = true
        defer { bezig = false }
        try? await client.markeerEerdereGelezen(serie: serieID, boek: boek)
        await haal()
    }
}
