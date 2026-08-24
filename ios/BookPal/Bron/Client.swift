import Foundation

enum ClientFout: LocalizedError {
    case geenAdres
    case ongeldigAdres(String)
    case server(status: Int, uitleg: String?)
    case netwerk(Error)
    /// De pagina heeft al kleur van de tekenaar zelf. Een eigen geval omdat het
    /// geen storing is: er ging niets mis, het is alleen de vraag of je dit wilt.
    case alInKleur(String)

    var errorDescription: String? {
        switch self {
        case .geenAdres:
            return "Er is nog geen serveradres ingesteld."
        case let .ongeldigAdres(adres):
            return "«\(adres)» is geen geldig adres."
        case let .server(status, uitleg):
            if let uitleg, !uitleg.isEmpty { return uitleg }
            return "De server antwoordde met \(status)."
        case let .netwerk(fout):
            return fout.localizedDescription
        case let .alInKleur(uitleg):
            return uitleg
        }
    }
}

/// Praat met dezelfde REST-API als de web-app en BookPal Lite.
///
/// Er is bewust geen eigen datamodel op het apparaat: één API en één waarheid
/// was het hele punt van de architectuur, dus de app leest wat de server zegt
/// en schrijft voortgang terug naar hetzelfde endpoint dat de web-lezer
/// gebruikt.
struct Client: Sendable {
    /// `web`: 1600px breed. Gemeten op de eigen bibliotheek zijn de bronpagina's
    /// rond de 1080px hoog, en de server schaalt niet op — `web` en `web-hidpi`
    /// leveren daar dus hetzelfde beeld. Voor scans die wél groter zijn dekt
    /// 1600px een iPhone op 3x (1179px breed) met ruimte over om in te zoomen.
    static let standaardProfiel = "web"

    let basis: URL
    private let sessie: URLSession

    init(basis: URL, sessie: URLSession = .shared) {
        self.basis = basis
        self.sessie = sessie
    }

    // MARK: - Adressen

    /// De pagina zelf. Geen JSON maar beeld, dus dit adres gaat rechtstreeks
    /// naar de beeldlader.
    func paginaURL(
        boek: Int,
        index: Int,
        profiel: String = Client.standaardProfiel,
        bewerking: Beeldbewerking = Beeldbewerking()
    ) -> URL? {
        var onderdelen = URLComponents(
            url: basis.appending(path: "api/books/\(boek)/pages/\(index)"),
            resolvingAgainstBaseURL: false
        )
        onderdelen?.queryItems =
            [URLQueryItem(name: "profile", value: profiel)] + bewerking.queryItems
        return onderdelen?.url
    }

    // De vertaal-endpoints hangen onder `/api/books`, niet onder
    // `/api/translate` — dat laatste bestaat wel, maar alleen voor de
    // instellingen. Een verkeerd pad valt hier niet op als een 404: de web-app
    // vangt alles op, dus je krijgt vrolijk een 200 met HTML terug.

    /// De hertekende pagina (beeldstand). Bestaat alleen als er al voor betaald
    /// is; deze app maakt hem niet aan.
    func hertekendURL(boek: Int, index: Int) -> URL {
        basis.appending(path: "api/books/\(boek)/pages/\(index)/full")
    }

    /// De ingekleurde pagina. Met een taal erbij krijg je de versie die van de
    /// vertaalde pagina is gemaakt — kleur en vertaalde tekst in één beeld.
    func kleurURL(boek: Int, index: Int, taal: String?) -> URL? {
        var onderdelen = URLComponents(
            url: basis.appending(path: "api/books/\(boek)/pages/\(index)/colour"),
            resolvingAgainstBaseURL: false
        )
        if let taal { onderdelen?.queryItems = [URLQueryItem(name: "lang", value: taal)] }
        return onderdelen?.url
    }

    /// Het profiel waarin omslagen binnenkomen. `thumb` is 320px breed —
    /// ruim voor een tegel van honderd punten op 3x, en klein genoeg dat de
    /// hele bibliotheek aan omslagen op je toestel past.
    static let omslagProfiel = "thumb"

