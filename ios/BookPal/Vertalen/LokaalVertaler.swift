import Foundation

/// Eén pagina laten hertekenen of inkleuren, rechtstreeks bij Gemini vandaan —
/// zonder de NAS ertussen.
///
/// Alleen de twee beeldstanden en inkleuren: die zijn in één rondje op te
/// lossen, beeld erin en beeld eruit. De tekststand hoort hier bewust niet
/// bij — die levert tekstvlakken op die de lezer zelf tekent
/// (`Ballonnen.swift`), en dat vraagt om hetzelfde JSON-schema en dezelfde
/// balloon-afmetingen als de server gebruikt. Te veel om hier te verdubbelen
/// voor de stand die toch al het goedkoopst is en het minst de moeite waard
/// om zonder NAS te doen.
///
/// De opdrachten hieronder staan woordelijk gelijk aan `imagepage.py` op de
/// server. Dezelfde tekst leverde daar gemeten een betere uitlijning op (van
/// 0,840 naar 0,886 overlap met het origineel) — die meting geldt hier
/// evengoed, dus wie deze tekst aanpast past 'm op allebei de plekken aan.
enum LokaalVertaler {
    enum Fout: LocalizedError {
        case geenSleutel
        case server(Int)
        case geenBeeld

        var errorDescription: String? {
            switch self {
            case .geenSleutel:
                return "Er is geen eigen Gemini-sleutel ingesteld (Instellingen → Offline)."
            case let .server(status):
                return "Gemini gaf \(status) terug."
            case .geenBeeld:
                return "Gemini gaf geen afbeelding terug."
            }
        }
    }

    private static let basis = URL(string: "https://generativelanguage.googleapis.com/v1beta")!

    /// Moet gelijk blijven aan `gemini_image_model_fast`/`_pro` in
    /// `server/bookpal/config.py`.
    static func model(zwaar: Bool) -> String {
        zwaar ? "gemini-3-pro-image" : "gemini-3.1-flash-image"
    }

    private static let talen: [String: String] = [
        "nl": "Nederlands", "en": "Engels", "de": "Duits",
        "fr": "Frans", "es": "Spaans", "ja": "Japans",
    ]

    private static func vertaalOpdracht(taal: String) -> String {
        let taalnaam = talen[taal.lowercased()] ?? taal
        return """
        Dit is een pagina uit een stripverhaal.

        Vervang ALLE tekst in elke tekstballon, elk bijschrift en elk geluidseffect door
        een goede vertaling naar \(taalnaam), met de hele pagina als context: een losse
        ballon is vaak de tweede helft van een zin die in de vorige begon.

        Regels:
        - Vertaal ELKE ballon. Een ballon in de oorspronkelijke taal laten staan is een
          fout, ook een korte.
        - Verzin niets bij. Voeg geen tekst, ballonnen of regels toe die er niet staan.
        - Neem getallen, bedragen en eigennamen exact over. Een bedrag of naam
          veranderen is de ergste fout die je kunt maken, want die valt niet op.
        - Laat tekst die bij de tekening hoort (winkelborden, opschriften in een andere
          taal) staan zoals hij is.
        - Gebruik per vlak dezelfde letterstijl en grootte als het origineel.
        - Zet de vertaling ALTIJD horizontaal, van links naar rechts, en verdeel hem
          over meerdere regels binnen de ballon. Ook als het origineel verticaal van
          boven naar beneden loopt, zoals in Japanse ballonnen: die richting hoort bij
          het Japanse schrift, niet bij de ballon. Losse letters onder elkaar gestapeld
          zijn onleesbaar.
        - De ballon zelf houdt zijn vorm en plek. Past de vertaling er horizontaal niet
          fatsoenlijk in, maak de letters dan kleiner — niet de ballon groter.
        - Verander verder NIETS: geen tekening, geen arcering, geen kleuren, geen
          paneelindeling, geen ballonvormen. Een zwart-wit pagina blijft zwart-wit.

        Geef alleen de bewerkte pagina terug, op exact dezelfde afmeting als deze.
        """
    }

