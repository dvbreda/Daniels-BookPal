import SwiftUI

struct LezerView: View {
    let boek: Book

    @Environment(Instellingen.self) private var instellingen
    @Environment(\.dismiss) private var sluit

    @State private var lader: Beeldlader?
    @State private var spreadIndex = 0
    @State private var toontBalk = true
    @State private var toontInstellingen = false
    @State private var toontMaken = false
    @State private var bewaartaak: Task<Void, Never>?

    // Standen, bewaard tussen sessies. Dezelfde sleutels als de web-lezer
    // gebruikt, zodat de twee dezelfde begrippen hanteren.
    @AppStorage("reader.viewMode") private var weergaveRuw = Weergavestand.paginas.rawValue
    @AppStorage("reader.doublePage") private var dubbel = false
    @AppStorage("reader.fit") private var passendRuw = Passend.scherm.rawValue
    @AppStorage("reader.gridRows") private var rasterRijen = 0
    @AppStorage("reader.gridCols") private var rasterKolommen = 0
    @AppStorage("reader.crop") private var bijsnijden = false
    @AppStorage("reader.contrast") private var contrast = 100
    /// Lucht rondom een paneel, als deel van de paginabreedte. Nul betekent
    /// strak op het paneel; wat marge laat je zien waar het op de pagina staat.
    @AppStorage("reader.panelMargin") private var paneelmarge = 0.03
    /// Standaard aan: als er voor een pagina betaald is, wil je die zien.
    ///
    /// Kost niets op een onvertaalde serie — `Paginakeuze.kies` valt terug op
    /// het origineel zodra er geen hertekende pagina klaarligt, en die
    /// wetenschap komt uit een verzoek dat de lezer toch al doet.
    @AppStorage("reader.translated") private var vertaling = true
    @AppStorage("reader.colour") private var kleurAan = false
    @State private var rechtsNaarLinks: Bool

    // Wat er per pagina klaarligt.
    @State private var vertalingen: [Int: PageTranslation] = [:]
    @State private var kleuren: [Int: ColourInfo] = [:]
    @State private var origineelVan: Bubble?

    // Ingezoomd hoort bladeren uit te staan, anders schiet je naar de volgende
    // pagina terwijl je binnen deze wilt slepen.
    @State private var ingezoomd = false
    @State private var rastercel = 0

    // Panelenstand: waar je bent, en waar de panelen zitten.
    @State private var paneelbron: Paneelbron?
    @State private var paneelpad = Paneelpad(pagina: 0, paneel: 0)
    /// Waar de volgende weergave moet beginnen. Bij een standwissel is dat waar
    /// je stónd — niet je opgeslagen voortgang, want die loopt achter op waar je
    /// nu leest.
    @State private var startpagina = 0
    /// Of de doorlopende weergave al naar `startpagina` gesprongen is. Tot dat
    /// moment mag de eerste strook zijn `onAppear` niet als "hier ben ik" laten
    /// tellen: een `LazyVStack` bouwt vanaf nul op, dus die meldt pagina 1 nog
    /// voordat er gescrold is — en bewaart die dan ook.
    @State private var doorlopendGeplaatst = false

    // Het volgende hoofdstuk, om aan te bieden als je aan het eind bent.
    @State private var volgendAanbod: VolgendHoofdstuk?
    @State private var volgendBoek: Book?
    @State private var aanbodWeg = false

    init(boek: Book) {
        self.boek = boek
        _rechtsNaarLinks = State(initialValue: boek.rightToLeft)
    }

    private var weergave: Weergavestand {
        get { Weergavestand(rawValue: weergaveRuw) ?? .paginas }
        nonmutating set { weergaveRuw = newValue.rawValue }
    }

    private var passend: Passend {
        get { Passend(rawValue: passendRuw) ?? .scherm }
        nonmutating set { passendRuw = newValue.rawValue }
    }

    private var paginas: Int { boek.pageCount ?? 0 }
    private var taal: String { instellingen.taal }
    private var rastervorm: Rastervorm {
        get { Rastervorm(rijen: rasterRijen, kolommen: rasterKolommen) }
        nonmutating set {
            rasterRijen = newValue.rijen
            rasterKolommen = newValue.kolommen
            rastercel = 0
        }
    }

    private var rasterAan: Bool { rastervorm.cellen > 0 && weergave == .paginas }

    private var spreads: [[Int]] {
        Spreads.bouw(
            paginas: paginas,
            // Bij rasterzoom kijk je naar een deel van één pagina; twee naast
            // elkaar zou de cellen halveren.
            dubbel: dubbel && !rasterAan,
            verhoudingen: lader?.verhoudingen ?? [:]
        )
    }

    private var huidigePagina: Int { paginaIn(weergave) }

    /// Op welke pagina een bepáálde stand staat.
    ///
    /// Met de stand als argument en niet impliciet, want bij een standwissel
    /// moet je hem uitlezen vóórdat hij omgaat — daarna wijst hij naar de
    /// nieuwe stand, die nog nergens staat.
    private func paginaIn(_ stand: Weergavestand) -> Int {
        if stand == .panelen { return paneelpad.pagina }
        guard spreads.indices.contains(spreadIndex) else { return 0 }
        return spreads[spreadIndex].first ?? 0
    }

