import Foundation
import UIKit

/// Eén paneel, genormaliseerd op 0…1 ten opzichte van de hele pagina.
struct Paneel: Equatable, Sendable {
    let x0: Double
    let y0: Double
    let x1: Double
    let y1: Double

    var oppervlak: Double { max(0, x1 - x0) * max(0, y1 - y0) }

    /// Beslaat dit paneel praktisch de hele pagina? Dan viel er niets te
    /// snijden, en dat is bij een splash het juiste antwoord.
    var isHelePagina: Bool { oppervlak > 0.98 }

    static let helePagina = Paneel(x0: 0, y0: 0, x1: 1, y1: 1)

    /// Dit paneel met wat lucht eromheen.
    ///
    /// - Parameters:
    ///   - marge: als deel van de paginabréédte, zodat de instelling één getal
    ///     blijft.
    ///   - verhouding: hoogte gedeeld door breedte van de pagina. Verticaal moet
    ///     de marge namelijk kleiner zijn ín paginadelen om er even breed uit te
    ///     zien: op een pagina die anderhalf keer zo hoog is als breed, is 5%
    ///     van de breedte maar 3,3% van de hoogte.
    func metMarge(_ marge: Double, verhouding: Double) -> Paneel {
        guard marge > 0, verhouding > 0 else { return self }
        let verticaal = marge / verhouding
        return Paneel(
            x0: max(0, x0 - marge),
            y0: max(0, y0 - verticaal),
            x1: min(1, x1 + marge),
            y1: min(1, y1 + verticaal)
        )
    }
}

/// Panelen vinden zonder model, met dezelfde recursieve XY-cut als
/// `server/bookpal/images/panels.py`.
///
/// **Dit is een tweede implementatie van hetzelfde algoritme, en dat is een
/// risico.** De server is de bron: die rekent één keer, cachet het, en web en
/// Kobo krijgen hetzelfde antwoord. Deze kopie is de terugval voor als de
/// server het niet levert — offline, of een oudere server die het endpoint nog
/// niet kent. De constanten hieronder zijn daarom letterlijk dezelfde, en de
/// tests zijn gespiegeld aan `tests/test_panels.py`. Wijzig je er één, wijzig
/// dan allebei.
enum Panelen {
    static let achtergrondVanaf: UInt8 = 236
    /// Ruimer dan je zou denken, en dat is aan de serverkant gemeten: op 0,012
    /// bleef Oishinbo deel 3 hoofdstuk 26 pagina 2 op één paneel steken, omdat
    /// de goot daar een bijschrift en twee paneelaanzetten draagt. Met 0,05 én
    /// gootMinimum 0,008 vindt hij daar de juiste 4. Elk apart hielp niet.
    static let gootVulling = 0.05
    static let gootMinimum = 0.008
    static let paneelMinimum = 0.012
    static let maxDiepte = 6
    static let rekenbreedte = 700

    /// De panelen op deze pagina, in leesvolgorde. Minder dan twee betekent:
    /// de hele pagina.
    static func vind(in beeld: UIImage, rechtsNaarLinks: Bool) -> [Paneel] {
        guard let masker = Masker(beeld: beeld) else { return [Paneel.helePagina] }
        let stukken = snij(
            masker,
            vak: Vak(x0: 0, y0: 0, x1: masker.breedte, y1: masker.hoogte),
            diepte: 0,
            horizontaal: true
        )
        let panelen = stukken
            .map { vak in
                Paneel(
                    x0: Double(vak.x0) / Double(masker.breedte),
                    y0: Double(vak.y0) / Double(masker.hoogte),
                    x1: Double(vak.x1) / Double(masker.breedte),
                    y1: Double(vak.y1) / Double(masker.hoogte)
                )
            }
            .filter { $0.oppervlak >= paneelMinimum }

        guard panelen.count >= 2 else { return [Paneel.helePagina] }
        return leesvolgorde(panelen, rechtsNaarLinks: rechtsNaarLinks)
    }