    func omslagURL(serie: Int, profiel: String = Client.omslagProfiel) -> URL {
        var onderdelen = URLComponents(
            url: basis.appending(path: "api/series/\(serie)/cover"), resolvingAgainstBaseURL: false
        )
        onderdelen?.queryItems = [URLQueryItem(name: "profile", value: profiel)]
        return onderdelen?.url ?? basis.appending(path: "api/series/\(serie)/cover")
    }

    func boekOmslagURL(boek: Int, profiel: String = Client.omslagProfiel) -> URL {
        var onderdelen = URLComponents(
            url: basis.appending(path: "api/books/\(boek)/cover"), resolvingAgainstBaseURL: false
        )
        onderdelen?.queryItems = [URLQueryItem(name: "profile", value: profiel)]
        return onderdelen?.url ?? basis.appending(path: "api/books/\(boek)/cover")
    }

    // MARK: - Lezen

    func gezondheid() async throws -> ServerHealth {
        try await haal("api/health")
    }

    func series(zoek: String? = nil, limiet: Int = 200) async throws -> Paginated<Series> {
        var items = [URLQueryItem(name: "limit", value: String(limiet))]
        if let zoek, !zoek.isEmpty { items.append(URLQueryItem(name: "search", value: zoek)) }
        return try await haal("api/series", query: items)
    }

    /// De startpagina: waar je gebleven bent en wat er nieuw is.
    func home() async throws -> Home {
        try await haal("api/home")
    }

    func serie(_ id: Int) async throws -> SeriesDetail {
        try await haal("api/series/\(id)")
    }

    /// De bibliotheek, gefilterd. Dezelfde parameters als de web-app gebruikt;
    /// de tab-regels blijven op de server, waar ze naar een query compileren.
    func series(
        filter: Bibliotheekfilter,
        zoek: String? = nil,
        sortering: Sortering = .naam,
        omgekeerd: Bool = false,
        limiet: Int = 200
    ) async throws -> Paginated<Series> {
        var items = [URLQueryItem(name: "limit", value: String(limiet))]
        items.append(URLQueryItem(name: "sort", value: sortering.rawValue))
        if omgekeerd { items.append(URLQueryItem(name: "desc", value: "true")) }
        if let zoek, !zoek.isEmpty { items.append(URLQueryItem(name: "search", value: zoek)) }
        if let groep = filter.groep.query { items.append(URLQueryItem(name: "group", value: groep)) }
        if let soort = filter.soort { items.append(URLQueryItem(name: "kind", value: soort.rawValue)) }
        if let herkomst = filter.herkomst {
            items.append(URLQueryItem(name: "region", value: herkomst.rawValue))
        }
        if let root = filter.rootID { items.append(URLQueryItem(name: "root_id", value: String(root))) }
        return try await haal("api/series", query: items)
    }

    /// De series van één tab. De regel wordt op de server naar een
    /// SQLAlchemy-query gecompileerd — die engine willen we hier niet nabouwen.
    /// De groep gaat er los naast mee: die snijdt dwars door elke tab heen.
    func tabSeries(_ tab: Int, groep: Soortfilter = .alles, zoek: String? = nil, limiet: Int = 200)
        async throws -> Paginated<Series>
    {
        var items = [URLQueryItem(name: "limit", value: String(limiet))]
        if let zoek, !zoek.isEmpty { items.append(URLQueryItem(name: "search", value: zoek)) }
        if let waarde = groep.query { items.append(URLQueryItem(name: "group", value: waarde)) }
        return try await haal("api/tabs/\(tab)/series", query: items)
    }

    func tabs() async throws -> [Bibliotheektab] {
        try await haal("api/tabs")
    }

    func roots() async throws -> [LibraryRoot] {
        try await haal("api/libraries")
    }

    func profielen() async throws -> [Beeldprofiel] {
        try await haal("api/profiles")
    }

    /// De vertaalstanden van de server, met de prijs per pagina. Alleen lezen:
    /// omzetten kan geld laten lopen en gebeurt in de web-app.
    func vertaalinstellingen() async throws -> Vertaalinstellingen {
        try await haal("api/translate/mode")
    }

    /// Het volgende hoofdstuk. Geeft 404 als dit het laatste was, en dat is
    /// geen fout — dan is er gewoon niets meer.
    func volgendHoofdstuk(boek: Int) async throws -> VolgendHoofdstuk {
        try await haal("api/books/\(boek)/next")
    }