    private func keuze(voor index: Int) -> Paginakeuze {
        Paginakeuze.kies(
            vertaling: vertaling,
            kleurAan: kleurAan,
            heeftHertekend: vertalingen[index]?.fullPage ?? false,
            kleur: kleuren[index],
            taal: taal
        )
    }

    private func ballonnen(voor index: Int) -> [Bubble] {
        guard vertaling, keuze(voor: index).tekentBallonnen else { return [] }
        return vertalingen[index]?.bubbles ?? []
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if let lader {
                switch weergave {
                case .doorlopend: doorlopend(lader)
                case .panelen: panelenstand(lader)
                case .paginas: pager(lader)
                }
            } else {
                ProgressView().tint(.white)
            }
            if toontBalk { balk }
            if toontAanbod, let volgendAanbod { aanbod(volgendAanbod) }
        }
        .navigationBarBackButtonHidden(true)
        .toolbar(.hidden, for: .navigationBar)
        // Weg met de tabbalk: hier lees je, en dan is elke pixel onderin
        // strip in plaats van navigatie.
        .toolbar(.hidden, for: .tabBar)
        .statusBarHidden(!toontBalk)
        .sheet(item: $origineelVan) { OrigineelSheet(bubble: $0).presentationDetents([.medium]) }
        .sheet(isPresented: $toontMaken) {
            MaakSheet(
                boek: boek,
                pagina: huidigePagina,
                taal: taal,
                vertaling: vertalingen[huidigePagina],
                kleur: kleuren[huidigePagina],
                opVernieuwd: { vernieuwPagina(huidigePagina) }
            )
        }
        .sheet(isPresented: $toontInstellingen) {
            LezerInstellingenSheet(
                weergave: Binding(get: { weergave }, set: { weergave = $0 }),
                dubbel: $dubbel,
                passend: Binding(get: { passend }, set: { passend = $0 }),
                rastervorm: Binding(get: { rastervorm }, set: { rastervorm = $0 }),
                bijsnijden: $bijsnijden,
                contrast: $contrast,
                rechtsNaarLinks: $rechtsNaarLinks,
                paneelmarge: $paneelmarge
            )
        }
        .task { start() }
        .task { volgendAanbod = try? await instellingen.client?.volgendHoofdstuk(boek: boek.id) }
        // Eén plek waar je plek meeverhuist, wélke weg de wissel ook loopt:
        // dubbeltik, de knop in de balk, of de keuze in de instellingen.
        .onChange(of: weergaveRuw) { oud, nieuw in
            guard let van = Weergavestand(rawValue: oud),
                  let naar = Weergavestand(rawValue: nieuw)
            else { return }
            verhuis(van: van, naar: naar)
        }
        .onChange(of: huidigePagina) { _, _ in aanbodWeg = false }
        .navigationDestination(item: $volgendBoek) { boek in
            LezerView(boek: boek)
        }
        .onChange(of: bijsnijden) { _, _ in pasBewerkingToe() }
        .onChange(of: contrast) { _, _ in pasBewerkingToe() }
        .onDisappear {
            bewaartaak?.cancel()
            let pagina = huidigePagina
            let percent = Spreads.percentVoor(spreads, spreadIndex: spreadIndex, paginas: paginas)
            Task { await bewaar(pagina: pagina, percent: percent) }
            // Hier en niet bij elke pagina: dit is bestandswerk, en je sluit
            // een boek veel minder vaak dan je bladert.
            let prioriteiten = Prioriteiten.gedeeld
            Task {
                await Paginacache.gedeeld.ruimOpIndienNodig(
                    limiet: prioriteiten.limietBytes,
                    prioriteitSeries: prioriteiten.eigenGekozen,
                    beschermdeBoeken: prioriteiten.beschermdeBoeken
                )
            }
        }
    }

    // MARK: - Bladeren

    /// Bladeren met een ScrollView en niet met `TabView(.page)`, omdat alleen
    /// deze `scrollDisabled` kent. Dat is precies wat er nodig is: zodra je
    /// inzoomt gaat het bladeren uit en sleep je binnen de plaat.
    private func pager(_ lader: Beeldlader) -> some View {
        ScrollView(.horizontal) {
            LazyHStack(spacing: 0) {
                ForEach(Array(spreads.enumerated()), id: \.offset) { index, spread in
                    spreadView(spread, lader: lader)
                        .containerRelativeFrame(.horizontal)
                        .id(index)
                }
            }
            .scrollTargetLayout()
        }
        .scrollTargetBehavior(.paging)
        .scrollIndicators(.hidden)
        .scrollDisabled(ingezoomd)
        .scrollPosition(id: Binding(get: { spreadIndex }, set: { spreadIndex = $0 ?? spreadIndex }))
        // Rechts-naar-links via de leesrichting van het systeem, zodat de
        // pagina-indexen blijven wat ze zijn.
        .environment(\.layoutDirection, rechtsNaarLinks ? .rightToLeft : .leftToRight)
        .ignoresSafeArea()
        .onChange(of: spreadIndex) { _, _ in
            rastercel = 0
            laadRondom(lader)
            planBewaren()
        }
        .onChange(of: vertaling) { _, _ in laadRondom(lader) }
        .onChange(of: kleurAan) { _, _ in laadRondom(lader) }
    }

    private func spreadView(_ spread: [Int], lader: Beeldlader) -> some View {
        let volgorde = Spreads.volgordeVoorScherm(spread, rechtsNaarLinks: rechtsNaarLinks)
        return HStack(spacing: 0) {
            ForEach(volgorde, id: \.self) { index in
                PaginaView(
                    index: index,
                    keuze: keuze(voor: index),
                    ballonnen: ballonnen(voor: index),
                    lader: lader,
                    passend: passend,
                    ingezoomd: $ingezoomd,
                    raster: rasterAan
                        ? Rasterstand(
                            rijen: rastervorm.rijen,
                            kolommen: rastervorm.kolommen,
                            cel: rastercel,
                            rechtsNaarLinks: rechtsNaarLinks
                        )
                        : nil,
                    origineelVan: $origineelVan,
                    opTik: { x in tik(op: x) },
                    opDubbeltik: { wisselStand() }
                )
            }
        }
        .environment(\.layoutDirection, .leftToRight)
    }

    // MARK: - Doorlopend

    /// Doorlopende verticale weergave, voor webtoons — daar zijn "pagina's"
    /// stroken die aan elkaar horen te zitten, en elke witruimte ertussen is een
    /// naad die er in het origineel niet is.
    private func doorlopend(_ lader: Beeldlader) -> some View {
        ScrollViewReader { scroll in
            ScrollView(.vertical) {
                LazyVStack(spacing: 0) {
                    ForEach(0..<max(paginas, 0), id: \.self) { index in
                        StrookView(
                            index: index,
                            keuze: keuze(voor: index),
                            ballonnen: ballonnen(voor: index),
                            lader: lader,
                            origineelVan: $origineelVan
                        )
                        .id(index)
                        .onAppear {
                            Task { await haalMerkjes(index) }
                            lader.laadVooruit(
                                (index + 1...index + 3).filter { $0 < paginas }
                            )
                            // Pas meetellen als we op onze plek staan — zie
                            // `doorlopendGeplaatst`.
                            guard doorlopendGeplaatst else { return }
                            spreadIndex = Spreads.spreadVanPagina(spreads, pagina: index)
                            planBewaren()
                        }
                    }
                }
            }
            .scrollIndicators(.hidden)
            .ignoresSafeArea()
            .onTapGesture(count: 2) { wisselStand() }
            .onTapGesture { withAnimation { toontBalk.toggle() } }
            .task {
                // Naar je plek springen vóór alles: anders begint de
                // doorlopende weergave bovenaan en meldt de eerste strook
                // meteen pagina 1 terug — dan ben je je plek kwijt bij elke
                // moduswissel.
                //
                // `startpagina` en niet je opgeslagen voortgang: die is van
                // toen je het boek opende en loopt dus achter op waar je nu
                // staat. Precies dáárom kwam je na een wissel op pagina 1 uit.
                let start = startpagina
                if start > 0 {
                    try? await Task.sleep(for: .milliseconds(120))
                    scroll.scrollTo(start, anchor: .top)
                }
                doorlopendGeplaatst = true
            }
        }
    }

    /// Een tik, afhankelijk van waar je tikt: links terug, rechts verder,
    /// midden de balk. Bij manga zijn links en rechts omgedraaid — zie
    /// `Tikzone`.
    private func tik(op x: Double) {
        // In de panelenstand altijd westers: rechts is verder, ook bij manga.
        // De vólgorde van de panelen volgt wél de leesrichting — je krijgt dus
        // de goede panelen in de goede volgorde — maar welke kant je tikt is
        // een gewoonte van je duim, niet van het boek. Als Europeaan verwacht je
        // rechts vooruit, en dat blijkt sterker dan de leesrichting van de pagina.
        let gespiegeld = weergave == .panelen ? false : rechtsNaarLinks
        switch Tikzone.voor(x: x, rechtsNaarLinks: gespiegeld) {
        case .balk:
            withAnimation { toontBalk.toggle() }
        case .volgende:
            sluitBalk()
            volgende()
        case .vorige:
            sluitBalk()
            vorige()
        }
    }

    /// De balken weg zodra je verder bladert.
    ///
    /// Ze liggen over de strip heen, dus zolang ze open staan dekken ze de
    /// bovenste en onderste stroken van de volgende pagina af. Wie doorbladert
    /// is klaar met het menu — dat is precies wat de tik zegt.
    private func sluitBalk() {
        guard toontBalk else { return }
        withAnimation { toontBalk = false }
    }

    private func volgende() {
        if weergave == .panelen {
            if let pad = paneelpad.volgende(aantal: aantalPanelen, paginas: paginas) {
                withAnimation(.easeInOut(duration: 0.22)) { paneelpad = pad }
            }
            return
        }
        if rasterAan, rastercel + 1 < rastervorm.cellen {
            withAnimation(.easeInOut(duration: 0.2)) { rastercel += 1 }
            return
        }
        guard spreadIndex + 1 < spreads.count else { return }
        withAnimation { spreadIndex += 1 }
    }

    private func vorige() {
        if weergave == .panelen {
            if let pad = paneelpad.vorige(aantal: aantalPanelen) {
                withAnimation(.easeInOut(duration: 0.22)) { paneelpad = pad }
            }
            return
        }
        if rasterAan, rastercel > 0 {
            withAnimation(.easeInOut(duration: 0.2)) { rastercel -= 1 }
            return
        }
        guard spreadIndex > 0 else { return }
        withAnimation {
            spreadIndex -= 1
            // Terugbladeren hoort onderaan de vorige pagina te beginnen, niet
            // bovenaan: je leest hem immers achterstevoren in.
            rastercel = rasterAan ? rastervorm.cellen - 1 : 0
        }
    }

    // MARK: - Panelen

    /// Paneel voor paneel, op ware grootte. Links en rechts tikken wisselt van
    /// paneel — heen en terug, en over de paginagrens heen.
    private func panelenstand(_ lader: Beeldlader) -> some View {
        GeometryReader { maat in
            ZStack {
                PaneelView(
                    index: paneelpad.pagina,
                    paneel: huidigPaneel,
                    keuze: keuze(voor: paneelpad.pagina),
                    ballonnen: ballonnen(voor: paneelpad.pagina),
                    lader: lader,
                    kader: maat.size,
                    marge: paneelmarge,
                    origineelVan: $origineelVan
                )
            }
            .frame(width: maat.size.width, height: maat.size.height)
            .contentShape(Rectangle())
            .onTapGesture(count: 2) { _ in wisselStand() }
            .onTapGesture { plek in
                tik(op: maat.size.width > 0 ? plek.x / maat.size.width : 0.5)
            }
        }
        .ignoresSafeArea()
        .task(id: paneelpad.pagina) { await bereidPanelenVoor() }
    }

    private var tellertekst: String {
        let basis = "pagina \(huidigePagina + 1) van \(paginas)"
        guard weergave == .panelen else { return basis }
        let aantal = aantalPanelen(paneelpad.pagina)
        if aantal <= 1 { return basis + " · hele plaat" }
        if paneelpad.isOverzicht { return basis + " · overzicht (\(aantal) panelen)" }
        return basis + " · paneel \(paneelpad.paneel + 1) van \(aantal)"
    }

    private var huidigPaneel: Paneel {
        // Het overzicht is de hele pagina; daarna pas de losse panelen.
        guard !paneelpad.isOverzicht else { return .helePagina }
        let panelen = paneelbron?.panelen(paneelpad.pagina) ?? [Paneel.helePagina]
        guard panelen.indices.contains(paneelpad.paneel) else { return .helePagina }
        return panelen[paneelpad.paneel]
    }

    private func aantalPanelen(_ pagina: Int) -> Int {
        max(1, paneelbron?.panelen(pagina).count ?? 1)
    }

    /// Deze pagina onderzoeken en de volgende alvast, zodat een tik naar de
    /// volgende pagina niet op een lege stand uitkomt.
    private func bereidPanelenVoor() async {
        guard let bron = paneelbron, let lader else { return }
        for index in [paneelpad.pagina, paneelpad.pagina + 1] where index < paginas {
            var beeld = lader.klaarstaand(index, keuze: keuze(voor: index))
            if beeld == nil { beeld = await lader.laad(index, keuze: keuze(voor: index)) }
            await bron.onderzoek(index, beeld: beeld)
        }
        // De voortgang volgt de pagina waar je in zit.
        spreadIndex = Spreads.spreadVanPagina(spreads, pagina: paneelpad.pagina)
        planBewaren()
    }

    /// Dubbeltikken op de pagina: heen en weer tussen paneelzoom en
    /// doorlopend. Op een tekstballon telt de dubbeltik niet mee — die opent
    /// daar het origineel, en dat gebaar hoort bij de ballon.
    ///
    /// Je plek meenemen gebeurt niet hier maar in `verhuis(van:naar:)`, zodat
    /// het ook geldt voor de knop in de balk en de keuze in de instellingen.
    private func wisselStand() {
        withAnimation(.easeInOut(duration: 0.25)) {
            weergave = weergave.naDubbeltik
        }
    }

    /// Je plek meenemen naar de nieuwe stand.
    ///
    /// De drie standen tellen ieder hun eigen plek: de pagina- en doorlopende
    /// stand via `spreadIndex`, de panelenstand via `paneelpad`. Wisselen zonder
    /// over te zetten laat de nieuwe stand staan waar hij de vorige keer was —
    /// en dat was bij een vers geopend boek pagina 1.
    private func verhuis(van oud: Weergavestand, naar nieuw: Weergavestand) {
        let hier = paginaIn(oud)
        startpagina = hier
        switch nieuw {
        case .panelen:
            // Op het overzicht en niet in paneel 1: eerst zien wat de pagina
            // is, dan pas inzoomen.
            paneelpad = Paneelpad(pagina: hier, paneel: Paneelpad.overzicht)
        case .paginas:
            spreadIndex = Spreads.spreadVanPagina(spreads, pagina: hier)
        case .doorlopend:
            spreadIndex = Spreads.spreadVanPagina(spreads, pagina: hier)
            // De doorlopende weergave is net opgebouwd en staat bovenaan; zijn
            // eigen `task` scrollt naar `startpagina` zodra hij er is.
            doorlopendGeplaatst = false
        }
    }

    /// Ben je aan het eind? Dan het volgende hoofdstuk aanbieden.
    ///
    /// Aanbieden en niet automatisch doorschuiven: doorlezen is een keuze, en
    /// ongevraagd in een volgend hoofdstuk belanden is precies hoe je je plek
    /// kwijtraakt.
    private var toontAanbod: Bool {
        !aanbodWeg && paginas > 0 && huidigePagina >= paginas - 1 && volgendAanbod != nil
    }

    private func aanbod(_ volgende: VolgendHoofdstuk) -> some View {
        VStack {
            Spacer()
            VStack(spacing: 10) {
                Text("Uit. Verder met:").font(.caption).foregroundStyle(.secondary)
                Text(volgende.label)
                    .font(.headline)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                HStack(spacing: 12) {
                    Button("Later") { aanbodWeg = true }
                        .buttonStyle(.bordered)
                    Button(volgende.hasFile ? "Lezen" : "Niet opgehaald") {
                        Task { await openVolgende(volgende) }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!volgende.hasFile)
                }
            }
            .padding()
            .frame(maxWidth: 320)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
            .padding(.bottom, 120)
        }
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    private func openVolgende(_ volgende: VolgendHoofdstuk) async {
        guard let client = instellingen.client else { return }
        // Het hele boek ophalen: de lezer heeft leesrichting, paginacount en
        // voortgang nodig, en die zitten niet in het aanbod.
        volgendBoek = try? await client.boek(volgende.bookID)
    }

    // MARK: - Balk

    private var balk: some View {
        VStack {
            HStack(spacing: 22) {
                Button { sluit() } label: { Label("Terug", systemImage: "chevron.left") }
                Spacer()
                knoppen
            }
            .labelStyle(.iconOnly)
            .font(.title3)
            .padding(.horizontal)
            .padding(.vertical, 10)
            .background(.ultraThinMaterial)

            Spacer()

            VStack(spacing: 6) {
                if paginas > 1 && weergave == .paginas {
                    // Door een hoofdstuk springen zonder honderd keer te vegen.
                    Slider(
                        value: Binding(
                            get: { Double(huidigePagina) },
                            set: { nieuw in
                                spreadIndex = Spreads.spreadVanPagina(
                                    spreads, pagina: Int(nieuw.rounded())
                                )
                            }
                        ),
                        in: 0...Double(paginas - 1),
                        step: 1
                    )
                    .padding(.horizontal)
                    .accessibilityLabel("Pagina kiezen")
                }
                // De merkjes staan los van de knoppen: die zeggen wat er gebeurt
                // als je drukt, deze zeggen wat er ligt.
                Merkjes(
                    vertaling: vertalingen[huidigePagina],
                    kleur: kleuren[huidigePagina]
                )
                Text(boek.label).font(.caption).lineLimit(1)
                // In de panelenstand ook wáár in de pagina je bent. Dat is
                // niet alleen oriëntatie: het aantal zegt meteen of de detectie
                // op deze pagina iets zinnigs heeft gevonden of terugviel op de
                // hele plaat.
                Text(tellertekst)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("paginateller")
            }
            .padding(8)
            .frame(maxWidth: .infinity)
            .background(.ultraThinMaterial)
        }
        .transition(.opacity)
    }

    @ViewBuilder
    private var knoppen: some View {
        // Bewust niet uitgrijzen als deze pagina niets heeft: dit zijn
        // voorkeuren voor het hele boek, niet per pagina. Een pagina zonder
        // vertaling of kleur valt vanzelf terug op het origineel — net als in de
        // web-lezer. Wat er wél ligt staat in de merkjes onderin.
        Button {
            weergave = weergave.volgende
        } label: {
            // Vaste naam, niet de stand zelf: anders heet deze knop soms
            // "Doorlopend" en botst hij met de keuze in het weergavepaneel.
            Label("Weergavestand", systemImage: weergave.icoon)
        }

        Button {
            rastervorm = Rastervorm.volgende(na: rastervorm)
        } label: {
            Label(
                rasterAan ? "Raster \(rastervorm.naam)" : "Raster",
                systemImage: rasterAan ? "square.grid.2x2.fill" : "square.grid.2x2"
            )
        }
        .accessibilityValue(rasterAan ? rastervorm.naam : "uit")

        Button {
            vertaling.toggle()
        } label: {
            Label("Vertaling", systemImage: vertaling ? "character.bubble.fill" : "character.bubble")
        }
        // Of hij aan staat is aan het icoon te zien, maar niet te horen — en
        // niet af te lezen door iets dat de app van buitenaf bestuurt.
        .accessibilityValue(vertaling ? "aan" : "uit")

        Button {
            kleurAan.toggle()
        } label: {
            Label("Kleur", systemImage: kleurAan ? "paintpalette.fill" : "paintpalette")
        }
        .accessibilityValue(kleurAan ? "aan" : "uit")

        Button {
            toontMaken = true
        } label: {
            Label("Laten maken", systemImage: "wand.and.sparkles")
        }

        Button {
            toontInstellingen = true
        } label: {
            Label("Weergave", systemImage: "gearshape")
        }
    }

    // MARK: - Gedrag

    private func start() {
        guard lader == nil, let client = instellingen.client else { return }
        let nieuwe = Beeldlader(
            client: client, boek: boek.id, serieID: boek.seriesID, vanAbonnement: boek.fromSource
        )
        nieuwe.bewerking = Beeldbewerking(bijsnijden: bijsnijden, contrast: contrast)
        nieuwe.profiel = instellingen.profiel
        lader = nieuwe
        paneelbron = Paneelbron(
            client: client, boek: boek.id, rechtsNaarLinks: rechtsNaarLinks
        )
        startpagina = boek.progress?.page ?? 0
        paneelpad = Paneelpad(pagina: startpagina, paneel: Paneelpad.overzicht)
        spreadIndex = Spreads.spreadVanPagina(spreads, pagina: boek.progress?.page ?? 0)
        laadRondom(nieuwe)
    }

    private func pasBewerkingToe() {
        lader?.bewerking = Beeldbewerking(bijsnijden: bijsnijden, contrast: contrast)
    }

    private func laadRondom(_ lader: Beeldlader) {
        guard spreads.indices.contains(spreadIndex) else { return }
        let hier = spreads[spreadIndex]
        let straks = Spreads.vooruitLaden(spreads, huidige: spreadIndex, vooruit: 2)

        for index in hier + straks {
            Task { await haalMerkjes(index) }
        }
        for index in hier {
            Task { await lader.laad(index, keuze: keuze(voor: index)) }
        }
        lader.laadVooruit(straks)
    }

    /// Wat er voor deze pagina klaarligt. Alleen lezen, dus gratis.
    private func haalMerkjes(_ index: Int) async {
        guard let client = instellingen.client else { return }
        if vertalingen[index] == nil {
            vertalingen[index] = try? await client.vertaling(
                boek: boek.id, index: index, taal: taal
            )
        }
        if kleuren[index] == nil {
            kleuren[index] = try? await client.kleurinfo(boek: boek.id, index: index, taal: taal)
        }
    }

    /// Opnieuw ophalen wat er voor deze pagina ligt, en het oude beeld weg.
    ///
    /// Zonder dit blijft de vorige versie staan: het adres is hetzelfde, dus de
    /// cache geeft hem gewoon terug en lijkt er niets gebeurd. Dezelfde reden
    /// waarom de web-lezer een oplopend versienummer per pagina heeft.
    private func vernieuwPagina(_ index: Int) {
        vertalingen[index] = nil
        kleuren[index] = nil
        lader?.vergeet(index)
        Task {
            await haalMerkjes(index)
            if let lader { laadRondom(lader) }
        }
    }

    private func planBewaren() {
        bewaartaak?.cancel()
        let pagina = huidigePagina
        let percent = Spreads.percentVoor(spreads, spreadIndex: spreadIndex, paginas: paginas)
        bewaartaak = Task {
            try? await Task.sleep(for: .milliseconds(1200))
            guard !Task.isCancelled else { return }
            await bewaar(pagina: pagina, percent: percent)
        }
    }

    private func bewaar(pagina: Int, percent: Double) async {
        guard let client = instellingen.client, paginas > 0 else { return }
        try? await client.bewaarVoortgang(
            boek: boek.id,
            positie: ["page": pagina],
            percent: percent,
            uitgelezen: percent >= 100
        )
    }
}

