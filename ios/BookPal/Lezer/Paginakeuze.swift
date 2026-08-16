import Foundation

/// Welke afbeelding een pagina krijgt: het origineel, de hertekende vertaling,
/// of de ingekleurde versie.
///
/// Exact dezelfde keuze als `pageSource` in de web-lezer. Dat moet ook wel: het
/// gaat om betaald werk dat op de server ligt, en als de twee lezers hier uit
/// elkaar lopen zie je op je telefoon iets anders dan in de browser — of, erger,
/// zie je een ingekleurde pagina helemaal niet omdat de hertekende versie hem
/// wegdrukt. Die fout is aan de webkant al een keer gemaakt en gerepareerd.
enum Paginakeuze: Equatable {
    case origineel
    case hertekend
    case kleur(taal: String?)

    /// - Parameters:
    ///   - vertaling: staat de vertaalschakelaar aan?
    ///   - kleurAan: staat de kleurschakelaar aan?
    ///   - heeftHertekend: ligt er een hertekende pagina klaar?
    ///   - kleur: wat de server over de kleur van deze pagina zegt.
    static func kies(
        vertaling: Bool,
        kleurAan: Bool,
        heeftHertekend: Bool,
        kleur: ColourInfo?,
        taal: String?
    ) -> Paginakeuze {
        if kleurAan, let kleur, kleur.available {
            // Alleen om de taal vragen als díe versie er ook is; anders krijg je
            // het ingekleurde origineel mét de oorspronkelijke letters erin.
            return .kleur(taal: kleur.translated ? taal : nil)
        }
        if vertaling, heeftHertekend {
            return .hertekend
        }
        return .origineel
    }

    /// Komen onze eigen tekstvlakken hier nog overheen?
    ///
    /// Bij een hertekende pagina niet: daar zit de vertaling al in het beeld
    /// gebakken. Bij een ingekleurde pagina juist wél — die is van het origineel
    /// gemaakt, dus de letters eronder zijn nog de oorspronkelijke. Dat is
    /// precies waarom kleur en de tekststand samen kunnen.
    var tekentBallonnen: Bool {
        switch self {
        case .hertekend: return false
        case .origineel, .kleur: return true
        }
    }
}