    /// Waar je verder leest in deze serie.
    func verderLezen(serie: Int) async throws -> VerderLezen {
        try await haal("api/series/\(serie)/continue")
    }

    /// Zelf zeggen of je een hoofdstuk gelezen hebt. Nodig omdat de automatiek
    /// soms te gretig is: een kort hoofdstuk staat na één blik op 100%.
    func zetGelezen(boek: Int, gelezen: Bool) async throws {
        var verzoek = URLRequest(url: basis.appending(path: "api/books/\(boek)/read-state"))
        verzoek.httpMethod = "POST"
        verzoek.setValue("application/json", forHTTPHeaderField: "Content-Type")
        verzoek.httpBody = try JSONSerialization.data(withJSONObject: ["finished": gelezen])
        _ = try await stuur(verzoek)
    }

    /// Alles vóór dit hoofdstuk op gelezen zetten.
    func markeerEerdereGelezen(serie: Int, boek: Int) async throws {
        var verzoek = URLRequest(
            url: basis.appending(path: "api/series/\(serie)/mark-read-before/\(boek)")
        )
        verzoek.httpMethod = "POST"
        _ = try await stuur(verzoek)
    }

    func boek(_ id: Int) async throws -> Book {
        try await haal("api/books/\(id)")
    }

    /// Wat er voor deze pagina aan vertaling klaarligt, in de beste stand die er
    /// is. Leest alleen — vertalen kost geld en gebeurt via POST, en die stuurt
    /// deze app bewust niet: dan zou je vanaf de telefoon per ongeluk een
    /// hoofdstuk kunnen afrekenen.
    func vertaling(boek: Int, index: Int, taal: String? = nil) async throws -> PageTranslation {
        var query: [URLQueryItem] = []
        if let taal { query.append(URLQueryItem(name: "lang", value: taal)) }
        return try await haal("api/books/\(boek)/pages/\(index)/translation", query: query)
    }

    // MARK: - Bronnen en trackers
    //
    // Deze kosten geen geld, maar veranderen wél iets: volgen maakt boeken aan,
    // ophalen kost schijfruimte en bandbreedte, en een push gaat naar buiten.
    // Vandaar dat elke knop hier zegt wat hij gaat doen.

    func bronnen() async throws -> [Bron] {
        try await haal("api/sources")
    }

    func zoek(bron: Int, term: String) async throws -> [Zoektreffer] {
        try await haal(
            "api/sources/\(bron)/search",
            query: [URLQueryItem(name: "q", value: term)]
        )
    }

    /// Een reeks gaan volgen. `readahead` haalt er een paar vooruit en ruimt de
    /// rest op; `permanent` houdt alles.
    @discardableResult
    func volg(
        bron: Int, ref: String, taal: String, policy: String, vooruit: Int
    ) async throws -> [String: JSONWaarde] {
        try await stuurJSON(
            "api/sources/\(bron)/subscribe",
            lichaam: [
                "ref": ref, "language": taal, "policy": policy, "readahead_n": vooruit,
            ]
        )
    }

    func abonnementen() async throws -> [Abonnement] {
        try await haal("api/sources/subscriptions/all")
    }

    @discardableResult
    func ververs(abonnement: Int) async throws -> [String: JSONWaarde] {
        try await stuurJSON("api/sources/subscriptions/\(abonnement)/refresh")
    }

    func stopAbonnement(_ id: Int) async throws {
        var verzoek = URLRequest(
            url: basis.appending(path: "api/sources/subscriptions/\(id)")
        )
        verzoek.httpMethod = "DELETE"
        _ = try await stuur(verzoek)
    }

    /// Een ronde langs alle abonnementen: nieuwe hoofdstukken ophalen en
    /// vooruitlezen bijwerken. Draait ook vanzelf op een interval; dit is de
    /// knop "nu bijwerken".
    func draaiRonde() async throws -> Rondeverslag {
        try await stuurJSON("api/sources/run")
    }

    /// Eén hoofdstuk binnenhalen.
    @discardableResult
    func haalHoofdstuk(boek: Int) async throws -> [String: JSONWaarde] {
        try await stuurJSON("api/sources/books/\(boek)/download")
    }

