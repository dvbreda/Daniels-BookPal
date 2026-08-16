import Foundation

/// Welke pagina's samen op één scherm komen.
///
/// Dit is bewust dezelfde redenering als `web/src/reader/spreads.ts`, met
/// dezelfde drie regels en dezelfde tests. Ze uit elkaar laten lopen zou
/// betekenen dat een album op de telefoon anders is opgedeeld dan in de
/// browser, en dan wijst "pagina 12" op twee apparaten niet meer hetzelfde aan:
///
/// 1. De omslag staat altijd alleen — anders loopt de rest van het boek één
///    pagina uit de pas, want in een gedrukt album staat pagina 1 rechts.
/// 2. Een liggende pagina is een uitklapper of dubbelpagina en vult het scherm
///    alleen.
/// 3. Twee staande pagina's naast elkaar, maar nooit een staande naast een
///    liggende.
///
/// De verhoudingen komen pas binnen zodra een beeld geladen is; tot die tijd
/// gaan we uit van staand, wat voor vrijwel elke stripbladzijde klopt.
enum Spreads {
    static let liggendVanaf = 1.0

    static func isLiggend(_ verhouding: Double?) -> Bool {
        guard let verhouding else { return false }
        return verhouding > liggendVanaf
    }

    /// - Parameters:
    ///   - verhoudingen: breedte/hoogte per pagina-index, voor zover al bekend.
    ///   - omslagAlleen: uit bij webtoons, waar geen omslagconventie geldt.
    static func bouw(
        paginas: Int,
        dubbel: Bool,
        verhoudingen: [Int: Double],
        omslagAlleen: Bool = true
    ) -> [[Int]] {
        guard paginas > 0 else { return [] }
        if !dubbel { return (0..<paginas).map { [$0] } }

        var spreads: [[Int]] = []
        var index = 0

        if omslagAlleen {
            spreads.append([0])
            index = 1
        }

        while index < paginas {
            if isLiggend(verhoudingen[index]) {
                spreads.append([index])
                index += 1
                continue
            }
            let volgende = index + 1
            if volgende < paginas, !isLiggend(verhoudingen[volgende]) {
                spreads.append([index, volgende])
                index += 2
                continue
            }
            spreads.append([index])
            index += 1
        }

        return spreads
    }

    /// In welke spread zit een pagina? Nodig om na een moduswissel op dezelfde
    /// plek te blijven staan in plaats van naar het begin te springen.
    static func spreadVanPagina(_ spreads: [[Int]], pagina: Int) -> Int {
        spreads.firstIndex { $0.contains(pagina) } ?? 0
    }

    /// De leesvolgorde binnen een spread.
    ///
    /// Bij manga leest de rechterpagina eerst, dus die moet links in beeld
    /// gespiegeld worden. Dit is precies wat een generieke fotoviewer niet doet
    /// en waarom manga daarin altijd verkeerd om aanvoelt.
    static func volgordeVoorScherm(_ spread: [Int], rechtsNaarLinks: Bool) -> [Int] {
        rechtsNaarLinks ? spread.reversed() : spread
    }

    /// Welke pagina's alvast ophalen.
    static func vooruitLaden(_ spreads: [[Int]], huidige: Int, vooruit: Int) -> [Int] {
        var paginas: [Int] = []
        for stap in 1...max(vooruit, 1) {
            let index = huidige + stap
            guard spreads.indices.contains(index) else { break }
            paginas.append(contentsOf: spreads[index])
        }
        // Eén spread terug, zodat terugbladeren ook direct is.
        let terug = huidige - 1
        if spreads.indices.contains(terug) {
            paginas.append(contentsOf: spreads[terug])
        }
        return paginas
    }

    /// Hoe ver je bent, gerekend op de láátste pagina van de spread.
    ///
    /// Exact dezelfde som als `percentFor` in de web-lezer, en dat is hier geen
    /// nettigheid maar een eis: beide schrijven naar hetzelfde
    /// voortgang-endpoint. Rekende de app het anders, dan zou dezelfde plek in
    /// hetzelfde boek op de telefoon een ander percentage geven dan in de
    /// browser, en zou "verder lezen" heen en weer springen tussen apparaten.
    static func percentVoor(_ spreads: [[Int]], spreadIndex: Int, paginas: Int) -> Double {
        guard paginas > 0, spreads.indices.contains(spreadIndex) else { return 0 }
        let spread = spreads[spreadIndex]
        guard let laatste = spread.max() else { return 0 }
        return min(100, (Double(laatste + 1) / Double(paginas) * 100).rounded())
    }
}