/// Wat de rasterzoom nu toont.
struct Rasterstand: Equatable {
    let rijen: Int
    let kolommen: Int
    let cel: Int
    let rechtsNaarLinks: Bool

    var sprong: Rastersprong {
        let cellen = Raster.volgorde(
            rijen: rijen, kolommen: kolommen, rechtsNaarLinks: rechtsNaarLinks
        )
        guard cellen.indices.contains(cel) else {
            return Rastersprong(schaal: 1, verschuifX: 0, verschuifY: 0)
        }
        return Raster.sprong(naar: cellen[cel], rijen: rijen, kolommen: kolommen)
    }
}

/// Eén pagina in de pager.
private struct PaginaView: View {
    let index: Int
    let keuze: Paginakeuze
    let ballonnen: [Bubble]
    let lader: Beeldlader
    let passend: Passend
    @Binding var ingezoomd: Bool
    let raster: Rasterstand?
    @Binding var origineelVan: Bubble?
    let opTik: (Double) -> Void
    let opDubbeltik: () -> Void

    @State private var beeld: UIImage?

    var body: some View {
        GeometryReader { maat in
            ZStack {
                if let beeld {
                    ZStack(alignment: .topLeading) {
                        if raster == nil {
                            ZoomBareBeeld(
                                beeld: beeld,
                                passend: passend,
                                ingezoomd: $ingezoomd,
                                opDubbeltik: opDubbeltik
                            )
                        } else {
                            Image(uiImage: beeld).resizable().scaledToFit()
                        }
                        if !ballonnen.isEmpty {
                            BallonOverlay(
                                bubbles: ballonnen,
                                paginakader: paginakader(beeld: beeld, in: maat.size),
                                origineelVan: $origineelVan
                            )
                        }
                    }
                    .modifier(Rasterzoom(stand: raster, kader: maat.size))
                } else {
                    ProgressView().tint(.white)
                }
            }
            .frame(width: maat.size.width, height: maat.size.height)
            .contentShape(Rectangle())
            // Met de plek erbij: links terug, rechts verder, midden de balk.
            .onTapGesture { plek in
                opTik(maat.size.width > 0 ? plek.x / maat.size.width : 0.5)
            }
        }
        .task(id: sleutel) {
            if let klaar = lader.klaarstaand(index, keuze: keuze) {
                beeld = klaar
            } else {
                beeld = await lader.laad(index, keuze: keuze)
            }
        }
    }