    func trackers() async throws -> [Trackeraccount] {
        try await haal("api/trackers")
    }

    @discardableResult
    func zetTracker(_ id: Int, actief: Bool? = nil, proef: Bool? = nil) async throws
        -> Trackeraccount
    {
        var lichaam: [String: Any] = [:]
        if let actief { lichaam["enabled"] = actief }
        if let proef { lichaam["dry_run"] = proef }
        var verzoek = URLRequest(url: basis.appending(path: "api/trackers/\(id)"))
        verzoek.httpMethod = "PATCH"
        verzoek.setValue("application/json", forHTTPHeaderField: "Content-Type")
        verzoek.httpBody = try JSONSerialization.data(withJSONObject: lichaam)
        return try Client.decoder.decode(Trackeraccount.self, from: try await stuur(verzoek))
    }

    /// Nu pushen. Staat het account in proefstand, dan wordt er niets echt
    /// verstuurd — dat is precies waar die stand voor is.
    func pushTracker(_ id: Int) async throws -> Pushverslag {
        try await stuurJSON("api/trackers/\(id)/run")
    }

    /// Het adres van de Goodreads-export. Die API is dood sinds eind 2020, dus
    /// dit is het vangnet: een CSV voor My Books → Import and Export.
    var goodreadsCSV: URL { basis.appending(path: "api/trackers/goodreads/export.csv") }

    // MARK: - Wat geld kost
    //
    // Deze aanroepen rekenen af bij Gemini. Ze staan hier bij elkaar en zijn
    // allemaal expliciet: de lezer vraagt eerst een plan of noemt de prijs, en
    // start pas daarna. Zie CLAUDE.md — "vraag het altijd eerst, en zeg hoeveel
    // pagina's het worden".

    /// Eén pagina in de tekststand: het model leest de pagina en geeft vlakken
    /// terug die wij zelf tekenen.
    @discardableResult
    func vertaalPagina(boek: Int, index: Int, taal: String, force: Bool = false) async throws
        -> PageTranslation
    {
        var query = [URLQueryItem(name: "lang", value: taal)]
        if force { query.append(URLQueryItem(name: "force", value: "true")) }
        return try await stuurJSON(
            "api/books/\(boek)/pages/\(index)/translation", query: query, lichaam: nil
        )
    }

    /// Eén pagina helemaal laten hertekenen mét vertaling (beeldstand).
    @discardableResult
    func hertekenPagina(
        boek: Int, index: Int, stand: String, taal: String, force: Bool = false
    ) async throws -> PageTranslation {
        try await stuurJSON(
            "api/books/\(boek)/pages/\(index)/full",
            lichaam: ["mode": stand, "lang": taal, "force": force]
        )
    }

    /// Eén pagina laten inkleuren.
    ///
    /// Antwoordt met 412 als de tekenaar de pagina zelf al kleurde: dan is het
    /// geen inkleuren maar overschilderen, en dat kost hetzelfde. De lezer maakt
    /// daar een vraag van en stuurt het desgewenst opnieuw met `force`.
    @discardableResult
    func kleurPagina(boek: Int, index: Int, taal: String?, force: Bool = false) async throws
        -> PageColour
    {
        var query: [URLQueryItem] = []
        if let taal { query.append(URLQueryItem(name: "lang", value: taal)) }
        if force { query.append(URLQueryItem(name: "force", value: "true")) }
        return try await stuurJSON(
            "api/books/\(boek)/pages/\(index)/colour", query: query, lichaam: nil
        )
    }

    /// Wat een heel hoofdstuk gaat kosten. Altijd eerst dit, dan pas starten.
    func batchplan(boek: Int, soort: String, vanafPagina: Int = 0) async throws -> Batchplan {
        try await haal(
            "api/books/\(boek)/batch/plan",
            query: [
                URLQueryItem(name: "kind", value: soort),
                URLQueryItem(name: "from_page", value: String(vanafPagina)),
            ]
        )
    }

    @discardableResult
    func startBatch(boek: Int, soort: String, vanafPagina: Int = 0) async throws -> Batchstatus {
        try await stuurJSON(
            "api/books/\(boek)/batch",
            lichaam: ["kind": soort, "from_page": vanafPagina]
        )
    }

