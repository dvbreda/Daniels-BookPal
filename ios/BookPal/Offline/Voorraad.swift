import Foundation
import Observation

/// Vult het toestel vooruit, zodat je zonder NAS kunt lezen wat je nog niet
/// geopend hebt.
///
/// Twee rondes, in deze volgorde en om verschillende redenen.
///
/// **Eerst alle sidecars.** Vertalingen en ingekleurde pagina's zijn duur
/// betaald en klein — tekstvlakken zijn JSON, een hertekende plaat een paar
/// honderd kilobyte. Die horen er altijd te staan, van elke serie, ongeacht
/// wat je hebt aangevinkt. Ze tellen niet mee in het paginabudget.
///
/// **Daarna de pagina's**, tot de limiet bereikt is. Volgorde: aangevinkte
/// series eerst, dan je eigen bestanden, en abonnementen als laatste. Wat van
/// een abonnement komt is immers altijd opnieuw op te halen zolang je
/// verbinding hebt, dus dat is de goedkoopste plek om ruimte te verliezen.
///
/// Bewust geen achtergrondtaak van iOS: dit draait terwijl de app openstaat,
/// en stopt netjes zodra hij naar de achtergrond gaat. Een halve voorraad is
/// geen probleem — de volgende keer gaat hij verder waar hij was, want hij
/// slaat over wat er al ligt.
@MainActor
@Observable
final class Voorraad {
    static let gedeeld = Voorraad()

    enum Stand: Equatable {
        case stil
        case sidecars(klaar: Int, totaal: Int)
        case paginas(klaar: Int, van: String)
        case vol
        case klaar(paginas: Int)
        case mislukt(String)
    }

    private(set) var stand: Stand = .stil
    private var taak: Task<Void, Never>?

    var loopt: Bool { taak != nil }

    private init() {}

    func start(_ client: Client) {
        guard taak == nil else { return }
        taak = Task { [weak self] in
            await self?.vul(client)
            self?.taak = nil
        }
    }

    func stop() {
        taak?.cancel()
        taak = nil
        stand = .stil
    }

    private func vul(_ client: Client) async {
        // Ronde 1: alles wat betaald is.
        stand = .sidecars(klaar: 0, totaal: 0)
        await SidecarSync.gedeeld.synchroniseer(client)
        if Task.isCancelled { return }

        // Ronde 2: pagina's, in de volgorde die de vinkjes bepalen.
        let prioriteiten = Prioriteiten.gedeeld
        let limiet = prioriteiten.limietBytes
        let gekozen = prioriteiten.eigenGekozen

        guard let lijst = try? await client.series(filter: .alles) else {
            stand = .mislukt("Geen verbinding met de NAS.")
            return
        }
        let series = lijst.items.sorted { links, rechts in
            let a = gekozen.contains(links.id), b = gekozen.contains(rechts.id)
            if a != b { return a }
            // Abonnementen achteraan: die haal je toch weer op.
            if links.fromSource != rechts.fromSource { return !links.fromSource }
            return links.sortTitle < rechts.sortTitle
        }

        var opgehaald = 0
        for serie in series {
            if Task.isCancelled { return }
            guard await Paginacache.gedeeld.omvang < limiet else {
                stand = .vol
                return
            }
            guard let detail = try? await client.serie(serie.id) else { continue }
            for boek in detail.books where boek.isReadable {
                if Task.isCancelled { return }
                let gedaan = await haalBoek(boek, serie: serie, client: client, limiet: limiet)
                opgehaald += gedaan
                stand = .paginas(klaar: opgehaald, van: serie.title)
                guard await Paginacache.gedeeld.omvang < limiet else {
                    stand = .vol
                    return
                }
            }
        }
        stand = .klaar(paginas: opgehaald)
    }

    /// Eén boek, pagina voor pagina. Geeft terug hoeveel er nieuw bij kwam.
    private func haalBoek(
        _ boek: Book, serie: Series, client: Client, limiet: Int64
    ) async -> Int {
        guard let paginas = boek.pageCount, paginas > 0 else { return 0 }
        var nieuw = 0
        for index in 0..<paginas {
            if Task.isCancelled { return nieuw }
            // Exact de sleutel die de lezer opzoekt — anders vult dit de schijf
            // met bestanden die nooit gevonden worden.
            let sleutel = Beeldlader.sleutelVoor(
                index, .origineel, profiel: Client.standaardProfiel, bewerking: Beeldbewerking()
            )
            if await Paginacache.gedeeld.heeft(serieID: serie.id, boek: boek.id, sleutel: sleutel) {
                continue
            }
            guard let adres = client.paginaURL(boek: boek.id, index: index) else { continue }
            guard let (data, antwoord) = try? await URLSession.shared.data(from: adres),
                  let http = antwoord as? HTTPURLResponse, (200..<300).contains(http.statusCode)
            else { continue }
            await Paginacache.gedeeld.schrijf(
                data, serieID: serie.id, boek: boek.id, sleutel: sleutel
            )
            nieuw += 1
            if await Paginacache.gedeeld.omvang >= limiet { return nieuw }
        }
        return nieuw
    }
}