    private var sleutel: String { "\(index)-\(keuze)-\(lader.profiel)-\(lader.bewerking.sleutel)" }

    /// Waar de pagina echt staat binnen het scherm.
    ///
    /// `scaledToFit` laat balken vallen naast of onder het beeld, en de vlakken
    /// van een vertaling zijn genormaliseerd op de pagina — niet op het scherm.
    private func paginakader(beeld: UIImage, in maat: CGSize) -> CGRect {
        guard beeld.size.width > 0, beeld.size.height > 0, maat.width > 0, maat.height > 0 else {
            return CGRect(origin: .zero, size: maat)
        }
        let schaal = min(maat.width / beeld.size.width, maat.height / beeld.size.height)
        let breedte = beeld.size.width * schaal
        let hoogte = beeld.size.height * schaal
        return CGRect(
            x: (maat.width - breedte) / 2,
            y: (maat.height - hoogte) / 2,
            width: breedte,
            height: hoogte
        )
    }
}

/// Eén strook in de doorlopende weergave.
///
/// Geen zoom en geen raster: bij doorlopend scrollen vecht een scrollview in een
/// scrollview om elke veeg, en bij een webtoon wil je toch de volle breedte.
private struct StrookView: View {
    let index: Int
    let keuze: Paginakeuze
    let ballonnen: [Bubble]
    let lader: Beeldlader
    @Binding var origineelVan: Bubble?