    /// Van boven naar beneden, en binnen een rij mee met de leesrichting.
    ///
    /// Panelen die elkaar verticaal grotendeels overlappen horen bij dezelfde
    /// rij; zonder dat gooit een paneel dat een paar pixels hoger begint de hele
    /// volgorde om.
    static func leesvolgorde(_ panelen: [Paneel], rechtsNaarLinks: Bool) -> [Paneel] {
        guard !panelen.isEmpty else { return [] }
        var rijen: [[Paneel]] = []
        for paneel in panelen.sorted(by: { $0.y0 < $1.y0 }) {
            var geplaatst = false
            for index in rijen.indices {
                let onder = rijen[index].map(\.y1).min() ?? 0
                let boven = rijen[index].map(\.y0).max() ?? 0
                let hoogte = onder - boven
                let overlap = min(paneel.y1, onder) - max(paneel.y0, boven)
                if overlap > 0, overlap >= 0.5 * min(hoogte, paneel.y1 - paneel.y0) {
                    rijen[index].append(paneel)
                    geplaatst = true
                    break
                }
            }
            if !geplaatst { rijen.append([paneel]) }
        }
        return rijen.flatMap { rij in
            rij.sorted { rechtsNaarLinks ? $0.x0 > $1.x0 : $0.x0 < $1.x0 }
        }
    }

    // MARK: - Onderwater

    private struct Vak {
        let x0: Int
        let y0: Int
        let x1: Int
        let y1: Int
    }

    /// Per pixel: staat hier inkt? Verkleind, want goten zijn grof.
    private struct Masker {
        let inkt: [Bool]
        let breedte: Int
        let hoogte: Int

        init?(beeld: UIImage) {
            guard let cg = beeld.cgImage else { return nil }
            let schaal = cg.width > Panelen.rekenbreedte
                ? Double(Panelen.rekenbreedte) / Double(cg.width)
                : 1
            let breedte = max(1, Int(Double(cg.width) * schaal))
            let hoogte = max(1, Int(Double(cg.height) * schaal))

            var grijs = [UInt8](repeating: 255, count: breedte * hoogte)
            // `deviceGray` en niet `linearGray`: die laatste past een lineaire
            // transferfunctie toe, waardoor lichte tinten fors donkerder
            // uitkomen. Papier van 245 zakte daarmee tot onder de drempel en
            // dan is de hele pagina "inkt" — geen goten, geen panelen. PIL's
            // `convert("L")` aan de serverkant doet het gamma-gewogen, en de
            // twee implementaties moeten hetzelfde zien.
            guard let ruimte = CGColorSpace(name: CGColorSpace.genericGrayGamma2_2),
                  let context = CGContext(
                      data: &grijs,
                      width: breedte,
                      height: hoogte,
                      bitsPerComponent: 8,
                      bytesPerRow: breedte,
                      space: ruimte,
                      bitmapInfo: CGImageAlphaInfo.none.rawValue
                  )
            else { return nil }
            context.draw(cg, in: CGRect(x: 0, y: 0, width: breedte, height: hoogte))

            self.breedte = breedte
            self.hoogte = hoogte
            inkt = grijs.map { $0 < Panelen.achtergrondVanaf }
        }

        func heeftInkt(rij: Int, kolom: Int) -> Bool { inkt[rij * breedte + kolom] }
    }

    private static func snij(
        _ masker: Masker, vak: Vak, diepte: Int, horizontaal: Bool
    ) -> [Vak] {
        if diepte >= maxDiepte || vak.x1 - vak.x0 < 2 || vak.y1 - vak.y0 < 2 {
            return [krimp(masker, vak)]
        }
        var richting = horizontaal
        var grenzen = goten(masker, vak: vak, horizontaal: richting)
        if grenzen.isEmpty {
            // In deze richting valt niets te snijden; probeer de andere.
            richting.toggle()
            grenzen = goten(masker, vak: vak, horizontaal: richting)
            if grenzen.isEmpty { return [krimp(masker, vak)] }
        }
        return grenzen.flatMap { van, tot -> [Vak] in
            let deel = richting
                ? Vak(x0: vak.x0, y0: van, x1: vak.x1, y1: tot)
                : Vak(x0: van, y0: vak.y0, x1: tot, y1: vak.y1)
            return snij(masker, vak: deel, diepte: diepte + 1, horizontaal: !richting)
        }
    }

