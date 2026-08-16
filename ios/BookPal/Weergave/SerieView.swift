import SwiftUI

struct SerieView: View {
    let serieID: Int

    @Environment(Instellingen.self) private var instellingen
    @State private var detail: SeriesDetail?
    @State private var verder: VerderLezen?
    @State private var fout: String?
    @State private var bezig = false
    private var prioriteiten: Prioriteiten { Prioriteiten.gedeeld }

    /// Dezelfde sleutel als de web-app: wie daar gelezen hoofdstukken verbergt,
    /// wil dat hier ook.
    @AppStorage("series.hideRead") private var verbergGelezen = false

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

    /// Het vinkje dat deze serie beschermt tegen opruimen.
    ///
    /// Zonder vinkje verdwijnt een gelezen hoofdstuk vanzelf zodra de
    /// offline-opslag vol raakt — dat is precies de bedoeling voor wat je één
    /// keer leest. Aanvinken is voor wat je herleest of zeker wilt hebben
    /// zonder NAS. Wat van een abonnement komt is al beschermd zodra je het
    /// opent, dus daar hoef je niets voor te doen.
    private var offlineSectie: some View {
        Section {
            Toggle(isOn: Binding(
                get: { prioriteiten.isPrioriteit(serieID: serieID) },
                set: { prioriteiten.zet(serieID: serieID, prioriteit: $0) }
            )) {
                Label("Offline bewaren", systemImage: "arrow.down.circle")
            }
        } footer: {
            Text(
                prioriteiten.isPrioriteit(serieID: serieID)
                    ? "Wat je van deze serie leest blijft op je toestel staan, ook als de "
                        + "opslag vol raakt."
                    : "Uit: pagina's van deze serie mogen weg zodra de offline-opslag vol is. "
                        + "Wat van een abonnement komt blijft sowieso staan."
            )
        }
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

            offlineSectie

            if boeken.isEmpty && verbergGelezen {
                Section {
                    Text("Alles gelezen. Zet het oogje uit om ze weer te zien.")
                        .foregroundStyle(.secondary)
                }
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