    private static let kleurOpdracht = """
        Dit is een zwart-witte pagina uit een stripverhaal.

        Schilder er aquarel in, en houd daarbij de tekening exact op zijn plek.

        Wat onaangetast blijft, pixel voor pixel:
        - De omtrekken van alle figuren, gezichten en voorwerpen.
        - De randen van elk paneel, en de vorm en plek van elke tekstballon.
        - Alle tekst, in dezelfde letters op dezelfde plek. Vertaal niets en herschrijf
          niets.

        Wat je toevoegt — aquarel, zoals de kleurpagina's die mangaka zelf schilderen:
        - Doorschijnende wassingen, geen egale vlakken. Binnen één vlak mag de kleur
          verlopen van vol naar bijna niets, en het wit van het papier schijnt eronder
          door.
        - Zachte randen, en kleuren die in elkaar mogen lopen waar ze elkaar raken.
        - Kies de kleur die het onderwerp in het echt heeft. Bladeren zijn groen,
          bloemen en kleding mogen uitgesproken kleurrijk zijn, eten ziet er eetbaar
          uit. Verf het niet allemaal in bruin en grijs.
        - De arcering mag opgaan in de wassing; de omtrekken zelf niet. Die blijven
          scherp, met de verf eronder.
        - Tekstballonnen en de papierrand blijven wit. Papier is papier en inkt is inkt.
        - Houd het rustig genoeg om te blijven lezen. Een overdreven verzadigde pagina
          leest slechter dan het zwart-witte origineel.

        Verschuif, herschaal of herteken niets. Iemand legt jouw pagina straks precies
        over deze heen, en dan moet elke lijn samenvallen.

        Geef alleen de geschilderde pagina terug, op exact dezelfde afmeting als deze.
        """

    static func hertekenPagina(
        data: Data, mediaType: String, taal: String, zwaar: Bool
    ) async throws -> Data {
        try await stuur(
            opdracht: vertaalOpdracht(taal: taal), data: data, mediaType: mediaType,
            model: model(zwaar: zwaar)
        )
    }

    static func kleurPagina(data: Data, mediaType: String) async throws -> Data {
        try await stuur(
            opdracht: kleurOpdracht, data: data, mediaType: mediaType, model: model(zwaar: false)
        )
    }

    private static func stuur(
        opdracht: String, data: Data, mediaType: String, model: String
    ) async throws -> Data {
        guard let sleutel = Sleutelketen.lees(), !sleutel.isEmpty else { throw Fout.geenSleutel }

        var verzoek = URLRequest(url: basis.appending(path: "models/\(model):generateContent"))
        verzoek.httpMethod = "POST"
        verzoek.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // In de header en niet als query-parameter: dezelfde fout die de
        // serversleutel ooit in de containerlogs liet belanden (zie
        // CLAUDE.md) mag hier niet nog een keer.
        verzoek.setValue(sleutel, forHTTPHeaderField: "x-goog-api-key")
        verzoek.timeoutInterval = 300
        verzoek.httpBody = try JSONSerialization.data(withJSONObject: [
            "contents": [
                [
                    "parts": [
                        ["text": opdracht],
                        ["inline_data": ["mime_type": mediaType, "data": data.base64EncodedString()]],
                    ]
                ]
            ]
        ])

        let (antwoordData, antwoord) = try await URLSession.shared.data(for: verzoek)
        guard let http = antwoord as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw Fout.server((antwoord as? HTTPURLResponse)?.statusCode ?? 0)
        }
        return try beeld(uit: antwoordData)
    }

    /// Zoekt zowel `inlineData` als `inline_data`: Gemini gebruikt camelCase,
    /// maar de server test op allebei omdat dat ooit anders bleek — zie
    /// `imagepage._extract_image`. Dezelfde voorzichtigheid hier.
    private static func beeld(uit data: Data) throws -> Data {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let kandidaten = json["candidates"] as? [[String: Any]],
              let eerste = kandidaten.first,
              let inhoud = eerste["content"] as? [String: Any],
              let delen = inhoud["parts"] as? [[String: Any]]
        else { throw Fout.geenBeeld }

        for deel in delen {
            let blob = (deel["inlineData"] as? [String: Any]) ?? (deel["inline_data"] as? [String: Any])
            if let base64 = blob?["data"] as? String, let beeld = Data(base64Encoded: base64) {
                return beeld
            }
        }
        throw Fout.geenBeeld
    }
}
