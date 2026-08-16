import SwiftUI

struct InstellingenView: View {
    @Environment(Instellingen.self) private var instellingen
    @Environment(\.dismiss) private var sluit

    @State private var proef: String?
    @State private var proeftLopend = false
    @State private var gezondheid: ServerHealth?
    @State private var profielen: [Beeldprofiel] = []
    @State private var vertaal: Vertaalinstellingen?
    @State private var roots: [LibraryRoot] = []
    @State private var opslag: String = "…"
    @State private var paginaOpslag: String = "…"
    @State private var eigenSleutel: String = ""
    @State private var sleutelBewaard = false
    private var prioriteiten: Prioriteiten { Prioriteiten.gedeeld }
    private var sync: SidecarSync { SidecarSync.gedeeld }

    // De leesstanden staan ook in de lezer zelf; hier voor wie ze vooraf wil
    // zetten in plaats van tijdens het lezen te zoeken.
    @AppStorage("reader.viewMode") private var weergaveRuw = Weergavestand.paginas.rawValue
    @AppStorage("reader.fit") private var passendRuw = Passend.scherm.rawValue
    @AppStorage("reader.doublePage") private var dubbel = false
    @AppStorage("reader.crop") private var bijsnijden = false
    @AppStorage("reader.contrast") private var contrast = 100

