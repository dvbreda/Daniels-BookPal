import SwiftUI

struct BibliotheekView: View {
    @Environment(Instellingen.self) private var instellingen

    @State private var series: [Series] = []
    @State private var tabs: [Bibliotheektab] = []
    @State private var roots: [LibraryRoot] = []
    @State private var filter = Bibliotheekfilter.alles
    @State private var zoek = ""
    @State private var laadt = false
    @State private var fout: String?
    @State private var toontInstellingen = false
    @State private var toontFilter = false
    /// Zie `HomeView` — dezelfde terugval, dezelfde balk.
    @State private var vanCache = false
    /// Per categorie onthouden: bij tijdschriften wil je het nieuwste nummer
    /// bovenaan, bij je strips de reeksnaam. Eén keuze voor alles zou je bij
    /// elke tabwissel opnieuw laten omzetten.
    @AppStorage("library.sortPerGroup") private var sorteringRuw = ""

    private var sortering: Sortering {
        get {
            let bewaard = sorteringRuw
                .split(separator: ",")
                .first { $0.hasPrefix(filter.groep.rawValue + ":") }?
                .split(separator: ":").last
            return bewaard.flatMap { Sortering(rawValue: String($0)) }
                ?? Sortering.standaard(voor: filter.groep)
        }
        nonmutating set {
            var delen = sorteringRuw
                .split(separator: ",")
                .filter { !$0.hasPrefix(filter.groep.rawValue + ":") }
                .map(String.init)
            delen.append("\(filter.groep.rawValue):\(newValue.rawValue)")
            sorteringRuw = delen.joined(separator: ",")
        }
    }

