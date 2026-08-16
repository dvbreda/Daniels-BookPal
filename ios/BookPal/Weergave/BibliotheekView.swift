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
        HStack(spacing: 8) {
            ForEach(Soortfilter.allCases) { keuze in
                chip(naam: keuze.naam, icoon: nil, actief: filter.groep == keuze) {
                    filter.groep = keuze
                }
            }
            Spacer()
        }
        .padding(.horizontal)
        .padding(.bottom, 8)
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
        guard let client = instellingen.client else {
            fout = ClientFout.geenAdres.localizedDescription
            return
        }
        laadt = true
        defer { laadt = false }
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
            let sleutel = "series-\(filter.groep.rawValue)-\(zoek)"
            (resultaat, terugval) = await Bibliotheekcache.metTerugval(sleutel: sleutel) {
                try await client.series(filter: filter, zoek: zoek)
            }
        }
        vanCache = terugval
        if let resultaat {
            series = resultaat.items
            fout = nil
        } else if series.isEmpty {
            fout = ClientFout.netwerk(URLError(.notConnectedToInternet)).localizedDescription
        }
    }
}