    var body: some View {
        @Bindable var instellingen = instellingen
        NavigationStack {
            Form {
                serverSectie($instellingen.adres)
                if let gezondheid { serverInfo(gezondheid) }
                beeldSectie
                lezenSectie
                vertaalSectie
                offlineSectie
                sleutelSectie
                opslagSectie
                bronnenSectie
            }
            .navigationTitle("Instellingen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Klaar") { sluit() }
                }
            }
            .task { await haal() }
        }
    }

    // MARK: - Secties

    private func serverSectie(_ adres: Binding<String>) -> some View {
        Section {
            TextField("http://192.168.68.98:1997", text: adres)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
            Button {
                Task { await proefVerbinding() }
            } label: {
                HStack {
                    Text("Verbinding testen")
                    if proeftLopend {
                        Spacer()
                        ProgressView()
                    }
                }
            }
            .disabled(proeftLopend)
            if let proef {
                Text(proef).font(.callout).foregroundStyle(.secondary)
            }
        } header: {
            Text("Server")
        } footer: {
            Text("Het adres van BookPal op je NAS, zoals je het ook in de browser intikt.")
        }
    }

    private func serverInfo(_ gezond: ServerHealth) -> some View {
        Section("Op de server") {
            LabeledContent("Versie", value: gezond.version)
            LabeledContent("Series", value: "\(gezond.series)")
            LabeledContent("Boeken", value: "\(gezond.books)")
            if !roots.isEmpty {
                LabeledContent("Mappen", value: roots.filter(\.enabled).map(\.naam)
                    .joined(separator: ", "))
            }
        }
    }

    private var beeldSectie: some View {
        Section {
            Picker("Beeldprofiel", selection: Binding(
                get: { instellingen.profiel },
                set: { instellingen.profiel = $0 }
            )) {
                ForEach(profielen.filter { !$0.name.hasPrefix("kobo") }) { profiel in
                    Text(omschrijving(profiel)).tag(profiel.name)
                }
            }
            .disabled(profielen.isEmpty)
        } header: {
            Text("Beeld")
        } footer: {
            Text(
                "Waarin pagina's binnenkomen. De server schaalt niet op, dus een groter "
                    + "profiel geeft alleen meer als de scan zelf groter is. "
                    + "De Kobo-profielen staan er niet bij: die zijn grijs en op paneelmaat."
            )
        }
    }

    private var lezenSectie: some View {
        Section {
            Picker("Weergave", selection: $weergaveRuw) {
                ForEach(Weergavestand.allCases) { Text($0.naam).tag($0.rawValue) }
            }
            Picker("Passend maken", selection: $passendRuw) {
                ForEach(Passend.allCases) { Text($0.naam).tag($0.rawValue) }
            }
            Toggle("Dubbele pagina's", isOn: $dubbel)
            Toggle("Bijsnijden", isOn: $bijsnijden)
            Toggle("Contrast oprekken", isOn: Binding(
                get: { contrast > 100 },
                set: { contrast = $0 ? 140 : 100 }
            ))
        } header: {
            Text("Lezen")
        } footer: {
            Text("Dezelfde standen als het tandwiel in de lezer; hier vooraf in te stellen.")
        }
    }

    @ViewBuilder
    private var vertaalSectie: some View {
        if let vertaal {
            Section {
                LabeledContent("Vanzelf", value: Vertaalinstellingen.naam(vertaal.mode))
                LabeledContent("Knop in de lezer", value: Vertaalinstellingen.naam(vertaal.buttonMode))
                LabeledContent("Inkleuren", value: Vertaalinstellingen.naam(vertaal.colourMode))
                ForEach(vertaal.costs.sorted(by: { $0.key < $1.key }), id: \.key) { stand, prijs in
                    LabeledContent(
                        Vertaalinstellingen.naam(stand),
                        value: prijs.formatted(.currency(code: "USD")) + " / pagina"
                    )
                    .font(.caption)
                }
            } header: {
                Text("Vertalen en inkleuren")
            } footer: {
                Text(
                    "De standen zelf zet je om in de web-app; hier staan ze ter informatie, "
                        + "met de prijs per pagina. Zélf laten vertalen of inkleuren kan wel: "
                        + "het toverstafje in de leesbalk, en dat noemt altijd eerst het bedrag."
                )
            }
        }
    }

    /// Hoeveel ruimte offline lezen mag innemen, en wat er nu in zit.
    private var offlineSectie: some View {
        Section {
            LabeledContent("Pagina's op dit toestel", value: paginaOpslag)
            VStack(alignment: .leading) {
                Text("Ruimte: \(prioriteiten.limietMB) MB")
                Slider(
                    value: Binding(
                        get: { Double(prioriteiten.limietMB) },
                        set: { prioriteiten.limietMB = Int($0) }
                    ),
                    in: 250...10000,
                    step: 250
                )
            }
            Button("Offline pagina's wissen", role: .destructive) {
                Task {
                    await Paginacache.gedeeld.maakLeeg()
                    paginaOpslag = await omvangTekst()
                }
            }

            Button {
                Task {
                    if let client = instellingen.client { await sync.synchroniseer(client) }
                }
            } label: {
                HStack {
                    Label("Nu synchroniseren", systemImage: "arrow.triangle.2.circlepath")
                    if sync.bezig { Spacer(); ProgressView() }
                }
            }
            .disabled(sync.bezig)
            if let verslag = sync.laatsteVerslag {
                Text(verslag).font(.caption).foregroundStyle(.secondary)
            }
        } header: {
            Text("Offline lezen")
        } footer: {
            Text(
                "Wat je leest blijft op je toestel staan, zodat het ook zonder NAS opengaat. "
                    + "Raakt de ruimte vol, dan gaat het langst ongelezene het eerst weg — "
                    + "behalve series met «Offline bewaren» aan en alles wat van een abonnement "
                    + "komt. Synchroniseren haalt alle vertalingen van de NAS en stuurt terug "
                    + "wat je onderweg zelf hebt laten maken."
            )
        }
    }

    /// De eigen Gemini-sleutel, voor vertalen zonder NAS.
    private var sleutelSectie: some View {
        Section {
            SecureField("AIza…", text: $eigenSleutel)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button(eigenSleutel.isEmpty ? "Sleutel wissen" : "Sleutel bewaren") {
                Sleutelketen.bewaar(eigenSleutel)
                sleutelBewaard = !eigenSleutel.isEmpty
            }
            if sleutelBewaard {
                Label("Bewaard in de sleutelhanger", systemImage: "checkmark.circle")
                    .font(.caption)
                    .foregroundStyle(.green)
            }
        } header: {
            Text("Eigen Gemini-sleutel")
        } footer: {
            Text(
                "Alleen nodig om onderweg te vertalen of in te kleuren zonder NAS — mét "
                    + "internet, maar buiten je netwerk. Elke pagina kost dan hetzelfde als op "
                    + "de NAS, en wordt van je eigen Google-account afgeschreven. De sleutel "
                    + "staat in de sleutelhanger van dit toestel en gaat niet mee in een "
                    + "iCloud-back-up. Zonder sleutel werkt alles behalve dít gewoon door."
            )
        }
    }

    private var opslagSectie: some View {
        Section {
            LabeledContent("Opgehaalde epubs", value: opslag)
            Button("Opslag leegmaken", role: .destructive) {
                EpubOpslag.maakLeeg()
                Task { opslag = EpubOpslag.omvang() }
            }
        } header: {
            Text("Op dit toestel")
        } footer: {
            Text(
                "Een epub die je opent wordt bewaard, zodat hij zonder NAS opnieuw opengaat. "
                    + "Weggooien kan altijd; hij komt terug zodra je hem weer opent."
            )
        }
    }

    private var bronnenSectie: some View {
        Section {
            NavigationLink {
                BronnenView()
            } label: {
                Label("Bronnen", systemImage: "antenna.radiowaves.left.and.right")
            }
            NavigationLink {
                TrackersView()
            } label: {
                Label("Trackers", systemImage: "list.bullet.rectangle")
            }
        } header: {
            Text("Volgen en bijhouden")
        } footer: {
            Text(
                "Bij een bron zoek je reeksen en volg je ze; een tracker houdt je leeslijst "
                    + "buiten BookPal bij. Het kóppelen van een tracker doe je in de web-app — "
                    + "dat is eenmalig werk met een client-id en een autorisatiecode."
            )
        }
    }

    // MARK: - Gedrag

    private func omschrijving(_ profiel: Beeldprofiel) -> String {
        if let breedte = profiel.maxWidth {
            return "\(profiel.name) — \(breedte)px \(profiel.format)"
        }
        return "\(profiel.name) — \(profiel.format)"
    }

    private func omvangTekst() async -> String {
        let bytes = await Paginacache.gedeeld.omvang
        guard bytes > 0 else { return "niets" }
        return ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }

    private func haal() async {
        opslag = EpubOpslag.omvang()
        paginaOpslag = await omvangTekst()
        sleutelBewaard = Sleutelketen.lees()?.isEmpty == false
        guard let client = instellingen.client else { return }
        async let g = try? client.gezondheid()
        async let p = try? client.profielen()
        async let v = try? client.vertaalinstellingen()
        async let r = try? client.roots()
        gezondheid = await g
        profielen = await p ?? []
        vertaal = await v
        roots = await r ?? []
    }

    private func proefVerbinding() async {
        guard let client = instellingen.client else {
            proef = ClientFout.geenAdres.localizedDescription
            return
        }
        proeftLopend = true
        defer { proeftLopend = false }
        do {
            let gezond = try await client.gezondheid()
            gezondheid = gezond
            proef = "Verbonden met versie \(gezond.version): \(gezond.series) series, \(gezond.books) boeken."
        } catch {
            proef = error.localizedDescription
        }
    }
}
