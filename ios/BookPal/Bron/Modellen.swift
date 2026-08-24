import Foundation

/// De vorm waarin de server lijsten teruggeeft.
struct Paginated<T: Codable & Sendable>: Codable, Sendable {
    let items: [T]
    let total: Int
    let offset: Int
    let limit: Int
}

/// Hoe een boek gelezen wordt — niet per se de bestandsextensie. Deze drie zijn
/// wat `BookKind` op de server kent; manga valt onder `comic`.
enum BookKind: String, Codable, Sendable {
    case comic
    case epub
    case pdf

    /// Kan de stripleer hier pagina's van tonen?
    ///
    /// Een epub heeft geen vaste pagina's — de server antwoordt daar met 409 en
    /// verwijst naar `/file`. Dat is een aparte lezer (M6 op het web), dus hier
    /// blijft het voorlopig bij het herkennen ervan.
    var hasFixedPages: Bool {
        self != .epub
    }
}

/// Eén waarde uit de vrije JSON van een leespositie.
///
/// Die positie is bewust niet één vaste vorm: voor een strip staat er
/// `{"page": 12}` in, voor een epub een CFI als tekst. Een model dat alleen
/// getallen aankan liet daardoor élke serie met een epub erin op een foutmelding
/// stuklopen — één onleesbaar veld gooit in Swift de hele decode om, niet alleen
/// dat ene boek.
enum JSONWaarde: Codable, Sendable {
    case getal(Int)
    case tekst(String)
    case anders

    init(from decoder: Decoder) throws {
        let waarde = try decoder.singleValueContainer()
        if let getal = try? waarde.decode(Int.self) {
            self = .getal(getal)
        } else if let tekst = try? waarde.decode(String.self) {
            self = .tekst(tekst)
        } else {
            self = .anders
        }
    }

    /// Alleen nodig om de offline-momentopname terug te kunnen schrijven
    /// (`Bibliotheekcache`); de server krijgt deze waarde nooit terug — die
    /// route stuurt altijd een verse positie, geen oude uit deze enum.
    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case let .getal(getal): try container.encode(getal)
        case let .tekst(tekst): try container.encode(tekst)
        case .anders: try container.encodeNil()
        }
    }
}

struct Progress: Codable, Sendable {
    let position: [String: JSONWaarde]
    let percent: Double
    let finished: Bool
    let device: String?
    let updatedAt: Date

    /// Op welke pagina je gebleven bent. Een epub heeft geen paginanummer maar
    /// een CFI; die is voor de stripleer niet bruikbaar, dus dan begin je
    /// vooraan.
    var page: Int {
        if case let .getal(nummer) = position["page"] { return nummer }
        return 0
    }

    enum CodingKeys: String, CodingKey {
        case position, percent, finished, device
        case updatedAt = "updated_at"
    }
}

struct Series: Codable, Sendable, Identifiable {
    let id: Int
    let title: String
    let sortTitle: String
    let originRegion: String
    let publisher: String?
    let authors: [String]
    let tags: [String]
    let summary: String?
    let bookCount: Int
    let fromSource: Bool
    let hasCoverURL: Bool

    enum CodingKeys: String, CodingKey {
        case id, title, publisher, authors, tags, summary
        case sortTitle = "sort_title"
        case originRegion = "origin_region"
        case bookCount = "book_count"
        case fromSource = "from_source"
        case hasCoverURL = "has_cover_url"
    }
}

struct Book: Codable, Sendable, Identifiable, Hashable {
    let id: Int
    let seriesID: Int
    let kind: BookKind
    let title: String
    let number: String?
    let volume: String?
    let pageCount: Int?
    let rightToLeft: Bool
    let hasFile: Bool
    let fromSource: Bool
    let extensionName: String?
    /// Wanneer dit verscheen, uit de bestandsnaam. Los van wanneer jij het
    /// binnenhaalde — bij een tijdschrift is dit wat het nummer ís.
    let publishedYear: Int?
    let publishedMonth: Int?
    let progress: Progress?
    let editionName: String?
    let editionLanguage: String?
    let editionNote: String?

    /// Hoe dit hoofdstuk in een lijst heet: "Deel 3, hoofdstuk 12 — Titel".
    var label: String {
        var delen: [String] = []
        if let volume { delen.append("Deel \(volume)") }
        if let number { delen.append("hoofdstuk \(number)") }
        let nummering = delen.joined(separator: ", ")
        if nummering.isEmpty { return title }
        return title.isEmpty ? nummering : "\(nummering) — \(title)"
    }