    private let kolommen = [GridItem(.adaptive(minimum: 110), spacing: 12)]

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if vanCache { Offlinebanner() }
                soortbalk
                if !tabs.isEmpty { tabbalk }
                inhoud
            }
            .navigationTitle("Bibliotheek")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        toontFilter = true
                    } label: {
                        Label("Filteren", systemImage: filter.aantalLos > 0
                            ? "line.3.horizontal.decrease.circle.fill"
                            : "line.3.horizontal.decrease.circle")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Picker("Sorteren", selection: Binding(
                            get: { sortering },
                            set: { sortering = $0 }
                        )) {
                            ForEach(Sortering.allCases) { keuze in
                                Label(keuze.naamgeving, systemImage: keuze.icoon).tag(keuze)
                            }
                        }
                    } label: {
                        Label("Sorteren", systemImage: "arrow.up.arrow.down")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        toontInstellingen = true
                    } label: {
                        Label("Instellingen", systemImage: "gearshape")
                    }
                }
            }
            .searchable(text: $zoek, prompt: "Zoek een serie")
            .onSubmit(of: .search) { Task { await haal() } }
            .sheet(isPresented: $toontInstellingen) { InstellingenView() }
            .sheet(isPresented: $toontFilter) {
                FilterSheet(filter: $filter, roots: roots)
            }
            .onChange(of: filter) { _, _ in Task { await haal() } }
        .onChange(of: sorteringRuw) { _, _ in Task { await haal() } }
            .task { await start() }
            .refreshable { await haal() }
        }
    }

    /// Dezelfde grove indeling als op de startpagina: boeken, strips, manga.
    ///
    /// Boven de tabs, want hij snijdt er dwars doorheen: eerst kies je waar je
    /// in leest, dan pas welke tab. Hij blijft dus staan als je een tab kiest,
    /// anders dan de losse filters onder het trechtertje.
    private var soortbalk: some View {
        // Icoon met kleine tekst eronder, net als de hoofdtabbalk. Als chips
        // met alleen tekst pasten zes categorieën niet meer op een telefoon;
        // zo blijft elke keuze leesbaar en even breed.
        HStack(spacing: 0) {
            ForEach(Soortfilter.allCases) { keuze in
                let actief = filter.groep == keuze
                Button {
                    filter.groep = keuze
                } label: {
                    VStack(spacing: 3) {
                        Image(systemName: keuze.icoon)
                            .font(.system(size: 17))
                            .symbolVariant(actief ? .fill : .none)
                        Text(keuze.naam)
                            .font(.system(size: 10))
                            .lineLimit(1)
                            .minimumScaleFactor(0.8)
                    }
                    .frame(maxWidth: .infinity)
                    .foregroundStyle(actief ? Color.accentColor : Color.secondary)
                    .padding(.vertical, 6)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 4)
        .padding(.bottom, 6)
    }

    /// De tabs uit de web-app als filterbalk. Hun regel blijft op de server —
    /// die compileert hem naar een query, en dat is precies waarom hij daar
    /// hoort te blijven.
    private var tabbalk: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8) {
                chip(naam: "Alles", icoon: nil, actief: filter.tabID == nil) {
                    filter.kiesTab(nil)
                }
                ForEach(tabs.filter(\.enabled)) { tab in
                    chip(naam: tab.name, icoon: tab.icon, actief: filter.tabID == tab.id) {
                        filter.kiesTab(tab.id)
                    }
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 8)
        }
        .scrollIndicators(.hidden)
    }

    private func chip(
        naam: String, icoon: String?, actief: Bool, actie: @escaping () -> Void
    ) -> some View {
        Button(action: actie) {
            HStack(spacing: 4) {
                if let icoon, !icoon.isEmpty { Text(icoon) }
                Text(naam)
            }
            .font(.subheadline)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(
                Capsule().fill(actief ? Color.accentColor : Color(.secondarySystemBackground))
            )
            .foregroundStyle(actief ? .white : .primary)
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var inhoud: some View {
        if let fout {
            // Een leeg scherm zonder uitleg is de ergste uitkomst: dan weet je
            // niet of de NAS uit staat, of het adres fout is, of dat je
            // bibliotheek echt leeg is.
            ContentUnavailableView {
                Label("Geen verbinding", systemImage: "wifi.exclamationmark")
            } description: {
                Text(fout)
            } actions: {
                Button("Opnieuw proberen") { Task { await haal() } }
                Button("Instellingen") { toontInstellingen = true }
            }
        } else if series.isEmpty && laadt {
            ProgressView("Bibliotheek ophalen…").frame(maxHeight: .infinity)
        } else if series.isEmpty {
            ContentUnavailableView(
                filter.isLeeg ? "Niets gevonden" : "Niets in dit filter",
                systemImage: "books.vertical",
                description: Text(
                    filter.isLeeg
                        ? "Er staan geen series in de bibliotheek."
                        : "Geen serie voldoet aan wat je hebt gekozen."
                )
            )
        } else {
            ScrollView {
                LazyVGrid(columns: kolommen, spacing: 16) {
                    ForEach(series) { serie in
                        NavigationLink(value: serie.id) {
                            tegel(serie)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding()
            }
            .navigationDestination(for: Int.self) { id in
                SerieView(serieID: id)
            }
        }
    }

    private func tegel(_ serie: Series) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if let client = instellingen.client {
                OmslagView(url: client.omslagURL(serie: serie.id), titel: serie.title)
            }
            Text(serie.title)
                .font(.caption)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text("\(serie.bookCount) delen")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        // Het tikgebied is de tegel en niets daarbuiten. Anders bepaalt de
        // grootste omslag hoe ver de knop reikt.
        .contentShape(Rectangle())
    }

    private func start() async {
        guard let client = instellingen.client else {
            fout = ClientFout.geenAdres.localizedDescription
            return
        }
        // Tabs en mappen zijn zelden anders; één keer per keer openen volstaat.
        async let opgehaaldeTabs = try? client.tabs()
        async let opgehaaldeRoots = try? client.roots()
        tabs = await opgehaaldeTabs ?? []
        roots = await opgehaaldeRoots ?? []
        await haal()
    }

    private func haal() async {
        laadt = true
        defer { laadt = false }

        guard let client = instellingen.client else {
            let sleutel = "series-\(filter.groep.rawValue)-\(sortering.rawValue)-\(zoek)"
            let bewaard = Bibliotheekcache.lees(Paginated<Series>.self, sleutel: sleutel)
            let aanwezig = await Paginacache.gedeeld.seriesMetInhoud()
            series = (bewaard?.items ?? []).filter { aanwezig.contains($0.id) }
            vanCache = true
            fout = series.isEmpty
                ? "Er staan nog geen pagina's van deze categorie op dit toestel."
                : nil
            return
        }
        // Een tab compileert op de server naar een query; die kunnen we
        // zonder NAS niet nabouwen, dus de terugval geldt alleen als er geen
        // tab gekozen is. Een gekozen tab zonder NAS toont dan niet ten
        // onrechte de vorige "Alles"-lijst alsof hij bij de tab hoort.
        let resultaat: Paginated<Series>?
        let terugval: Bool
        if let tab = filter.tabID {
            resultaat = try? await client.tabSeries(tab, groep: filter.groep, zoek: zoek)
            terugval = false
        } else {
            let sleutel = "series-\(filter.groep.rawValue)-\(sortering.rawValue)-\(zoek)"
            (resultaat, terugval) = await Bibliotheekcache.metTerugval(sleutel: sleutel) {
                try await client.series(filter: filter, zoek: zoek, sortering: sortering)
            }
        }
        vanCache = terugval || instellingen.alleenOffline
        if let resultaat {
            series = resultaat.items
            if instellingen.alleenOffline {
                // Alleen wat je hier ook echt kunt openen. Een lijst met
                // series die bij het aantikken een grijze tegel opleveren is
                // erger dan een korte lijst.
                let aanwezig = await Paginacache.gedeeld.seriesMetInhoud()
                series = series.filter { aanwezig.contains($0.id) }
            }
            fout = nil
        } else if series.isEmpty {
            fout = ClientFout.netwerk(URLError(.notConnectedToInternet)).localizedDescription
        }
    }
}