    private static func goten(
        _ masker: Masker, vak: Vak, horizontaal: Bool
    ) -> [(Int, Int)] {
        let lengte = horizontaal ? vak.y1 - vak.y0 : vak.x1 - vak.x0
        let dwars = horizontaal ? vak.x1 - vak.x0 : vak.y1 - vak.y0
        guard lengte >= 4, dwars >= 4 else { return [] }

        var gevuld = [Bool](repeating: false, count: lengte)
        for index in 0..<lengte {
            var inkt = 0
            if horizontaal {
                let rij = vak.y0 + index
                for kolom in vak.x0..<vak.x1 where masker.heeftInkt(rij: rij, kolom: kolom) {
                    inkt += 1
                }
            } else {
                let kolom = vak.x0 + index
                for rij in vak.y0..<vak.y1 where masker.heeftInkt(rij: rij, kolom: kolom) {
                    inkt += 1
                }
            }
            gevuld[index] = Double(inkt) / Double(dwars) > gootVulling
        }

        let minimum = max(2, Int(gootMinimum * Double(dwars)))
        var stukken: [(Int, Int)] = []
        var begin: Int?
        var leeg = 0
        for (index, vol) in gevuld.enumerated() {
            if vol {
                if begin == nil { begin = index }
                leeg = 0
            } else {
                leeg += 1
                if let start = begin, leeg >= minimum {
                    stukken.append((start, index - leeg + 1))
                    begin = nil
                }
            }
        }
        if let start = begin { stukken.append((start, lengte)) }

        // Eén stuk betekent: geen goot gevonden die iets scheidt.
        guard stukken.count >= 2 else { return [] }
        let verschuiving = horizontaal ? vak.y0 : vak.x0
        return stukken.map { (verschuiving + $0.0, verschuiving + $0.1) }
    }

    /// De lege rand rond een stuk weghalen, zodat het paneel strak zit.
    private static func krimp(_ masker: Masker, _ vak: Vak) -> Vak {
        var top = vak.y0
        var onder = vak.y1
        var links = vak.x0
        var rechts = vak.x1

        func rijHeeftInkt(_ rij: Int) -> Bool {
            (vak.x0..<vak.x1).contains { masker.heeftInkt(rij: rij, kolom: $0) }
        }
        func kolomHeeftInkt(_ kolom: Int) -> Bool {
            (top..<onder).contains { masker.heeftInkt(rij: $0, kolom: kolom) }
        }

        while top < onder, !rijHeeftInkt(top) { top += 1 }
        while onder > top, !rijHeeftInkt(onder - 1) { onder -= 1 }
        while links < rechts, !kolomHeeftInkt(links) { links += 1 }
        while rechts > links, !kolomHeeftInkt(rechts - 1) { rechts -= 1 }

        guard top < onder, links < rechts else { return vak }
        return Vak(x0: links, y0: top, x1: rechts, y1: onder)
    }
}

/// Waar je bent in de panelenstand: een pagina en een paneel daarbinnen.
///
/// Vooruit en terug lopen over de paginagrens heen — na het laatste paneel van
/// een pagina komt het eerste van de volgende, en terug precies andersom. Dat
/// laatste is het stukje dat je vergeet: terugtikken hoort op het *laatste*
/// paneel van de vorige pagina uit te komen, niet op het eerste, want je leest
/// hem achterstevoren in.
struct Paneelpad: Equatable {
    var pagina: Int
    var paneel: Int

    /// Het overzicht: de hele pagina, vóór je in paneel 1 duikt. Elke pagina
    /// begint hier — je wilt eerst zien hoe de bladzijde in elkaar zit voordat
    /// je inzoomt, net als wanneer je een strip op papier omslaat.
    static let overzicht = -1

    var isOverzicht: Bool { paneel == Paneelpad.overzicht }

    /// - Parameter aantal: hoeveel panelen elke pagina heeft. Een pagina die nog
    ///   niet onderzocht is telt als één, zodat je nooit vastloopt op iets dat
    ///   nog moet laden.
    func volgende(aantal: (Int) -> Int, paginas: Int) -> Paneelpad? {
        if paneel + 1 < aantal(pagina) {
            return Paneelpad(pagina: pagina, paneel: paneel + 1)
        }
        guard pagina + 1 < paginas else { return nil }
        return Paneelpad(pagina: pagina + 1, paneel: Paneelpad.overzicht)
    }

    func vorige(aantal: (Int) -> Int) -> Paneelpad? {
        if paneel > Paneelpad.overzicht {
            return Paneelpad(pagina: pagina, paneel: paneel - 1)
        }
        guard pagina > 0 else { return nil }
        // Terug hoort op het láátste paneel van de vorige pagina uit te komen,
        // niet op het overzicht: je leest die pagina achterstevoren in.
        return Paneelpad(pagina: pagina - 1, paneel: max(0, aantal(pagina - 1) - 1))
    }
}
