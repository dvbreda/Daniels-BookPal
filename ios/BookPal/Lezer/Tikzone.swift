import Foundation

/// Wat een tik op de pagina doet, afhankelijk van waar je tikt.
///
/// Links terug, rechts verder — en bij manga precies andersom, want daar loopt
/// het verhaal van rechts naar links. Dat is dezelfde regel als voor het vegen,
/// en hem hier vergeten is precies de fout die je pas merkt als je een manga
/// leest: elke tik brengt je dan een pagina de verkeerde kant op.
///
/// In het midden gebeurt er niets met de pagina maar gaat de balk aan of uit.
/// Die strook moet breed genoeg zijn om te raken zonder te mikken, en smal
/// genoeg om niet in de weg te zitten bij het bladeren.
enum Tikzone: Equatable {
    case vorige
    case volgende
    case balk

    /// Hoeveel van de breedte de middenstrook inneemt.
    static let middenDeel = 0.34

    /// - Parameters:
    ///   - x: waar je tikte, als fractie van de breedte (0 = links).
    ///   - rechtsNaarLinks: leest dit boek van rechts naar links?
    static func voor(x: Double, rechtsNaarLinks: Bool) -> Tikzone {
        let rand = (1 - middenDeel) / 2
        if x > rand && x < 1 - rand { return .balk }
        let linkerkant = x <= rand
        // Bij een westerse strip is links terug; bij manga is links juist
        // verder, want daar begint de pagina rechts.
        if linkerkant { return rechtsNaarLinks ? .volgende : .vorige }
        return rechtsNaarLinks ? .vorige : .volgende
    }
}

/// De rastervormen die je kunt kiezen.
///
/// Meer dan de drie waarmee dit begon: een pagina met brede stroken wil 2×1,
/// een dichte mangapagina 3×3. Het aantal cellen is wat je per tik doorloopt,
/// dus dit is echt een leesinstelling en niet alleen een zoomfactor.
struct Rastervorm: Identifiable, Hashable, Sendable {
    let rijen: Int
    let kolommen: Int

    var id: String { "\(rijen)x\(kolommen)" }
    var naam: String { "\(rijen)×\(kolommen)" }
    var cellen: Int { rijen * kolommen }

    static let uit = Rastervorm(rijen: 0, kolommen: 0)

    static let keuzes = [
        Rastervorm(rijen: 2, kolommen: 1),
        Rastervorm(rijen: 1, kolommen: 2),
        Rastervorm(rijen: 2, kolommen: 2),
        Rastervorm(rijen: 3, kolommen: 2),
        Rastervorm(rijen: 2, kolommen: 3),
        Rastervorm(rijen: 3, kolommen: 3),
        Rastervorm(rijen: 4, kolommen: 2),
    ]

    /// De volgende vorm in de rij, met "uit" ertussen. Voor de knop in de balk,
    /// die je zonder het paneel te openen door de standen laat lopen.
    static func volgende(na huidige: Rastervorm) -> Rastervorm {
        guard let index = keuzes.firstIndex(of: huidige) else { return keuzes[0] }
        return index + 1 < keuzes.count ? keuzes[index + 1] : .uit
    }
}
