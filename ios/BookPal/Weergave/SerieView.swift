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
    /// Welke jaargangen openstaan. Bij Power Unlimited zijn het er
    /// tweeëndertig met 351 nummers; alles tegelijk tonen is geen lijst meer
    /// maar een muur.
    @State private var openJaargangen: Set<String> = []
    @State private var mappen: [LibraryRoot] = []
    @State private var wiki: [Wikisuggestie] = []
    /// Dezelfde sleutel als de bibliotheek: hier omzetten zet het daar ook om.
    /// Eén begrip van "omgekeerd" in de hele app is minder verwarrend dan twee
    /// die uit de pas kunnen lopen.
    @AppStorage("library.sortDesc") private var omgekeerd = false

    /// Hoe een deel hier heet. Bij Power Unlimited is "jaargang 17" juist, bij
    /// manga "deel 3" — en elke soort heeft zijn eigen bibliotheekmap, dus die
    /// map is het hele antwoord. Geen serverveld voor nodig.
    private var deelwoord: String {
        let pad = mappen.first { $0.id == detail?.libraryRootID }?.path ?? ""
        return pad.contains("tijdschriften") || pad.contains("print") ? "Jaargang" : "Deel"
    }

    /// De delen per jaargang, nieuwste eerst. Leeg als er geen jaargangen
    /// zijn — dan is groeperen alleen maar een extra tik.
    private var perJaargang: [(jaargang: String, delen: [Book])] {
        let metJaargang = boeken.compactMap { boek in boek.volume.map { ($0, boek) } }
        guard metJaargang.count == boeken.count, Set(metJaargang.map(\.0)).count > 1 else {
            return []
        }
        return Dictionary(grouping: metJaargang, by: \.0)
            .map { (jaargang: $0.key, delen: $0.value.map(\.1)) }
            .sorted { (Double($0.jaargang) ?? 0) > (Double($1.jaargang) ?? 0) }
    }

    private var boeken: [Book] {
        guard let detail else { return [] }
        let zichtbaar = verbergGelezen
            ? detail.books.filter { !($0.progress?.finished ?? false) }
            : detail.books
        return omgekeerd ? zichtbaar.reversed() : zichtbaar
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
                Toggle(isOn: $omgekeerd) {
                    Label("Omgekeerd", systemImage: "arrow.up.arrow.down")
                }
                .toggleStyle(.button)
                .labelStyle(.iconOnly)
            }
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
        .onChange(of: detail?.id) { _, _ in
            // De nieuwste jaargang open, de rest dicht. Dat is waar je bij een
            // lopend tijdschrift begint te kijken.
            if let eerste = perJaargang.first?.jaargang { openJaargangen = [eerste] }
        }
    }

    @ViewBuilder
    private func lijst(_ detail: SeriesDetail) -> some View {
        List {
            if let verder { verderSectie(verder) }
            if !wiki.isEmpty { wikiSectie }

            if let samenvatting = detail.summary, !samenvatting.isEmpty {
                Section("Over deze reeks") {
                    Text(samenvatting).font(.callout).foregroundStyle(.secondary)
                }
            }

            if boeken.isEmpty && verbergGelezen {
                Section {
                    Text("Alles gelezen. Zet het oogje uit om ze weer te zien.")
                        .foregroundStyle(.secondary)
                }
            } else if !perJaargang.isEmpty {
                ForEach(perJaargang, id: \.jaargang) { groep in
                    jaargangSectie(groep.jaargang, groep.delen)
                }
            } else if omslagen {
                Section(kop(detail)) { omslagraster(boeken) }
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

    /// Achtergrond van Wikipedia, boven de delen.
    ///
    /// Een los paneel en niet ergens onderin: dit is wat je wilt lezen vóórdat
    /// je aan een reeks begint, en bij een tijdschrift met tweeëndertig
    /// jaargangen zou het anders onvindbaar diep staan.
    ///
    /// Het opent als epub in dezelfde lezer als je boeken — dat is wat de
    /// server ervan maakt, dus het leest als alle andere tekst hier.
    @ViewBuilder
    private var wikiSectie: some View {
        Section {
            ForEach(wiki) { suggestie in
                if let client = instellingen.client,
                   let adres = client.wikiEpubURL(sleutel: suggestie.key, taal: suggestie.lang) {
                    Link(destination: adres) {
                        HStack(spacing: 10) {
                            Image(systemName: suggestie.overDeReeks ? "books.vertical" : "person")
                                .foregroundStyle(.secondary)
                                .frame(width: 20)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(suggestie.title).font(.callout)
                                Text(
                                    suggestie.description
                                        ?? (suggestie.overDeReeks ? "over de reeks" : suggestie.voor)
                                )
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                            }
                            Spacer()
                            Text(suggestie.lang.uppercased())
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        } header: {
            Text("Achtergrond")
        } footer: {
            Text("Artikelen van Wikipedia, als epub. Ze openen in je browser of leesapp.")
        }
    }

    /// Eén jaargang, dichtgeklapt tot je erop tikt.
    ///
    /// Standaard dicht, behalve de nieuwste: bij tweeëndertig jaargangen wil je
    /// een overzicht zien en niet meteen 351 regels. De kop zegt hoeveel er in
    /// zitten, zodat je weet of het de moeite is om open te klappen.
    @ViewBuilder
    private func jaargangSectie(_ jaargang: String, _ delen: [Book]) -> some View {
        let open = openJaargangen.contains(jaargang)
        Section {
            if open {
                if omslagen {
                    omslagraster(delen)
                        .listRowInsets(EdgeInsets(top: 8, leading: 12, bottom: 8, trailing: 12))
                } else {
                    ForEach(delen) { boek in rij(boek) }
                }
            }
        } header: {
            Button {
                if open { openJaargangen.remove(jaargang) } else { openJaargangen.insert(jaargang) }
            } label: {
                HStack {
                    Image(systemName: open ? "chevron.down" : "chevron.right")
                        .font(.caption2)
                    Text("\(deelwoord) \(jaargang)")
                    Spacer()
                    Text("\(delen.count)")
                        .foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
    }

    /// De omslagen naast elkaar, met het nummer en de verschijningsdatum
    /// eronder. Geen voortgangsbalk: die past niet in een tegel van honderd
    /// punten breed, en bij een tijdschrift blader je toch zelden halverwege
    /// weg.
    private func omslagraster(_ delen: [Book]) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 10)], spacing: 14) {
            ForEach(delen) { boek in
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

    /// Waar je verder leest, met de omslag van dát deel ernaast.
    ///
    /// Een regel tekst zegt bij een tijdschrift met 351 nummers weinig; de kaft
    /// van het nummer waar je in zit wél. De samenvatting van de serie staat
    /// eronder als die er is — bij een boek is dat de flaptekst, en die wil je
    /// juist hier zien en niet drie secties lager.
    private func label(_ verder: VerderLezen) -> some View {
        HStack(alignment: .top, spacing: 12) {
            if let client = instellingen.client {
                OmslagView(url: client.boekOmslagURL(boek: verder.bookID), titel: verder.title)
                    .frame(width: 64)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(verder.resuming ? "Lees verder" : "Beginnen")
                    .font(.headline)
                Text(verder.title + (verder.hasFile ? "" : " — moet nog opgehaald"))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                // Over dít deel, niet over de reeks — die staat verderop als
                // eigen sectie. Een hoofdstuksamenvatting hebben we niet in de
                // gegevens, dus dit is wat we wél weten: waar je bent en hoe
                // lang het is.
                if let boek = detail?.books.first(where: { $0.id == verder.bookID }) {
                    HStack(spacing: 8) {
                        if let paginas = boek.pageCount { Text("\(paginas) pagina's") }
                        if let verschenen = boek.verschenen { Text(verschenen) }
                        if let voortgang = boek.progress, voortgang.percent > 0 {
                            Text("\(Int(voortgang.percent))% gelezen")
                        }
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
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
            if mappen.isEmpty { mappen = (try? await client.roots()) ?? [] }
            // Mag mislukken: Wikipedia is achtergrond, geen voorwaarde om te
            // kunnen lezen.
            wiki = (try? await client.wikiVoorSerie(serieID, taal: instellingen.taal)) ?? []
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