    /// Wat er loopt — ook van een ander boek, want er kan er maar één tegelijk.
    func batchstatus(boek: Int) async throws -> Batchstatus? {
        let data = try await stuur(
            URLRequest(url: basis.appending(path: "api/books/\(boek)/batch"))
        )
        if data.isEmpty || String(data: data, encoding: .utf8) == "null" { return nil }
        return try Client.decoder.decode(Batchstatus.self, from: data)
    }

    /// Waar de panelen op deze pagina zitten. De server rekent dit zonder
    /// model uit (recursieve XY-cut) en cachet het; de app heeft dezelfde
    /// berekening als terugval.
    func panelen(boek: Int, index: Int) async throws -> [Paneel] {
        let antwoord: PanelsAntwoord = try await haal(
            "api/books/\(boek)/pages/\(index)/panels"
        )
        return antwoord.panelen
    }

    func kleurinfo(boek: Int, index: Int, taal: String? = nil) async throws -> ColourInfo {
        var query: [URLQueryItem] = []
        if let taal { query.append(URLQueryItem(name: "lang", value: taal)) }
        return try await haal("api/books/\(boek)/pages/\(index)/colour/info", query: query)
    }

    // MARK: - Schrijven

    /// Waar je gebleven bent. Hetzelfde endpoint als de web-lezer, dus wat je
    /// hier leest telt daar meteen mee — dat is ontwerp 4 uit de architectuur.
    ///
    /// Het percentage wordt door de aanroeper meegegeven en hier niet opnieuw
    /// uitgerekend: het moet gelijk zijn aan wat de web-lezer stuurt, en die som
    /// staat in `Spreads.percentVoor`.
    /// De positie is vrije JSON, want elke soort lezer bewaart iets anders:
    /// `{"page": 12}` bij een strip, `{"hoofdstuk": 3, "blok": 40}` bij een epub.
    func bewaarVoortgang(
        boek: Int, positie: [String: Int], percent: Double, uitgelezen: Bool
    ) async throws {
        let lichaam: [String: Any] = [
            "book_id": boek,
            "position": positie,
            "percent": min(max(percent, 0), 100),
            "finished": uitgelezen,
            "device": "ios",
        ]
        var verzoek = URLRequest(url: basis.appending(path: "api/progress"))
        verzoek.httpMethod = "PUT"
        verzoek.setValue("application/json", forHTTPHeaderField: "Content-Type")
        verzoek.httpBody = try JSONSerialization.data(withJSONObject: lichaam)
        _ = try await stuur(verzoek)
    }

    // MARK: - Sidecars zonder NAS
    //
    // Voor het synchroniseren van sidecars die de telefoon zelf maakte terwijl
    // er geen NAS was, en voor het binnenhalen van wat er al op de NAS ligt.
    // Zie `bookpal.api.sidecars` op de server — precies deze drie routes.

    func sidecarManifest(boek: Int? = nil) async throws -> SidecarManifest {
        var query: [URLQueryItem] = []
        if let boek { query.append(URLQueryItem(name: "book_id", value: String(boek))) }
        return try await haal("api/sidecars", query: query)
    }

    func sidecarOphalen(boek: Int, naam: String) async throws -> Data {
        try await stuur(URLRequest(url: basis.appending(path: "api/sidecars/\(boek)/\(naam)")))
    }

    /// Overschrijft nooit stilzwijgend: een botsing laat staan wat er al ligt,
    /// tenzij je `force` meegeeft. Zie de server-kant voor waarom dat de
    /// goede kant is om op te vallen.
    @discardableResult
    func sidecarPlaatsen(
        boek: Int, naam: String, data: Data, force: Bool = false
    ) async throws -> SidecarRegel {
        var onderdelen = URLComponents(
            url: basis.appending(path: "api/sidecars/\(boek)/\(naam)"), resolvingAgainstBaseURL: false
        )
        if force { onderdelen?.queryItems = [URLQueryItem(name: "force", value: "true")] }
        guard let url = onderdelen?.url else { throw ClientFout.ongeldigAdres(naam) }
        var verzoek = URLRequest(url: url)
        verzoek.httpMethod = "PUT"
        verzoek.httpBody = data
        verzoek.setValue(
            naam.hasSuffix(".json") ? "application/json" : "application/octet-stream",
            forHTTPHeaderField: "Content-Type"
        )
        return try Client.decoder.decode(SidecarRegel.self, from: try await stuur(verzoek))
    }