    /// Waarin deze uitgave zich onderscheidt, als er meer dan één is.
    var editionLabel: String? {
        var delen: [String] = []
        if let editionLanguage { delen.append(editionLanguage.uppercased()) }
        if let editionNote { delen.append(editionNote) }
        return delen.isEmpty ? nil : delen.joined(separator: " · ")
    }

    var isReadable: Bool { hasFile && kind.hasFixedPages && (pageCount ?? 0) > 0 }

    /// "september 2026", "1989", of niets. Kort, want dit staat onder een
    /// omslag in een raster waar geen ruimte is voor een volzin.
    var verschenen: String? {
        guard let jaar = publishedYear else { return nil }
        guard let maand = publishedMonth, (1...12).contains(maand) else { return String(jaar) }
        let namen = ["jan", "feb", "mrt", "apr", "mei", "jun",
                     "jul", "aug", "sep", "okt", "nov", "dec"]
        return "\(namen[maand - 1]) \(jaar)"
    }

    // Op id vergelijken en hashen: de rest van de velden verandert (voortgang!)
    // zonder dat het een ander boek wordt, en navigatie hoort daar niet op te
    // reageren.
    static func == (links: Book, rechts: Book) -> Bool { links.id == rechts.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }

    enum CodingKeys: String, CodingKey {
        case id, kind, title, number, volume, progress
        case seriesID = "series_id"
        case pageCount = "page_count"
        case rightToLeft = "right_to_left"
        case hasFile = "has_file"
        case fromSource = "from_source"
        case extensionName = "extension"
        case publishedYear = "published_year"
        case publishedMonth = "published_month"
        case editionName = "edition_name"
        case editionLanguage = "edition_language"
        case editionNote = "edition_note"
    }
}

struct SeriesDetail: Decodable, Sendable {
    let id: Int
    let title: String
    let summary: String?
    let books: [Book]
}

/// Eén tekstvlak uit een vertaalde pagina.
///
/// `box` is genormaliseerd op 0…1 ten opzichte van de hele pagina, zodat
/// dezelfde vertaling over elk beeldprofiel past — web, Kobo en telefoon hebben
/// alle drie een andere afmeting.
struct Bubble: Decodable, Sendable, Identifiable {
    let box: [Double]
    let source: String
    let translation: String
    let kind: String
    let bold: Bool
    let italic: Bool

    var id: String { "\(box)-\(translation)" }

    /// Striplettering staat traditioneel vol in kapitalen. Of dat hier ook zo
    /// is, staat al in de brontekst — dat hoeft het model niet te vertellen.
    var kapitalen: Bool {
        let letters = source.filter(\.isLetter)
        guard letters.count >= 3 else { return false }
        return letters.allSatisfy(\.isUppercase)
    }

    var tekst: String { kapitalen ? translation.uppercased() : translation }

    /// Een korte uitroep of geluidseffect in plaats van een zin. Bepaalt of het
    /// vlak de ballon mag vullen en of het vet gezet wordt.
    var isKreet: Bool { tekst.count <= Ballonnen.kreetTot }
}

struct PageTranslation: Decodable, Sendable {
    let bookID: Int
    let pageIndex: Int
    let targetLang: String
    let provider: String
    let bubbles: [Bubble]
    /// In de beeldstanden is de hele pagina hertekend in plaats van dat er
    /// vlakken over het origineel gaan. De lezer moet dat weten: hij toont dan
    /// een andere afbeelding, en er valt niet op een ballon te tikken.
    let mode: String
    let fullPage: Bool

    enum CodingKeys: String, CodingKey {
        case provider, bubbles, mode
        case bookID = "book_id"
        case pageIndex = "page_index"
        case targetLang = "target_lang"
        case fullPage = "full_page"
    }
}

/// Wat er qua kleur voor deze pagina klaarligt.
struct ColourInfo: Decodable, Sendable {
    let available: Bool
    /// Van de tekenaar zelf: dan valt er niets in te kleuren, en dat is iets
    /// anders dan "nog niet gedaan".
    let native: Bool
    /// Zit de vertaling in dit beeld gebakken? Dan is dít de versie die je wilt
    /// zien als kleur en vertaling allebei aanstaan.
    let translated: Bool
}

