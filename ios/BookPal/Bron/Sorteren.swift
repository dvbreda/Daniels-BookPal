import Foundation

/// Waarop de bibliotheek gesorteerd staat.
///
/// Dezelfde namen als de server (`?sort=`), want de volgorde wordt daar
/// bepaald: op verschijningsjaar sorteert een serie op haar nieuwste deel, en
/// dat is een `max()` over alle delen — niets wat je in de client wilt
/// nabouwen op een lijst die maar één pagina diep is.
enum Sortering: String, CaseIterable, Identifiable, Sendable {
    case naam
    case verschenen
    case toegevoegd

    var id: String { rawValue }

    var naamgeving: String {
        switch self {
        case .naam: return "Naam"
        case .verschenen: return "Verschenen"
        case .toegevoegd: return "Toegevoegd"
        }
    }

    var icoon: String {
        switch self {
        case .naam: return "textformat.abc"
        case .verschenen: return "calendar"
        case .toegevoegd: return "clock.arrow.circlepath"
        }
    }

    /// Wat er standaard past bij deze categorie. Bij een tijdschrift wil je
    /// het nieuwste nummer bovenaan; bij je strips is de reeksnaam handiger,
    /// want daar zoek je op titel en niet op jaargang.
    static func standaard(voor groep: Soortfilter) -> Sortering {
        switch groep {
        case .tijdschriften, .print: return .verschenen
        case .alles, .boeken, .strips, .manga: return .naam
        }
    }
}
