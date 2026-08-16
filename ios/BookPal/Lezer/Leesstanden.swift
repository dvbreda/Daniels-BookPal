import SwiftUI
import UIKit

/// De standen van de stripleer, met dezelfde namen en betekenis als in
/// `web/src/reader/ComicReader.tsx`. Gelijk houden is geen nettigheid: je leest
/// hetzelfde boek op allebei, en een "dubbel" dat hier iets anders doet dan in
/// de browser is verwarrender dan geen dubbel.

/// Pagina voor pagina, of doorlopend scrollen.
enum Weergavestand: String, CaseIterable, Identifiable {
    case paginas
    case doorlopend
    /// Paneel voor paneel, op ware grootte. Op een telefoon is dit wat een
    /// mangapagina leesbaar maakt zonder dat je zit te knijpen: de panelen
    /// worden zonder model gevonden (zie `Panelen`), dus het werkt op elke
    /// pagina en niet alleen waar iemand ze heeft ingetekend.
    case panelen

    var id: String { rawValue }

    var naam: String {
        switch self {
        case .paginas: return "Pagina's"
        case .doorlopend: return "Doorlopend"
        case .panelen: return "Panelen"
        }
    }

    var icoon: String {
        switch self {
        case .paginas: return "book.pages"
        case .doorlopend: return "arrow.up.and.down"
        case .panelen: return "squareshape.split.2x2"
        }
    }

    /// Wat een dubbeltik op de pagina doet: heen en weer tussen paneelzoom en
    /// doorlopend.
    ///
    /// Die twee zijn de uitersten van hoe je een strip leest — helemaal
    /// inzoomen op één paneel, of alles achter elkaar door. Daar wil je snel
    /// tussen kunnen, zonder een menu. Sta je in de paginastand, dan brengt de
    /// eerste dubbeltik je naar de panelen.
    var naDubbeltik: Weergavestand {
        self == .panelen ? .doorlopend : .panelen
    }

    /// De volgende stand, rondlopend. De knop in de leesbalk loopt hiermee door
    /// alle drie: panelen zijn een gewone leesstand, geen instelling die je in
    /// een paneel moet gaan zoeken.
    var volgende: Weergavestand {
        let alle = Weergavestand.allCases
        guard let index = alle.firstIndex(of: self) else { return .paginas }
        return alle[(index + 1) % alle.count]
    }
}

/// Hoe de pagina in het scherm gezet wordt.
///
/// Bij een webtoon wil je breedte, bij een gewone bladzijde hoogte, en
/// "passend" laat hem helemaal zien. Op een telefoon is dat verschil groot
/// genoeg om het te kunnen omzetten.
enum Passend: String, CaseIterable, Identifiable {
    case breedte
    case hoogte
    case scherm

    var id: String { rawValue }

    var naam: String {
        switch self {
        case .breedte: return "Breedte"
        case .hoogte: return "Hoogte"
        case .scherm: return "Passend"
        }
    }

    var contentMode: UIView.ContentMode {
        switch self {
        // Vullen en bijsnijden: de pagina raakt de zijkanten, de rest valt
        // buiten beeld en is er met slepen bij te halen.
        case .breedte, .hoogte: return .scaleAspectFill
        case .scherm: return .scaleAspectFit
        }
    }
}

/// Bewerkingen die de server op de pagina uitvoert vóór hij hem stuurt.
///
/// Server-side en niet op het toestel, want het beeld wordt daar toch al
/// klaargemaakt en het resultaat is meteen gecachet — hetzelfde argument als bij
/// de beeldprofielen.
struct Beeldbewerking: Equatable {
    /// Egale rand rond de pagina wegsnijden. Scheelt op een klein scherm zo een
    /// vijfde van de hoogte.
    var bijsnijden = false
    /// 100 is onbewerkt; hoger rekt het grijsbereik op voor bleke scans.
    var contrast = 100

    var queryItems: [URLQueryItem] {
        var items: [URLQueryItem] = []
        if bijsnijden { items.append(URLQueryItem(name: "crop", value: "true")) }
        if contrast != 100 { items.append(URLQueryItem(name: "contrast", value: String(contrast))) }
        return items
    }

    /// Onderdeel van de cachesleutel: dezelfde pagina met bijsnijden aan is een
    /// ander beeld, en zonder dit zou de oude versie blijven staan.
    var sleutel: String { "\(bijsnijden)-\(contrast)" }
}
