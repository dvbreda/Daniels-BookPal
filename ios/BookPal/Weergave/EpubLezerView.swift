import SwiftUI

/// De epub-lezer: opent waar je gebleven was, met de inhoudsopgave op een knop.
///
/// De lijst was eerst het beginscherm en het hoofdstuk een niveau dieper. Dat is
/// verkeerd om: een boek openen doe je om verder te lezen, niet om te kiezen.
/// Nu is het hoofdstuk het scherm en staat de inhoudsopgave onder het
/// lijstknopje — voor de keren dat je wél wilt bladeren.
///
/// **Let op bij de voortgang.** De web-lezer (foliate-js) bewaart zijn plek als
/// CFI — een verwijzing in de epub-structuur. Die kunnen wij niet maken, want we
/// tekenen de tekst zelf. Daarom schrijft deze lezer wél hetzelfde `percent`
/// terug, want dáár hangen leesstatus, "verder lezen" en de tabs aan, maar zijn
/// eigen plek als `{"hoofdstuk": n, "blok": m}`. Gevolg: je percentage en je
/// leesstatus lopen tussen telefoon en browser gewoon mee, maar precies
/// terugspringen naar dezelfde zin doet alleen de client die de plek geschreven
/// heeft. De web-lezer negeert een positie zonder `cfi` en begint dan vooraan.
struct EpubLezerView: View {
    let boek: Book

    @Environment(Instellingen.self) private var instellingen
    @State private var lees = LeesInstellingen()
    @Environment(\.colorScheme) private var kleurschema

    @State private var inhoud: EpubParser.Inhoud?
    @State private var huidig: EpubParser.Hoofdstuk?
    @State private var fout: String?
    @State private var downloadFractie: Double?
    @State private var toontInhoud = false
    @State private var toontInstellingen = false

    var body: some View {
        Group {
            if let fout {
                ContentUnavailableView(
                    "Niet gelukt", systemImage: "exclamationmark.triangle", description: Text(fout)
                )
            } else if let inhoud, let huidig {
                HoofdstukView(
                    boek: boek,
                    hoofdstuk: huidig,
                    aantalHoofdstukken: inhoud.hoofdstukken.count,
                    lees: lees,
                    volgende: volgendeNa(huidig, in: inhoud),
                    ga: { self.huidig = $0 }
                )
                // Een nieuw hoofdstuk is een nieuw scherm: blokken opnieuw
                // splitsen en bovenaan beginnen, in plaats van de oude
                // scrollpositie meenemen.
                .id(huidig.id)
            } else {
                bezig
            }
        }
        .navigationTitle(huidig?.titel ?? inhoud?.titel ?? boek.title)
        .navigationBarTitleDisplayMode(.inline)
        // Weg met de tabbalk: hier lees je, en dan is elke pixel onderin
        // strip in plaats van navigatie.
        .toolbar(.hidden, for: .tabBar)
        .toolbar {
            if inhoud != nil {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button {
                        toontInstellingen = true
                    } label: {
                        Label("Lezen", systemImage: "textformat.size")
                    }
                    Button {
                        toontInhoud = true
                    } label: {
                        Label("Inhoud", systemImage: "list.bullet")
                    }
                }
            }
        }
        .sheet(isPresented: $toontInstellingen) {
            LeesInstellingenSheet(lees: lees)
                .presentationDetents([.height(220)])
        }
        .sheet(isPresented: $toontInhoud) {
            if let inhoud {
                InhoudSheet(inhoud: inhoud, huidig: huidig) { gekozen in
                    huidig = gekozen
                }
            }
        }
        .task { await open() }
    }

    private var bezig: some View {
        VStack(spacing: 12) {
            if let fractie = downloadFractie {
                ProgressView(value: fractie) {
                    Text("Boek ophalen…")
                }
                .padding(.horizontal, 40)
            } else {
                ProgressView("Boek ophalen…")
            }
        }
    }

    private func volgendeNa(
        _ hoofdstuk: EpubParser.Hoofdstuk, in inhoud: EpubParser.Inhoud
    ) -> EpubParser.Hoofdstuk? {
        guard let plek = inhoud.hoofdstukken.firstIndex(where: { $0.id == hoofdstuk.id }),
              plek + 1 < inhoud.hoofdstukken.count
        else { return nil }
        return inhoud.hoofdstukken[plek + 1]
    }

    private func open() async {
        guard inhoud == nil, let client = instellingen.client else { return }
        do {
            let bestand = try await EpubOpslag.haal(client: client, boek: boek.id) { fractie in
                downloadFractie = fractie
            }
            // Uitpakken buiten de hoofdthread: zip openen en tientallen
            // hoofdstukken door een reguliere expressie halen is te veel om het
            // scherm voor te laten staan.
            let beeldmap = EpubOpslag.beeldmap(boek: boek.id)
            let gelezen = try await Task.detached(priority: .userInitiated) {
                try EpubParser.parse(url: bestand, beeldmap: beeldmap)
            }.value
            inhoud = gelezen
            huidig = beginHoofdstuk(gelezen)
        } catch {
            // Een half binnengehaald bestand blijft anders staan en blijft dan
            // elke keer opnieuw mislukken.
            EpubOpslag.gooiWeg(boek: boek.id)
            fout = error.localizedDescription
        }
    }

    /// Waar we openen: je eigen plek als die er is, anders vooraan.
    ///
    /// Een plek die de web-lezer geschreven heeft (een CFI) levert hier niets
    /// op; dan is vooraan beginnen het eerlijke antwoord.
    private func beginHoofdstuk(_ inhoud: EpubParser.Inhoud) -> EpubParser.Hoofdstuk? {
        if let plek = bewaardePlek(boek),
           let terug = inhoud.hoofdstukken.first(where: { $0.id == plek.hoofdstuk }) {
            return terug
        }
        return inhoud.hoofdstukken.first
    }
}