    // MARK: - Onderwater

    private func stuurJSON<T: Decodable>(
        _ pad: String, query: [URLQueryItem] = [], lichaam: [String: Any]? = nil
    ) async throws -> T {
        var onderdelen = URLComponents(
            url: basis.appending(path: pad), resolvingAgainstBaseURL: false
        )
        if !query.isEmpty { onderdelen?.queryItems = query }
        guard let url = onderdelen?.url else { throw ClientFout.ongeldigAdres(pad) }
        var verzoek = URLRequest(url: url)
        verzoek.httpMethod = "POST"
        // Deze aanroepen duren tientallen seconden: het model tekent een hele
        // pagina. De standaardtimeout van 60 seconden is daar te krap voor.
        verzoek.timeoutInterval = 300
        if let lichaam {
            verzoek.setValue("application/json", forHTTPHeaderField: "Content-Type")
            verzoek.httpBody = try JSONSerialization.data(withJSONObject: lichaam)
        }
        let data = try await stuur(verzoek)
        return try Client.decoder.decode(T.self, from: data)
    }

    private func haal<T: Decodable>(_ pad: String, query: [URLQueryItem] = []) async throws -> T {
        var onderdelen = URLComponents(
            url: basis.appending(path: pad),
            resolvingAgainstBaseURL: false
        )
        if !query.isEmpty { onderdelen?.queryItems = query }
        guard let url = onderdelen?.url else { throw ClientFout.ongeldigAdres(pad) }
        let data = try await stuur(URLRequest(url: url))
        return try Client.decoder.decode(T.self, from: data)
    }

    private func stuur(_ verzoek: URLRequest) async throws -> Data {
        let data: Data
        let antwoord: URLResponse
        do {
            (data, antwoord) = try await sessie.data(for: verzoek)
        } catch {
            throw ClientFout.netwerk(error)
        }
        guard let http = antwoord as? HTTPURLResponse else { return data }
        guard (200..<300).contains(http.statusCode) else {
            // 412 is geen storing: de tekenaar kleurde deze pagina zelf al, en
            // de server vraagt of je hem écht wilt overschilderen.
            if http.statusCode == 412 {
                let uitleg = try? Client.decoder.decode(ServerFout.self, from: data).detail
                throw ClientFout.alInKleur(uitleg ?? "deze pagina heeft al kleur")
            }
            // De server legt in `detail` uit wát er mis is ("een epub heeft geen
            // vaste pagina's"). Die tekst is bruikbaarder dan een statuscode.
            let uitleg = try? Client.decoder.decode(ServerFout.self, from: data).detail
            throw ClientFout.server(status: http.statusCode, uitleg: uitleg)
        }
        return data
    }

    /// De server stuurt tijdstempels zonder tijdzone (`2026-08-11T08:55:58.390215`).
    /// Gemeten in de container: die draait op UTC terwijl de NAS eromheen op
    /// CEST staat. Zonder dit worden ze als lokale tijd gelezen en staat "laatst
    /// gelezen" er twee uur naast.
    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        let metFractie = DateFormatter()
        metFractie.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        metFractie.timeZone = TimeZone(identifier: "UTC")
        metFractie.locale = Locale(identifier: "en_US_POSIX")

        let zonderFractie = DateFormatter()
        zonderFractie.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        zonderFractie.timeZone = TimeZone(identifier: "UTC")
        zonderFractie.locale = Locale(identifier: "en_US_POSIX")

        decoder.dateDecodingStrategy = .custom { decoder in
            let tekst = try decoder.singleValueContainer().decode(String.self)
            if let datum = metFractie.date(from: tekst) { return datum }
            if let datum = zonderFractie.date(from: tekst) { return datum }
            if let datum = ISO8601DateFormatter().date(from: tekst) { return datum }
            throw DecodingError.dataCorrupted(
                .init(codingPath: decoder.codingPath, debugDescription: "onbekende datum: \(tekst)")
            )
        }
        return decoder
    }()
}