    @State private var beeld: UIImage?

    var body: some View {
        Group {
            if let beeld {
                GeometryReader { maat in
                    let hoogte = maat.size.width * beeld.size.height / max(beeld.size.width, 1)
                    ZStack(alignment: .topLeading) {
                        Image(uiImage: beeld)
                            .resizable()
                            .scaledToFit()
                        if !ballonnen.isEmpty {
                            BallonOverlay(
                                bubbles: ballonnen,
                                paginakader: CGRect(
                                    x: 0, y: 0, width: maat.size.width, height: hoogte
                                ),
                                origineelVan: $origineelVan
                            )
                        }
                    }
                }
                .aspectRatio(
                    beeld.size.width / max(beeld.size.height, 1), contentMode: .fit
                )
            } else {
                // Een plaatsvervanger met hoogte: zonder dit klapt de lijst in
                // elkaar en springt hij bij elk geladen beeld.
                Color.black.frame(height: 500).overlay(ProgressView().tint(.white))
            }
        }
        .task(id: keuze) {
            if let klaar = lader.klaarstaand(index, keuze: keuze) {
                beeld = klaar
            } else {
                beeld = await lader.laad(index, keuze: keuze)
            }
        }
    }
}

/// Schaalt en verschuift de pagina naar de gekozen rastercel.
private struct Rasterzoom: ViewModifier {
    let stand: Rasterstand?
    let kader: CGSize

