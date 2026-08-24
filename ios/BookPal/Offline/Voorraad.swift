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
        case omslagen
        case paginas(klaar: Int, van: String)
        case vol
        /// De server had het te druk; we proberen het later nog eens.
        case wacht
        case klaar(paginas: Int)
        case mislukt(String)
    }

    private(set) var stand: Stand = .stil
    private var taak: Task<Void, Never>?
    private var laatsteRonde: Date?

    /// Rustpauze tussen twee paginaverzoeken. Zonder dit vroeg de vooruitlader
    /// onafgebroken pagina's op — gemeten 547 verzoeken in één ronde — en dan
    /// komt de NAS niet meer toe aan de healthcheck. Autoheal zag een zieke
    /// container en herstartte hem elke vier minuten, precies het ritme van
    /// deze ronde. De telefoon kon dan geen verbinding maken.
    ///
    /// Dit is voorraad aanleggen, geen race: een kwart seconde per pagina vult
    /// in een half uur ruim duizend pagina's, en dat is snel zat.
    private static let pauze: Duration = .milliseconds(250)

    /// Duurt een verzoek langer dan dit, dan heeft de server het te druk —
    /// waarschijnlijk omdat jij aan het lezen bent. Dan stoppen we deze ronde;
    /// bij het volgende logische moment gaat hij gewoon verder.
    private static let teTraag: TimeInterval = 5.0

    /// Hoe vaak een ronde vanzelf mag starten. Kort genoeg dat je nieuwe
    /// vertalingen snel op je toestel hebt, lang genoeg dat het heen en weer
    /// schakelen tussen apps geen tien rondes tegelijk oplevert. De knop in
    /// Instellingen negeert dit — die vraag je expliciet.
    private static let vanzelfInterval: TimeInterval = 120

    var loopt: Bool { taak != nil }

    private init() {}

    /// Voor de automatische momenten: bij het openen van de app en zodra de
    /// NAS weer bereikbaar is. Doet niets als er net een ronde geweest is of er
    /// al één loopt.
    func startIndienNodig(_ client: Client) {
        guard taak == nil else { return }
        if let laatste = laatsteRonde,
           Date().timeIntervalSince(laatste) < Self.vanzelfInterval { return }
        start(client)
    }

    func start(_ client: Client) {
        guard taak == nil else { return }
        laatsteRonde = Date()
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

        // Eerst alle omslagen, van élke serie. Ze zijn klein (320px) en ze
        // zijn wat je offline als eerste mist: zonder omslag is een
        // bibliotheek een raster grijze vakjes waarin niets te herkennen valt.
        // Ze tellen niet mee in het paginabudget.
        stand = .omslagen
        for serie in series {
            if Task.isCancelled { return }
            let adres = client.omslagURL(serie: serie.id)
            _ = try? await URLSession.shared.data(from: adres)
            try? await Task.sleep(for: Self.pauze)
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
                if case .wacht = stand { return }
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
            let begin = Date()
            guard let (data, antwoord) = try? await URLSession.shared.data(from: adres),
                  let http = antwoord as? HTTPURLResponse, (200..<300).contains(http.statusCode)
            else { continue }
            let duur = Date().timeIntervalSince(begin)
            await Paginacache.gedeeld.schrijf(
                data, serieID: serie.id, boek: boek.id, sleutel: sleutel
            )
            nieuw += 1
            if await Paginacache.gedeeld.omvang >= limiet { return nieuw }

            // De server voorrang geven boven onze voorraad: hij bedient ook
            // jouw lezer, en een healthcheck die geen beurt krijgt kost een
            // herstart middenin het lezen.
            if duur > Self.teTraag {
                stand = .wacht
                return nieuw
            }
            try? await Task.sleep(for: Self.pauze)
        }
        return nieuw
    }
}
