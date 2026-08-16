import SwiftUI

/// Je leeslijsten bijhouden bij MyAnimeList en Goodreads.
///
/// Eenrichtingsverkeer: BookPal leest nooit iets terug, dus er is geen conflict
/// om op te lossen. Dat betekent ook dat een push naar buiten gaat en niet meer
/// terug te draaien is — vandaar de proefstand, die standaard aan staat bij een
/// nieuw account en precies laat zien wát er verstuurd zou worden.
///
/// Het kóppelen zelf gebeurt in de web-app: daar registreer je een MAL-app met
/// een client-id en -secret en plak je een autorisatiecode terug. Dat is een
/// eenmalige klus achter een toetsenbord, geen ding voor je duim.
struct TrackersView: View {
    @Environment(Instellingen.self) private var instellingen

    @State private var accounts: [Trackeraccount] = []
    @State private var bezig: Int?
    @State private var melding: String?
    @State private var fout: String?

    var body: some View {
        List {
            if let melding {
                Section { Text(melding).font(.callout).foregroundStyle(.secondary) }
            }
            if let fout {
                Section { Text(fout).font(.callout).foregroundStyle(.red) }
            }

            if accounts.isEmpty {
                Section {
                    Text("Nog geen koppeling. Die maak je in de web-app.")
                        .foregroundStyle(.secondary)
                }
            }

            ForEach(accounts) { account in
                sectie(account)
            }

            Section {
                Link(destination: instellingen.client?.goodreadsCSV ?? URL(string: "about:blank")!) {
                    Label("Goodreads-CSV downloaden", systemImage: "square.and.arrow.down")
                }
            } header: {
                Text("Goodreads")
            } footer: {
                Text(
                    "Goodreads heeft geen werkende API meer sinds eind 2020, dus dit is het "
                        + "vangnet: een CSV voor My Books → Import and Export."
                )
            }
        }
        .navigationTitle("Trackers")
        .navigationBarTitleDisplayMode(.inline)
        .task { await haal() }
        .refreshable { await haal() }
    }

    private func sectie(_ account: Trackeraccount) -> some View {
        Section {
            LabeledContent("Gekoppeld", value: account.connected ? "ja" : "nee")
            if let laatst = account.lastSyncAt {
                LabeledContent(
                    "Laatst gesynct",
                    value: laatst.formatted(date: .abbreviated, time: .shortened)
                )
            }

            Toggle("Aan", isOn: Binding(
                get: { account.enabled },
                set: { nieuw in Task { await zet(account, actief: nieuw) } }
            ))

            Toggle("Proefstand", isOn: Binding(
                get: { account.dryRun },
                set: { nieuw in Task { await zet(account, proef: nieuw) } }
            ))

            Button {
                Task { await push(account) }
            } label: {
                HStack {
                    Label(
                        account.dryRun ? "Proefronde draaien" : "Nu pushen",
                        systemImage: "arrow.up.circle"
                    )
                    if bezig == account.id { Spacer(); ProgressView() }
                }
            }
            .disabled(bezig != nil || !account.connected)
        } header: {
            Text(account.naam)
        } footer: {
            Text(
                account.dryRun
                    ? "In proefstand gaat er niets naar buiten; je ziet alleen wát er zou gaan."
                    : "Wat je leest gaat naar \(account.naam). Eenrichting: er komt niets terug, "
                        + "en verstuurd is verstuurd."
            )
        }
    }

    private func haal() async {
        guard let client = instellingen.client else { return }
        do {
            accounts = try await client.trackers()
            fout = nil
        } catch {
            fout = error.localizedDescription
        }
    }

    private func zet(_ account: Trackeraccount, actief: Bool? = nil, proef: Bool? = nil) async {
        guard let client = instellingen.client else { return }
        _ = try? await client.zetTracker(account.id, actief: actief, proef: proef)
        await haal()
    }

    private func push(_ account: Trackeraccount) async {
        guard let client = instellingen.client else { return }
        bezig = account.id
        fout = nil
        defer { bezig = nil }
        do {
            let verslag = try await client.pushTracker(account.id)
            melding = "\(account.naam): \(verslag.samenvatting)"
            await haal()
        } catch {
            fout = error.localizedDescription
        }
    }
}