    func body(content: Content) -> some View {
        if let stand {
            let sprong = stand.sprong
            content
                .scaleEffect(sprong.schaal)
                .offset(
                    x: sprong.verschuifX * kader.width * sprong.schaal,
                    y: sprong.verschuifY * kader.height * sprong.schaal
                )
                .clipped()
        } else {
            content
        }
    }
}

/// Eén paneel beeldvullend, met de vertaalde ballonnen op hun plek.
///
/// De pagina wordt geschaald en verschoven zodat het paneel het scherm vult; de
/// ballonnen liggen op de pagina en schuiven dus vanzelf mee. Dat is de reden
/// dat de overlay hier op het hele paginakader gaat en niet op het paneel: de
/// vlakken zijn genormaliseerd op de pagina, en die verhouding moet kloppen.
private struct PaneelView: View {
    let index: Int
    let paneel: Paneel
    let keuze: Paginakeuze
    let ballonnen: [Bubble]
    let lader: Beeldlader
    let kader: CGSize
    let marge: Double
    @Binding var origineelVan: Bubble?

    @State private var beeld: UIImage?
    // Zelf knijpen en slepen bovenop de paneelsprong. Niet via ZoomBareBeeld:
    // die zet de héle pagina passend in beeld, en hier is het beeld juist
    // bewust groter dan het scherm.
    @State private var zoom: CGFloat = 1
    @State private var zoomBasis: CGFloat = 1
    @State private var sleep: CGSize = .zero
    @State private var sleepBasis: CGSize = .zero