/// De bewaarde plek van déze lezer, of niets als hij van de web-lezer komt.
private func bewaardePlek(_ boek: Book) -> (hoofdstuk: Int, blok: Int)? {
    guard let positie = boek.progress?.position,
          case let .getal(hoofdstuk) = positie["hoofdstuk"],
          case let .getal(blok) = positie["blok"]
    else { return nil }
    return (hoofdstuk, blok)
}

/// De inhoudsopgave, als blad over het hoofdstuk heen.
private struct InhoudSheet: View {
    let inhoud: EpubParser.Inhoud
    let huidig: EpubParser.Hoofdstuk?
    let kies: (EpubParser.Hoofdstuk) -> Void

    @Environment(\.dismiss) private var sluit

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(inhoud.hoofdstukken) { hoofdstuk in
                        Button {
                            kies(hoofdstuk)
                            sluit()
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(hoofdstuk.titel).lineLimit(2)
                                    Text("\(hoofdstuk.tekens) tekens")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                if hoofdstuk.id == huidig?.id {
                                    Image(systemName: "book.fill")
                                        .foregroundStyle(.tint)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                } header: {
                    Text("\(inhoud.hoofdstukken.count) hoofdstukken · \(inhoud.auteur)")
                }
            }
            .listStyle(.plain)
            .navigationTitle("Inhoud")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Klaar") { sluit() }
                }
            }
        }
    }
}

/// Eén hoofdstuk, in blokken, met de leesplek erin.
private struct HoofdstukView: View {
    let boek: Book
    let hoofdstuk: EpubParser.Hoofdstuk
    let aantalHoofdstukken: Int
    let lees: LeesInstellingen
    let volgende: EpubParser.Hoofdstuk?
    let ga: (EpubParser.Hoofdstuk) -> Void

    @Environment(Instellingen.self) private var instellingen
    @Environment(\.colorScheme) private var kleurschema

    @State private var blokken: [String] = []
    @State private var zichtbaarBlok = 0
    @State private var bewaartaak: Task<Void, Never>?

