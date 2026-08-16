import SwiftUI

/// Vertalen en inkleuren laten maken — de knoppen die geld kosten.
///
/// De regel uit CLAUDE.md staat hier in de vorm van het scherm: **nooit starten
/// zonder bedrag.** Voor één pagina staat de prijs bij de knop; voor een heel
/// hoofdstuk wordt eerst een plan opgehaald (hoeveel pagina's staan er nog open,
/// wat kost dat) en pas daarna komt de vraag of het mag starten. Wat er al ligt
/// valt uit dat plan, dus je betaalt nooit twee keer.
struct MaakSheet: View {
    let boek: Book
    let pagina: Int
    let taal: String
    /// Wat er voor deze pagina al ligt; bepaalt of "opnieuw" nodig is.
    let vertaling: PageTranslation?
    let kleur: ColourInfo?
    /// Roept de lezer aan zodra er iets nieuws klaarstaat.
    let opVernieuwd: () -> Void

    @Environment(Instellingen.self) private var instellingen
    @Environment(\.dismiss) private var sluit

    @State private var standen: Vertaalinstellingen?
    @State private var bezig: String?
    @State private var melding: String?
    @State private var fout: String?

    // Een heel hoofdstuk: eerst het plan, dan de vraag.
    @State private var plan: Batchplan?
    @State private var planSoort: String?
    @State private var status: Batchstatus?
    @State private var toontBevestiging = false

    // Al in kleur: de server geeft 412 en vraagt of je het écht wilt.
    @State private var vraagOverschilderen = false
    /// Vanaf welke pagina een hoofdstukklus telt.
    ///
    /// Standaard het hele hoofdstuk, anders dan de web-app. Daar begint "de
    /// rest vertalen" bij waar je bent, en dat is logisch voor een leeswachtrij
    /// die je vóór blijft. Maar hier zet je bewust een klus klaar en reken je
    /// af, en dan is stilzwijgend de eerste helft overslaan verkeerd: het gaf
    /// "niets meer open" terwijl er vier pagina's lagen te wachten, en het liet
    /// eerder pagina 1 tot 3 zomaar buiten de klus vallen. Wie wél vanaf hier
    /// wil, zet het om — en het bedrag hiernaast verandert meteen mee.
    @State private var vanafBegin = true
    @State private var volgtaak: Task<Void, Never>?
    @State private var overzicht: [Paginastatus] = []
    @State private var overzichtLaadt = false

    var body: some View {
        NavigationStack {
            Form {
                if let standen, !standen.configured {
                    Section {
                        Text(
                            "Er is geen Gemini-sleutel op de server ingesteld, dus vertalen en "
                                + "inkleuren kan niet."
                        )
                        .foregroundStyle(.secondary)
                    }
                } else {
                    if let status { lopende_klus(status) }
                    pagina_sectie
                    hoofdstuk_sectie
                    overzicht_sectie
                }
                if let melding {
                    Section { Text(melding).font(.callout).foregroundStyle(.secondary) }
                }
                if let fout {
                    Section { Text(fout).font(.callout).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Laten maken")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Klaar") { sluit() }
                }
            }
            .task { await haalStanden() }
            .task { await volgDeKlus() }
            .task { await haalOverzicht() }
            .onDisappear { volgtaak?.cancel() }
            .alert("Hoofdstuk laten doen?", isPresented: $toontBevestiging, presenting: plan) { plan in
                Button("Starten") { Task { await startBatch() } }
                Button("Annuleren", role: .cancel) {}
            } message: { plan in
                Text(planTekst(plan))
            }
            .alert("Deze pagina heeft al kleur", isPresented: $vraagOverschilderen) {
                Button("Toch inkleuren", role: .destructive) {
                    Task { await kleurNu(force: true) }
                }
                Button("Annuleren", role: .cancel) {}
            } message: {
                Text(
                    "De tekenaar kleurde deze pagina zelf al. Inkleuren is dan geen inkleuren "
                        + "maar overschilderen: het model vervangt het palet, voor dezelfde prijs."
                )
            }
        }
    }

    // MARK: - Deze pagina

    private var pagina_sectie: some View {
        Section {
            knop(
                titel: vertaling == nil ? "Vertalen (tekstvlakken)" : "Opnieuw vertalen",
                prijs: standen?.costs["text"],
                sleutel: "tekst"
            ) {
                await vertaalNu(stand: "text")
            }
            knop(
                titel: "Hertekenen mét vertaling",
                prijs: standen?.costs[standen?.buttonMode ?? "image_fast"],
                sleutel: "hertekend"
            ) {
                await vertaalNu(stand: standen?.buttonMode ?? "image_fast")
            }
            knop(
                titel: kleurHeeft ? "Opnieuw inkleuren" : "Inkleuren",
                prijs: standen?.costs[standen?.colourMode ?? "image_fast"],
                sleutel: "kleur"
            ) {
                await kleurNu(force: kleurHeeft)
            }
        } header: {
            Text("Pagina \(pagina + 1)")
        } footer: {
            Text("Eén pagina tegelijk. Wat er al ligt wordt nooit vanzelf vervangen.")
        }
    }