struct ServerHealth: Decodable, Sendable {
    let status: String
    let version: String
    let series: Int
    let books: Int
}

/// Wat de server terugstuurt als er iets misgaat: FastAPI zet de uitleg in
/// `detail`. Die tonen we letterlijk — de server legt beter uit wat er aan de
/// hand is dan een algemene "er ging iets mis".
struct ServerFout: Decodable, Sendable {
    let detail: String
}

/// Een opgeslagen tab uit de web-app: naam, icoon en een regel die de server
/// naar een query compileert. De app toont ze als filter en laat de regel zelf
/// met rust — die maak je in de web-app, waar een regelbouwer voor is.
struct Bibliotheektab: Decodable, Sendable, Identifiable {
    let id: Int
    let name: String
    let icon: String?
    let position: Int
    let enabled: Bool
}

/// Waar de bibliotheek op te filteren valt, buiten de tabs om.
enum Herkomst: String, CaseIterable, Identifiable, Sendable {
    case europe, japan, korea, china, us, other, unknown

    var id: String { rawValue }

    var naam: String {
        switch self {
        case .europe: return "Europa"
        case .japan: return "Japan"
        case .korea: return "Korea"
        case .china: return "China"
        case .us: return "VS"
        case .other: return "Overig"
        case .unknown: return "Onbekend"
        }
    }
}

struct LibraryRoot: Decodable, Sendable, Identifiable {
    let id: Int
    let path: String
    let enabled: Bool

    /// Alleen het laatste stuk van het pad: "/library/manga" wordt "manga".
    var naam: String { (path as NSString).lastPathComponent }
}

struct Beeldprofiel: Decodable, Sendable, Identifiable {
    let name: String
    let maxWidth: Int?
    let format: String
    let grayscale: Bool

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, format, grayscale
        case maxWidth = "max_width"
    }
}

/// De vertaalstanden zoals de server ze kent, met de prijs per pagina.
struct Vertaalinstellingen: Decodable, Sendable {
    let mode: String
    let buttonMode: String
    let colourMode: String
    let configured: Bool
    let costs: [String: Double]

    enum CodingKeys: String, CodingKey {
        case mode, configured, costs
        case buttonMode = "button_mode"
        case colourMode = "colour_mode"
    }

    static func naam(_ stand: String) -> String {
        switch stand {
        case "text": return "Tekstvlakken"
        case "image_fast": return "Ingetekend (snel)"
        case "image_pro": return "Ingetekend (zwaar)"
        default: return stand
        }
    }
}

/// Wat een klus voor dit hoofdstuk gaat inhouden, vóór je hem start.
///
/// Met de prijs erbij, want dit is de enige knop in de app die met één druk een
/// heel hoofdstuk kost. Zonder bedrag is dat een gok.
struct Batchplan: Decodable, Sendable {
    let kind: String
    let mode: String
    let pages: Int
    let pricePerPage: Double
    let total: Double
    /// Batchwerk kost bij Google de helft van een gewone aanroep. Apart, zodat
    /// de lezer kan tonen dát dit het batchtarief is in plaats van te
    /// suggereren dat het het normale is.
    let batchFactor: Double

    enum CodingKeys: String, CodingKey {
        case kind, mode, pages, total
        case pricePerPage = "price_per_page"
        case batchFactor = "batch_factor"
    }
}

struct Batchstatus: Decodable, Sendable {
    let kind: String
    let bookID: Int
    let mode: String
    let state: String
    let done: Int
    let total: Int
    let failed: Int
    let error: String?

    /// De server schrijft zijn standen in het Nederlands: `bezig`, `klaar`,
    /// `mislukt`. Hier stond eerst "running"/"pending" — een Engelse gok, en
    /// daardoor gold een lopende klus altijd als klaar: geen balk, geen
    /// voortgang, en de tekst eronder zei dat je kon bladeren terwijl hij nog
    /// bezig was.
    var loopt: Bool { state == "bezig" }

    var mislukt: Bool { state == "mislukt" }

    /// In gewone taal, want "klaar" met één mislukte pagina is niet hetzelfde
    /// als klaar.
    var samenvatting: String {
        if loopt { return "bezig — \(done) van \(total)" }
        if mislukt { return "mislukt" }
        if failed > 0 { return "klaar, \(failed) van \(total) mislukt" }
        return "klaar"
    }

