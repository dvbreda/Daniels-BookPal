import Foundation
import UIKit

/// Waar een tekstballon komt te staan en hoe groot de letters worden.
///
/// Losgetrokken van het tekenen, en precies dezelfde som als
/// `web/src/reader/bubbles.ts`. Het is het soort rekenwerk dat er op het scherm
/// "bijna goed" uitziet: een ballon die net te klein is knipt zijn tekst weg, en
/// dan lijkt het alsof er niets vertaald is.
enum Ballonnen {
    /// Hoeveel het vlak buiten de gedetecteerde tekst groeit.
    ///
    /// Een ronde vorm die precies ín het tekstvlak past verliest juist de hoeken
    /// waar de tekst staat. Door het vlak op te rekken en de tekstruimte gelijk
    /// te houden ligt de tekst weer op het wit in plaats van op de tekening.
    static let groei = 0.05

    /// Ruwe maat voor hoeveel tekens er in een vlak passen bij normale grootte.
    static let tekensPerVlak = 1000.0

    /// Een vlak op de pagina, genormaliseerd op 0…1: [x0, y0, x1, y1].
    static func rekOp(_ vlak: [Double], groei: Double = groei) -> [Double] {
        guard vlak.count == 4 else { return vlak }
        let breedte = vlak[2] - vlak[0]
        let hoogte = vlak[3] - vlak[1]
        return [
            max(0, vlak[0] - breedte * groei),
            max(0, vlak[1] - hoogte * groei),
            min(1, vlak[2] + breedte * groei),
            min(1, vlak[3] + hoogte * groei),
        ]
    }

    /// Hoeveel de letters moeten krimpen om de tekst te laten passen.
    ///
    /// 1 als het ruim past. Kijkt naar het oppervlak en niet alleen naar de
    /// breedte: dat laatste liet een lange zin in een klein vlak overlopen, en
    /// dan werd hij weggeknipt. Groter dan de basismaat wordt het nooit, want
    /// dan zou een kort woord ineens beeldvullend worden.
    static func letterschaal(vlak: [Double], tekens: Int) -> Double {
        guard vlak.count == 4 else { return 1 }
        let ruimte = (vlak[2] - vlak[0]) * (vlak[3] - vlak[1]) * tekensPerVlak
        guard ruimte > 0 else { return 1 }
        return min(1, (ruimte / Double(max(1, tekens))).squareRoot())
    }

    /// De grootste lettergrootte waarbij de tekst écht in het vlak past.
    ///
    /// De schatting hierboven komt uit de web-lezer en is goed genoeg om een
    /// bovengrens mee te zetten, maar bij een lange zin in een bescheiden vlak
    /// zit hij ernaast en loopt de tekst buiten de ballon — op Oishinbo p3
    /// zichtbaar over de tekening heen. Op iOS hoeven we niet te schatten: we
    /// kunnen de tekst met het echte lettertype opmeten en de grootste maat
    /// zoeken die past. Dat is meteen ongevoelig voor een ander lettertype, en
    /// dat scheelt: DigitalStrip zet breder op dan Comic Neue.
    static func passendeGrootte(
        _ tekst: String,
        in maat: CGSize,
        fontnaam: String,
        maximum: CGFloat,
        minimum: CGFloat = 6
    ) -> CGFloat {
        guard maat.width > 1, maat.height > 1, !tekst.isEmpty, maximum > minimum else {
            return minimum
        }
        var laag = minimum
        var hoog = maximum
        // Halveren tot op een halve punt nauwkeurig: een stuk of zes rondes,
        // en dat is goedkoper dan per punt aflopen.
        while hoog - laag > 0.5 {
            let midden = (laag + hoog) / 2
            if past(tekst, maat: maat, fontnaam: fontnaam, grootte: midden) {
                laag = midden
            } else {
                hoog = midden
            }
        }
        return laag
    }

    /// Tot hoeveel tekens iets een kreet is in plaats van een zin.
    ///
    /// "EH?", "HAHA" en "KRAAK" mogen de ballon vullen — dat is hoe een strip
    /// gelettered is, en juist bij geluidseffecten hoort dat zo. Zodra het een
    /// zin wordt, is groot zetten alleen maar lomp.
    static let kreetTot = 10

    /// Hoe groot lopende tekst maximaal wordt, als deel van de paginahoogte.
    ///
    /// Een vaste leesmaat en niet "wat er past": in een ruime ballon past een
    /// hele alinea op dubbele grootte, en dat is precies wat er lelijk uitziet.
    /// Met een plafond staat lopende tekst overal even groot, ongeacht hoe groot
    /// de ballon toevallig is.
    ///
    /// Op het toestel bijgesteld: 0,022 → 0,015 → 0,011. Dit is een smaakoordeel
    /// op een echt scherm en geen berekening — een schermafdruk van de simulator
    /// gaf er een verkeerd beeld van, omdat je daar naar een vergroting van een
    /// telefoon zit te kijken.
    static let leesmaatDeel: CGFloat = 0.011

    /// Begrenst lopende tekst tot de leesmaat; korte kreten blijven zoals ze
    /// passen. Alleen naar bóven begrenzen, nooit naar beneden — groter dan wat
    /// past zou de tekst weer buiten de ballon duwen.
    static func begrens(
        _ groottes: [CGFloat],
        tekens: [Int],
        leesmaat: CGFloat,
        kreetTot: Int = kreetTot
    ) -> [CGFloat] {
        groottes.enumerated().map { index, grootte in
            let lengte = tekens.indices.contains(index) ? tekens[index] : 0
            return lengte <= kreetTot ? grootte : min(grootte, leesmaat)
        }
    }

    private static func past(
        _ tekst: String, maat: CGSize, fontnaam: String, grootte: CGFloat
    ) -> Bool {
        guard let font = UIFont(name: fontnaam, size: grootte) else { return false }
        let kader = (tekst as NSString).boundingRect(
            with: CGSize(width: maat.width, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: font],
            context: nil
        )
        return kader.height <= maat.height && kader.width <= maat.width + 0.5
    }
}