    var body: some View {
        Group {
            if let beeld {
                let plaats = paginaplaats(beeld: beeld)
                // `Color.clear` als bodem en expliciet linksboven uitlijnen: de
                // pagina is hier gróter dan het scherm, en zonder dit centreert
                // SwiftUI hem alsnog — waarmee de berekende verschuiving wordt
                // overreden en je naast het paneel uitkomt. Dezelfde valkuil als
                // bij de ballonoverlay.
                ZStack(alignment: .topLeading) {
                    Color.clear
                    ZStack(alignment: .topLeading) {
                        Image(uiImage: beeld)
                            .resizable()
                            .frame(width: plaats.width, height: plaats.height)
                        if !ballonnen.isEmpty {
                            BallonOverlay(
                                bubbles: ballonnen,
                                paginakader: CGRect(origin: .zero, size: plaats.size),
                                origineelVan: $origineelVan
                            )
                        }
                    }
                    .offset(x: plaats.minX, y: plaats.minY)
                }
                .scaleEffect(zoom)
                .offset(sleep)
                .frame(width: kader.width, height: kader.height, alignment: .topLeading)
                .clipped()
                .gesture(
                    MagnifyGesture()
                        .onChanged { waarde in
                            // Ook onder 1 mogen: het paneel vult standaard het
                            // scherm, en soms wil je even zien waar het op de
                            // pagina stond zonder de stand te verlaten. Tot 0,4
                            // — verder uitzoomen levert een postzegel op.
                            zoom = min(5, max(0.4, zoomBasis * waarde.magnification))
                        }
                        .onEnded { _ in zoomBasis = zoom }
                        .simultaneously(
                            with: DragGesture()
                                .onChanged { waarde in
                                    sleep = CGSize(
                                        width: sleepBasis.width + waarde.translation.width,
                                        height: sleepBasis.height + waarde.translation.height
                                    )
                                }
                                .onEnded { _ in sleepBasis = sleep }
                        )
                )
            } else {
                ProgressView().tint(.white)
            }
        }
        .task(id: sleutel) {
            if let klaar = lader.klaarstaand(index, keuze: keuze) {
                beeld = klaar
            } else {
                beeld = await lader.laad(index, keuze: keuze)
            }
        }
        .onChange(of: paneel) { _, _ in
            // Een nieuw paneel begint weer passend in beeld; anders zit je op
            // de plek waar je het vorige had uitvergroot.
            zoom = 1
            zoomBasis = 1
            sleep = .zero
            sleepBasis = .zero
        }
    }