    enum CodingKeys: String, CodingKey {
        case kind, mode, state, done, total, failed, error
        case bookID = "book_id"
    }
}

/// Wat een betaalde klus gaat kosten, in gewone taal.
enum Kosten {
    static func tekst(_ bedrag: Double) -> String {
        bedrag.formatted(.currency(code: "USD").precision(.fractionLength(bedrag < 0.1 ? 3 : 2)))
    }
}

/// Of er voor deze pagina een ingekleurde versie klaarstaat.
struct PageColour: Decodable, Sendable {
    let bookID: Int
    let pageIndex: Int
    let available: Bool

    enum CodingKeys: String, CodingKey {
        case available
        case bookID = "book_id"
        case pageIndex = "page_index"
    }
}

/// Waar je verder leest in deze serie.
struct VerderLezen: Decodable, Sendable {
    let bookID: Int
    let title: String
    let number: String?
    let page: Int
    /// Ga je verder in iets dat je al begonnen was, of begin je aan een nieuw
    /// hoofdstuk? Bepaalt of de knop "Lees verder" of "Beginnen" heet.
    let resuming: Bool
    /// Staat dit hoofdstuk al op de NAS? Zo niet, dan moet het eerst opgehaald.
    let hasFile: Bool
    /// Hoeveel hoofdstukken hiervóór nog niet uitgelezen zijn — precies wat
    /// "markeer vorige als gelezen" zou opruimen.
    let unreadBefore: Int

    enum CodingKeys: String, CodingKey {
        case title, number, page, resuming
        case bookID = "book_id"
        case hasFile = "has_file"
        case unreadBefore = "unread_before"
    }
}

/// Eén tegel op de startpagina: genoeg om te tonen en te openen.
struct HomeItem: Codable, Sendable, Identifiable {
    let bookID: Int
    let seriesID: Int
    let seriesTitle: String
    let title: String
    let number: String?
    let volume: String?
    let kind: BookKind
    /// De herkomst van de serie. Optioneel, want oudere servers sturen hem nog
    /// niet mee — dan valt de indeling terug op "alles" in plaats van de app te
    /// laten struikelen.
    let originRegion: String?
    let hasFile: Bool
    let pageCount: Int?
    let percent: Double
    let finished: Bool
    /// De pagina waar je gebleven was; de lezer opent hier.
    let page: Int

    var id: Int { bookID }

    var ondertitel: String {
        var delen: [String] = []
        if let volume { delen.append("deel \(volume)") }
        if let number { delen.append("hfst. \(number)") }
        return delen.isEmpty ? title : delen.joined(separator: ", ")
    }

    enum CodingKeys: String, CodingKey {
        case title, number, volume, kind, percent, finished, page
        case bookID = "book_id"
        case seriesID = "series_id"
        case seriesTitle = "series_title"
        case originRegion = "origin_region"
        case hasFile = "has_file"
        case pageCount = "page_count"
    }
}

/// De grove indeling: boeken, strips, manga.
///
/// Grover dan de tabs in de bibliotheek, en dat is de bedoeling. Hier wil je met
/// één duim langs wat je aan het lezen bent; de fijnmazige regels staan in de
/// tabs, die je in de web-app maakt.
///
/// Staat op de startpagina én boven de bibliotheek, met dezelfde vier woorden.
/// De uitkomst komt alleen langs een andere weg: op de startpagina schiften we
/// een lijstje van tien tegels na met `past`, in de bibliotheek filtert de
/// server met `query`. Dat moet ook wel — daar zit een limiet op de pagina, en
/// dan laat naschiften stilletjes series wegvallen.
enum Soortfilter: String, CaseIterable, Identifiable, Sendable {
    case alles, boeken, strips, manga, tijdschriften, print

    var id: String { rawValue }

    /// De naam die de server kent (`?group=`), of niets bij "alles".
    var query: String? { self == .alles ? nil : rawValue }

    var naam: String {
        switch self {
        case .alles: return "Alles"
        case .boeken: return "Boeken"
        case .strips: return "Strips"
        case .manga: return "Manga"
        case .tijdschriften: return "Tijdschriften"
        case .print: return "Drukwerk"
        }
    }