    private var kleurHeeft: Bool { kleur?.available == true }

    private func knop(
        titel: String, prijs: Double?, sleutel: String, actie: @escaping () async -> Void
    ) -> some View {
        Button {
            Task { await actie() }
        } label: {
            HStack {
                Text(titel)
                Spacer()
                if bezig == sleutel {
                    ProgressView()
                } else if let prijs {
                    // De prijs staat bij de knop en niet in een voetnoot: dit is
                    // het moment waarop je hem wilt weten.
                    Text(Kosten.tekst(prijs)).foregroundStyle(.secondary).font(.callout)
                }
            }
        }
        .disabled(bezig != nil)
    }

    // MARK: - Heel hoofdstuk

    private var hoofdstuk_sectie: some View {
        Section {
            // De namen die de server kent (`batch.SOORTEN`), en die zijn
            // Nederlands. Engelse gokjes gaven hier "onbekende soort".
            ForEach(["tekst", "hertekend", "kleuren"], id: \.self) { soort in
                Button {
                    Task { await haalPlan(soort) }
                } label: {
                    HStack {
                        Text(soortnaam(soort))
                        Spacer()
                        if planSoort == soort && plan == nil {
                            ProgressView()
                        } else {
                            Image(systemName: "chevron.right").font(.caption)
                                .foregroundStyle(.tertiary)
                        }
                    }
                }
                .disabled(bezig != nil || (status?.loopt ?? false))
            }
            Picker("Vanaf", selection: $vanafBegin) {
                Text("Hele hoofdstuk").tag(true)
                Text("Vanaf pagina \(pagina + 1)").tag(false)
            }
            .pickerStyle(.segmented)
        } header: {
            Text("Heel hoofdstuk")
        } footer: {
            Text(
                "Via de batch van Google: de helft van het tarief, maar je wacht — bij een "
                    + "hoofdstuk van 25 pagina's gemeten twee uur, want je staat in hun "
                    + "wachtrij. Je krijgt eerst te zien wat het kost."
            )
        }
    }

    // MARK: - Wat er per pagina ligt

