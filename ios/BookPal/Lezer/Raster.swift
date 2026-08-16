import Foundation

/// Rasterzoom: een pagina in cellen verdelen en die één voor één vullend tonen.
///
/// Overgenomen uit `web/src/reader/grid.ts`, dat het weer uit leadingmangazoom
/// (KOReader) heeft. Het probleem dat het oplost is op een telefoon het
/// grootst: een mangapagina is daar leesbaar noch te overzien, dus zit je
/// constant in en uit te zoomen. Met een raster spring je per tik naar het
/// volgende paneelgebied, op ware grootte.
///
/// De leesrichting telt hier écht: bij manga loopt een rij van rechts naar
/// links, dus cel 0 zit rechtsboven. Vandaar eigen functies met eigen tests —
/// dit is precies het soort ding dat er op het scherm "bijna goed" uitziet.
struct Rastercel: Equatable, Sendable {
    /// Positie in het raster, vanaf linksboven geteld.
    let rij: Int
    let kolom: Int
}

struct Rastersprong: Equatable, Sendable {
    let schaal: Double
    /// Deel van de eigen breedte/hoogte dat de pagina opschuift (−0,5…0,5).
    let verschuifX: Double
    let verschuifY: Double
}

enum Raster {
    /// De cellen in leesvolgorde: rijen van boven naar beneden, en binnen een
    /// rij mee met de leesrichting.
    static func volgorde(rijen: Int, kolommen: Int, rechtsNaarLinks: Bool) -> [Rastercel] {
        var cellen: [Rastercel] = []
        for rij in 0..<max(0, rijen) {
            for stap in 0..<max(0, kolommen) {
                cellen.append(
                    Rastercel(rij: rij, kolom: rechtsNaarLinks ? kolommen - 1 - stap : stap)
                )
            }
        }
        return cellen
    }

    /// Hoe de pagina geschaald en verschoven moet worden om deze cel te vullen.
    ///
    /// De schaal is de grootste van beide richtingen: bij een raster van 2×3 wil
    /// je niet dat een cel horizontaal past maar verticaal half leeg blijft —
    /// dan lees je alsnog niets. Liever iets buiten beeld dan te klein.
    static func sprong(naar cel: Rastercel, rijen: Int, kolommen: Int) -> Rastersprong {
        guard rijen > 0, kolommen > 0 else {
            return Rastersprong(schaal: 1, verschuifX: 0, verschuifY: 0)
        }
        let schaal = Double(max(rijen, kolommen))
        let middenX = (Double(cel.kolom) + 0.5) / Double(kolommen)
        let middenY = (Double(cel.rij) + 0.5) / Double(rijen)
        return Rastersprong(
            schaal: schaal,
            verschuifX: 0.5 - middenX,
            verschuifY: 0.5 - middenY
        )
    }

    /// Welke cel hoort bij een tik op deze plek? Fracties van 0…1.
    static func cel(opX x: Double, y: Double, rijen: Int, kolommen: Int) -> Rastercel {
        func begrens(_ waarde: Double, _ maximum: Int) -> Int {
            min(maximum - 1, max(0, Int(waarde.rounded(.down))))
        }
        return Rastercel(
            rij: begrens(y * Double(rijen), rijen),
            kolom: begrens(x * Double(kolommen), kolommen)
        )
    }

    /// De plek van een cel in de leesvolgorde, of `nil` als hij er niet in zit.
    static func index(
        van cel: Rastercel, rijen: Int, kolommen: Int, rechtsNaarLinks: Bool
    ) -> Int? {
        volgorde(rijen: rijen, kolommen: kolommen, rechtsNaarLinks: rechtsNaarLinks)
            .firstIndex(of: cel)
    }
}