    /// Manga en strips zijn allebei `comic`; alleen de herkomst scheidt ze. Komt
    /// die niet mee (oudere server), dan tonen we het item liever wél dan het
    /// stilletjes weg te laten.
    func past(_ item: HomeItem) -> Bool {
        switch self {
        case .alles:
            return true
        case .boeken:
            return item.kind != .comic
        case .strips:
            return item.kind == .comic && item.originRegion != "japan"
        case .manga:
            return item.kind == .comic && item.originRegion == "japan"
        case .tijdschriften, .print:
            // Deze twee hangen aan de bibliotheekmap, en die staat niet op een
            // starttegel. Op de startpagina schiften we dus niet: wat je aan
            // het lezen bent hoort er sowieso te staan. In de bibliotheek doet
            // de server het wél, met `query`.
            return true
        }
    }
}

struct HomeRail: Codable, Sendable, Identifiable {
    let key: String
    let title: String
    let items: [HomeItem]

    var id: String { key }
}

struct Home: Codable, Sendable {
    /// Lege rails komen niet mee: een kop zonder inhoud is ruis.
    let rails: [HomeRail]
}

/// De panelen van één pagina, zoals de server ze vond.
struct PanelsAntwoord: Decodable, Sendable {
    struct Vak: Decodable, Sendable {
        let box: [Double]
    }

    let panels: [Vak]
    /// Eén paneel over de hele pagina: hier viel niets te snijden. Bij een
    /// splash is dat het juiste antwoord.
    let wholePage: Bool

    enum CodingKeys: String, CodingKey {
        case panels
        case wholePage = "whole_page"
    }

    var panelen: [Paneel] {
        panels.compactMap { vak in
            guard vak.box.count == 4 else { return nil }
            return Paneel(x0: vak.box[0], y0: vak.box[1], x1: vak.box[2], y1: vak.box[3])
        }
    }
}

/// Het volgende hoofdstuk, om aan te bieden als je er een uit hebt.
struct VolgendHoofdstuk: Decodable, Sendable {
    let bookID: Int
    let title: String
    let number: String?
    let volume: String?
    /// Al binnen, of moet het nog opgehaald worden? Bepaalt of de knop meteen
    /// opent of eerst iets moet doen.
    let hasFile: Bool

    var label: String {
        var delen: [String] = []
        if let volume { delen.append("deel \(volume)") }
        if let number { delen.append("hoofdstuk \(number)") }
        let nummering = delen.joined(separator: ", ")
        return nummering.isEmpty ? title : "\(nummering) — \(title)"
    }

    enum CodingKeys: String, CodingKey {
        case title, number, volume
        case bookID = "book_id"
        case hasFile = "has_file"
    }
}

/// Eén bewaard stuk betaald werk, zoals het op de NAS op schijf staat.
/// Zie `bookpal.api.sidecars` — dezelfde vorm, voor het synchroniseren.
struct SidecarRegel: Codable, Sendable {
    let bookID: Int
    let pageIndex: Int
    let name: String
    let kind: String
    let bytes: Int
    let changedAt: Date
    /// Bij een upload: was jij degene die dit neerzette, of lag er al iets van
    /// een ander apparaat? Ontbreekt bij het manifest — dan is het niet van
    /// toepassing en staat hij op `true`.
    let stored: Bool

    enum CodingKeys: String, CodingKey {
        case name, kind, bytes, stored
        case bookID = "book_id"
        case pageIndex = "page_index"
        case changedAt = "changed_at"
    }

    init(from decoder: Decoder) throws {
        let waarden = try decoder.container(keyedBy: CodingKeys.self)
        bookID = try waarden.decode(Int.self, forKey: .bookID)
        pageIndex = try waarden.decode(Int.self, forKey: .pageIndex)
        name = try waarden.decode(String.self, forKey: .name)
        kind = try waarden.decode(String.self, forKey: .kind)
        bytes = try waarden.decode(Int.self, forKey: .bytes)
        changedAt = try waarden.decode(Date.self, forKey: .changedAt)
        stored = try waarden.decodeIfPresent(Bool.self, forKey: .stored) ?? true
    }
}

struct SidecarManifest: Codable, Sendable {
    let items: [SidecarRegel]
    let total: Int
    let totalBytes: Int

    enum CodingKeys: String, CodingKey {
        case items, total
        case totalBytes = "total_bytes"
    }
}