    private var overzicht_sectie: some View {
        Section {
            if overzichtLaadt && overzicht.isEmpty {
                HStack { ProgressView(); Text("Nalopen…").foregroundStyle(.secondary) }
            } else {
                ForEach(overzicht) { regel in
                    HStack {
                        Text("\(regel.index + 1)")
                            .monospacedDigit()
                            .frame(width: 34, alignment: .leading)
                            .foregroundStyle(regel.index == pagina ? Color.accentColor : .primary)
                        Text(regel.vertaaltekst)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Text(regel.kleurtekst)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .font(.caption)
                    .foregroundStyle(regel.heeftIets ? .primary : .secondary)
                }
            }
        } header: {
            HStack {
                Text("Per pagina")
                Spacer()
                Text("vertaling").font(.caption2).frame(maxWidth: 90, alignment: .leading)
                Text("kleur").font(.caption2).frame(maxWidth: 70, alignment: .leading)
            }
        } footer: {
            Text(
                "Wat er al ligt telt niet mee in een nieuwe klus, dus je betaalt nooit twee keer. "
                    + "Een streepje betekent: nog niets."
            )
        }
    }

    private func haalOverzicht() async {
        guard let client = instellingen.client, let paginas = boek.pageCount, paginas > 0 else {
            return
        }
        overzichtLaadt = true
        defer { overzichtLaadt = false }

        // Begrensd parallel: 29 pagina's maal twee verzoeken is prima voor een
        // NAS in huis, maar allemaal tegelijk losgooien is onnodig onbeleefd.
        var uit: [Paginastatus] = []
        await withTaskGroup(of: Paginastatus.self) { groep in
            var volgende = 0
            func leg(_ index: Int) {
                groep.addTask {
                    async let vertaling = try? await client.vertaling(
                        boek: boek.id, index: index, taal: taal
                    )
                    async let kleur = try? await client.kleurinfo(
                        boek: boek.id, index: index, taal: taal
                    )
                    return Paginastatus(
                        index: index, vertaling: await vertaling, kleur: await kleur
                    )
                }
            }
            while volgende < min(8, paginas) {
                leg(volgende)
                volgende += 1
            }
            for await klaar in groep {
                uit.append(klaar)
                if volgende < paginas {
                    leg(volgende)
                    volgende += 1
                }
            }
        }
        overzicht = uit.sorted { $0.index < $1.index }
    }

    private func lopende_klus(_ status: Batchstatus) -> some View {
        Section {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(soortnaam(status.kind))
                    Spacer()
                    Text(status.samenvatting)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
                ProgressView(value: Double(status.done), total: Double(max(status.total, 1)))
                if status.failed > 0 {
                    // Eén mislukte pagina maakt de rest niet ongeldig; die staat
                    // gewoon klaar. Wel zeggen dat het gebeurd is, anders zoek
                    // je je scheel naar die ene pagina.
                    Text("\(status.failed) pagina('s) niet gelukt — die staan nog open")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
                if let fout = status.error {
                    Text(fout).font(.caption).foregroundStyle(.red)
                }
            }
        } header: {
            Text(status.loopt ? "Loopt nu" : "Laatste klus")
        } footer: {
            // De vraag die je bij zo'n balk meteen hebt.
            Text(
                status.loopt
                    ? "Je kunt gewoon verder lezen. Dit draait op de server en bij Google — "
                        + "ook als je dit scherm sluit of de app weglegt. Een pagina die klaar "
                        + "is verschijnt vanzelf zodra je hem opnieuw opent."
                    : "Klaar. Blader naar een pagina om het resultaat te zien. "
                        + "Een klus die klaar is blokkeert niets: je kunt meteen een volgende starten."
            )
        }
    }

    private func soortnaam(_ soort: String) -> String {
        switch soort {
        case "tekst": return "Tekstvlakken"
        case "hertekend": return "Hertekenen"
        case "kleuren": return "Inkleuren"
        default: return soort
        }
    }

    private func planTekst(_ plan: Batchplan) -> String {
        let vanaf = vanafBegin ? "het begin" : "pagina \(pagina + 1)"
        guard plan.pages > 0 else {
            return "Vanaf \(vanaf) staat er niets meer open in dit hoofdstuk."
        }
        return """
            Vanaf \(vanaf): \(plan.pages) pagina's × \(Kosten.tekst(plan.pricePerPage)) = \
            \(Kosten.tekst(plan.total)).

            Dat is het batchtarief (\(Int(plan.batchFactor * 100))% van het gewone). \
            Wat er al ligt telt niet mee, dus je betaalt nooit twee keer.
            """
    }

    // MARK: - Gedrag

    /// De voortgang van een lopende klus bijhouden.
    ///
    /// Pollen en geen melding van de server: er is geen kanaal terug, en een
    /// batch duurt minuten. Elke vijf seconden vragen is ruim genoeg en scheelt
    /// een websocket die we verder nergens voor nodig hebben.
    private func volgDeKlus() async {
        volgtaak?.cancel()
        volgtaak = Task {
            while !Task.isCancelled {
                guard let client = instellingen.client else { return }
                let nu = try? await client.batchstatus(boek: boek.id)
                await MainActor.run { status = nu }
                guard nu?.loopt == true else { return }
                try? await Task.sleep(for: .seconds(5))
            }
        }
        await volgtaak?.value
    }

    private func haalStanden() async {
        guard let client = instellingen.client else { return }
        standen = try? await client.vertaalinstellingen()
        status = try? await client.batchstatus(boek: boek.id)
    }

    private func vertaalNu(stand: String) async {
        guard let client = instellingen.client else { return }
        bezig = stand == "text" ? "tekst" : "hertekend"
        melding = nil
        fout = nil
        defer { bezig = nil }
        do {
            if stand == "text" {
                _ = try await client.vertaalPagina(
                    boek: boek.id, index: pagina, taal: taal, force: vertaling != nil
                )
            } else {
                _ = try await client.hertekenPagina(
                    boek: boek.id, index: pagina, stand: stand, taal: taal, force: true
                )
            }
            melding = "Klaar — pagina \(pagina + 1) is bijgewerkt."
            opVernieuwd()
            await haalOverzicht()
        } catch {
            fout = error.localizedDescription
        }
    }

    private func kleurNu(force: Bool) async {
        guard let client = instellingen.client else { return }
        bezig = "kleur"
        melding = nil
        fout = nil
        defer { bezig = nil }
        do {
            _ = try await client.kleurPagina(
                boek: boek.id, index: pagina, taal: nil, force: force
            )
            melding = "Klaar — pagina \(pagina + 1) is ingekleurd."
            opVernieuwd()
            await haalOverzicht()
        } catch ClientFout.alInKleur {
            vraagOverschilderen = true
        } catch {
            fout = error.localizedDescription
        }
    }

    private func haalPlan(_ soort: String) async {
        guard let client = instellingen.client else { return }
        planSoort = soort
        plan = nil
        fout = nil
        do {
            let opgehaald = try await client.batchplan(
                boek: boek.id, soort: soort, vanafPagina: vanafBegin ? 0 : pagina
            )
            plan = opgehaald
            toontBevestiging = true
        } catch {
            fout = error.localizedDescription
            planSoort = nil
        }
    }

    private func startBatch() async {
        guard let client = instellingen.client, let soort = planSoort else { return }
        do {
            status = try await client.startBatch(
                boek: boek.id, soort: soort, vanafPagina: vanafBegin ? 0 : pagina
            )
            melding = "De klus staat in de wachtrij bij Google; dat duurt minuten."
            // Meteen meekijken, zodat de balk niet pas bij het volgende openen
            // begint te lopen.
            Task { await volgDeKlus() }
        } catch {
            fout = error.localizedDescription
        }
        plan = nil
    }
}