    var body: some View {
        ScrollViewReader { scroll in
            ScrollView {
                // Geen eigen tussenruimte: `NSAttributedString` brengt de marges
                // van de `<p>`'s zelf al mee, en die er nog eens 12 punt
                // bovenop deed elke alinea een halve schermhoogte uit elkaar
                // staan.
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(blokken.enumerated()), id: \.offset) { index, blok in
                        OpgemaakteTekst(
                            html: blok,
                            lettergrootte: lees.lettergrootte,
                            regelafstand: lees.regelafstand,
                            donker: kleurschema == .dark
                        )
                        .id(index)
                        .onAppear {
                            // Het hoogste blok dat je gezien hebt is je plek.
                            if index > zichtbaarBlok { zichtbaarBlok = index; planBewaren() }
                        }
                    }
                    if let volgende { volgendeKnop(volgende) }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
            }
            .task {
                blokken = HTMLBlokken.splits(hoofdstuk.html)
                // Terug naar waar je was, maar alleen als deze client de plek
                // geschreven heeft — zie de uitleg boven `EpubLezerView`.
                if let plek = bewaardePlek(boek), plek.hoofdstuk == hoofdstuk.id, plek.blok > 0 {
                    zichtbaarBlok = plek.blok
                    try? await Task.sleep(for: .milliseconds(150))
                    scroll.scrollTo(plek.blok, anchor: .top)
                }
            }
        }
        .onDisappear {
            bewaartaak?.cancel()
            Task { await bewaar() }
        }
    }

    /// Onderaan het hoofdstuk: door naar het volgende, zonder via de lijst.
    private func volgendeKnop(_ volgende: EpubParser.Hoofdstuk) -> some View {
        Button {
            Task { await bewaar() }
            ga(volgende)
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Volgende hoofdstuk").font(.caption).foregroundStyle(.secondary)
                    Text(volgende.titel).font(.body).lineLimit(2)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(.secondary)
            }
            .padding(.vertical, 14)
        }
        .buttonStyle(.plain)
        .padding(.top, 24)
    }

    private func planBewaren() {
        bewaartaak?.cancel()
        bewaartaak = Task {
            try? await Task.sleep(for: .milliseconds(1500))
            guard !Task.isCancelled else { return }
            await bewaar()
        }
    }

    /// Grof percentage: hoe ver door de hoofdstukken, plus je plek in dit
    /// hoofdstuk. Niet precies op tekens — dat suggereert een nauwkeurigheid die
    /// er niet is zolang hoofdstukken verschillend lang zijn — maar wel
    /// monotoon, en dat is wat "verder lezen" nodig heeft.
    private var percent: Double {
        guard aantalHoofdstukken > 0 else { return 0 }
        let perHoofdstuk = 100.0 / Double(aantalHoofdstukken)
        let binnen = blokken.isEmpty
            ? 0
            : Double(zichtbaarBlok + 1) / Double(blokken.count)
        return min(100, (Double(hoofdstuk.id) * perHoofdstuk + binnen * perHoofdstuk).rounded())
    }

    private func bewaar() async {
        guard let client = instellingen.client else { return }
        try? await client.bewaarVoortgang(
            boek: boek.id,
            positie: ["hoofdstuk": hoofdstuk.id, "blok": zichtbaarBlok],
            percent: percent,
            uitgelezen: percent >= 100
        )
    }
}

private struct LeesInstellingenSheet: View {
    @Bindable var lees: LeesInstellingen
    @Environment(\.dismiss) private var sluit

    var body: some View {
        NavigationStack {
            Form {
                VStack(alignment: .leading) {
                    Text("Lettergrootte: \(Int(lees.lettergrootte))")
                    Slider(value: $lees.lettergrootte, in: 12...30, step: 1)
                }
                VStack(alignment: .leading) {
                    Text("Regelafstand: \(lees.regelafstand, specifier: "%.1f")")
                    Slider(value: $lees.regelafstand, in: 1.0...2.2, step: 0.1)
                }
            }
            .navigationTitle("Lezen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Klaar") { sluit() }
                }
            }
        }
    }
}