    private var sleutel: String { "\(index)-\(keuze)" }

    /// Waar de hele pagina komt te liggen zodat dít paneel het scherm vult.
    ///
    /// De schaal is de krapste van breedte en hoogte: liever een randje van het
    /// buurpaneel in beeld dan het paneel zelf half afgesneden.
    private func paginaplaats(beeld: UIImage) -> CGRect {
        // Het paneel mét de ingestelde lucht eromheen. Bij het overzicht
        // (de hele pagina) verandert er niets: die kan niet groter.
        let verhouding = beeld.size.height / max(beeld.size.width, 1)
        let ruim = paneel.metMarge(marge, verhouding: Double(verhouding))

        // Expliciet als CGFloat: gemengd met Double laat Swift de deling
        // hieronder als dubbelzinnig staan.
        let breed = CGFloat(max(0.001, ruim.x1 - ruim.x0))
        let hoog = CGFloat(max(0.001, ruim.y1 - ruim.y0))
        let paneelX = CGFloat(ruim.x0)
        let paneelY = CGFloat(ruim.y0)
        guard kader.width > 0, kader.height > 0 else {
            return CGRect(origin: .zero, size: kader)
        }
        // De pagina wordt zo groot getekend dat het paneel er precies in
        // past. Bij een breedte W is de hoogte W × verhouding; het paneel meet
        // dan breed×W bij hoog×H. Beide moeten binnen het scherm passen, dus
        // de krapste van de twee bepaalt: liever een randje van het buurpaneel
        // in beeld dan dit paneel half afgesneden.
        // Het hele scherm, ook onder de balken: die zweven eroverheen en
        // hebben geen eigen ruimte. Een strip die krimpt omdat er een menu
        // openstaat leest slechter dan een strip met een balkje eroverheen —
        // en de balk gaat met één tik weg.
        let paginaBreedte = min(
            kader.width / breed,
            kader.height / (hoog * verhouding)
        )
        let paginaHoogte = paginaBreedte * verhouding

        // Verschuiven zodat het paneel midden in die vrije ruimte komt.
        let x = -paneelX * paginaBreedte + (kader.width - breed * paginaBreedte) / 2
        let y = -paneelY * paginaHoogte + (kader.height - hoog * paginaHoogte) / 2
        return CGRect(x: x, y: y, width: paginaBreedte, height: paginaHoogte)
    }
}


