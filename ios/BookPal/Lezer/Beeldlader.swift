import Foundation
import UIKit

/// Haalt pagina's op en houdt ze vast.
///
/// Een pagina van een paar honderd kilobyte opnieuw ophalen bij elke keer
/// terugbladeren is precies wat een lezer traag laat voelen, dus blijft wat
/// binnen is in het geheugen staan. `NSCache` en geen eigen dictionary: die
/// ruimt zichzelf op als iOS om geheugen vraagt, en dat is bij een boek van
/// driehonderd pagina's geen theoretisch geval.
///
/// De cachesleutel bevat de gekozen bron, want dezelfde pagina heeft in kleur
/// een ander beeld dan in zwart-wit. Zonder dat zou omschakelen het oude beeld
/// blijven tonen.
///
/// Onder het geheugen zit een tweede, langzamere laag op schijf
/// (`Paginacache`): wat hier ooit is opgehaald, blijft ook staan zodra iOS het
/// geheugen terugvraagt of de app opnieuw opstart, en is wat je zonder NAS
/// terugziet.
@MainActor
@Observable
final class Beeldlader {
    private let client: Client
    private let boek: Int
    private let serieID: Int
    private let cache = NSCache<NSString, UIImage>()
    private var lopend: [String: Task<UIImage?, Never>] = [:]

    /// Breedte gedeeld door hoogte, per pagina. Voedt de spread-indeling: een
    /// liggende pagina hoort het scherm alleen te vullen.
    private(set) var verhoudingen: [Int: Double] = [:]

    init(client: Client, boek: Int, serieID: Int, vanAbonnement: Bool = false) {
        self.client = client
        self.boek = boek
        self.serieID = serieID
        if vanAbonnement { Prioriteiten.gedeeld.markeerAltijdBewaren(boek: boek) }
        cache.countLimit = 24
    }

    /// Wat de server op de pagina doet vóór hij hem stuurt. Zit in de
    /// cachesleutel, want bijgesneden is een ander beeld.
    var bewerking = Beeldbewerking() {
        didSet {
            // Alles weggooien: de oude platen horen bij de vorige bewerking.
            if oldValue != bewerking { cache.removeAllObjects() }
        }
    }

    /// Het beeldprofiel waarin pagina's binnenkomen. Zit ook in de cachesleutel:
    /// een pagina op 1600px is een ander beeld dan diezelfde op 2400px.
    var profiel = Client.standaardProfiel {
        didSet {
            if oldValue != profiel { cache.removeAllObjects() }
        }
    }

    private func sleutel(_ index: Int, _ keuze: Paginakeuze) -> String {
        switch keuze {
        case .origineel: return "\(index)-o-\(profiel)-\(bewerking.sleutel)"
        // De hertekende en ingekleurde platen komen kant-en-klaar van de
        // sidecar; daar doet de server geen bijsnijden of contrast op.
        case .hertekend: return "\(index)-h"
        case let .kleur(taal): return "\(index)-k-\(taal ?? "")"
        }
    }

    private func adres(_ index: Int, _ keuze: Paginakeuze) -> URL? {
        switch keuze {
        case .origineel:
            return client.paginaURL(boek: boek, index: index, profiel: profiel, bewerking: bewerking)
        case .hertekend:
            return client.hertekendURL(boek: boek, index: index)
        case let .kleur(taal):
            return client.kleurURL(boek: boek, index: index, taal: taal)
        }
    }

    func klaarstaand(_ index: Int, keuze: Paginakeuze = .origineel) -> UIImage? {
        cache.object(forKey: sleutel(index, keuze) as NSString)
    }

    /// Haalt de pagina op, of geeft hem meteen terug als hij er al is.
    ///
    /// Twee keer tegelijk om dezelfde pagina vragen gebeurt zodra vooruitladen
    /// en de weergave elkaar overlappen; die tweede vraag hangt aan dezelfde
    /// taak in plaats van een tweede verzoek te sturen.
    ///
    /// Lukt het netwerk niet — geen NAS, geen wifi — dan valt dit terug op wat
    /// er op schijf staat van een eerdere keer. Lukt het wél, dan wordt de
    /// schijf meteen bijgewerkt, zodat de volgende keer zonder NAS ook deze
    /// pagina meetelt.
    @discardableResult
    func laad(_ index: Int, keuze: Paginakeuze = .origineel) async -> UIImage? {
        let sleutel = sleutel(index, keuze)
        if let klaar = cache.object(forKey: sleutel as NSString) { return klaar }
        if let bezig = lopend[sleutel] { return await bezig.value }

        let adres = adres(index, keuze)
        let serieID = serieID
        let boek = boek
        let taak = Task<UIImage?, Never> {
            if let adres {
                do {
                    let (data, antwoord) = try await URLSession.shared.data(from: adres)
                    if let http = antwoord as? HTTPURLResponse, (200..<300).contains(http.statusCode) {
                        await Paginacache.gedeeld.schrijf(
                            data, serieID: serieID, boek: boek, sleutel: sleutel
                        )
                        return UIImage(data: data)
                    }
                } catch {
                    // Geen verbinding: hieronder terugvallen op schijf.
                }
            }
            guard let bewaard = await Paginacache.gedeeld.lees(
                serieID: serieID, boek: boek, sleutel: sleutel
            ) else { return nil }
            return UIImage(data: bewaard)
        }
        lopend[sleutel] = taak
        let beeld = await taak.value
        lopend[sleutel] = nil

        if let beeld {
            cache.setObject(beeld, forKey: sleutel as NSString)
            // Alleen van het origineel: een hertekende of ingekleurde versie is
            // op dezelfde maat gebracht, dus dat zou hetzelfde antwoord geven.
            if case .origineel = keuze, beeld.size.height > 0 {
                verhoudingen[index] = beeld.size.width / beeld.size.height
            }
        }
        return beeld
    }

    /// Alles wat we van deze pagina hebben weggooien, in elke bron.
    ///
    /// Nodig na een betaalde klus: het adres blijft hetzelfde, dus zonder dit
    /// blijft de oude plaat in beeld en lijkt er niets te zijn gebeurd.
    func vergeet(_ index: Int) {
        for keuze in [Paginakeuze.origineel, .hertekend, .kleur(taal: nil)] {
            cache.removeObject(forKey: sleutel(index, keuze) as NSString)
        }
        // Ook de taalversies van de ingekleurde pagina.
        for taal in ["nl", "en"] {
            cache.removeObject(forKey: sleutel(index, .kleur(taal: taal)) as NSString)
        }
    }

    /// Vast ophalen wat er zo aan de beurt is, zonder erop te wachten.
    func laadVooruit(_ indexen: [Int], keuze: Paginakeuze = .origineel) {
        for index in indexen where klaarstaand(index, keuze: keuze) == nil {
            Task { await laad(index, keuze: keuze) }
        }
    }
}
