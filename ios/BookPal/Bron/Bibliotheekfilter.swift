import Foundation

/// Waarop de bibliotheek gefilterd staat.
///
/// Drie lagen, en dat is geen dubbeling.
///
/// De **groep** is de bijl: boeken, strips of manga, dezelfde vier woorden als
/// op de startpagina. Die staat bovenaan en snijdt overal doorheen — ook door
/// een gekozen tab, want "manga" is niet iets waar je een tab voor opgeeft.
///
/// Een **tab** is een opgeslagen regel uit de web-app die op de server naar een
/// query compileert — daar zit de regelbouwer, en die willen we hier niet
/// nabouwen.
///
/// De **losse filters** zijn wat je tijdens het bladeren even omzet zonder dat
/// je er een tab voor wilt maken. Kiezen voor een tab zet die uit en andersom,
/// want díe twee combineren niet: de server kent maar één van beide paden per
/// verzoek. De groep gaat als losse parameter met allebei die paden mee.
struct Bibliotheekfilter: Equatable {
    var groep: Soortfilter = .alles
    var tabID: Int?
    var soort: BookKind?
    var herkomst: Herkomst?
    var rootID: Int?

    static let alles = Bibliotheekfilter()

    var isLeeg: Bool { self == .alles }

    /// Hoeveel losse filters er aanstaan — voor het bolletje op de filterknop.
    /// De groep telt niet mee: die zie je al als balk staan.
    var aantalLos: Int {
        [soort != nil, herkomst != nil, rootID != nil].filter { $0 }.count
    }

    mutating func kiesTab(_ id: Int?) {
        tabID = id
        soort = nil
        herkomst = nil
        rootID = nil
    }

    mutating func wisLos() {
        soort = nil
        herkomst = nil
        rootID = nil
    }
}
