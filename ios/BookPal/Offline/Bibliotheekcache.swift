import Foundation

/// Wat je ziet als de NAS niet bereikbaar is: de laatst geslaagde versie van
/// de startpagina en de bibliotheek.
///
/// Alleen het gedecodeerde antwoord zelf, niet de platen — de omslagen en
/// pagina's hebben hun eigen cache (`Paginacache` voor pagina's, `URLCache`
/// voor omslagen). Dit is puur "wat staat er" — genoeg om iets te tonen
/// zonder een lege lijst met een foutmelding, en genoeg om te weten welke
/// series er zijn zodra je ze aan wilt zetten als offline-prioriteit.
enum Bibliotheekcache {
    private static let map: URL = {
        let basis = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        let map = basis.appendingPathComponent("bibliotheekcache", isDirectory: true)
        try? FileManager.default.createDirectory(at: map, withIntermediateDirectories: true)
        return map
    }()

    private static func bestand(_ sleutel: String) -> URL {
        map.appendingPathComponent("\(abs(sleutel.hashValue)).json")
    }

    static func bewaar<T: Encodable>(_ waarde: T, sleutel: String) {
        guard let data = try? JSONEncoder().encode(waarde) else { return }
        try? data.write(to: bestand(sleutel))
    }

    static func lees<T: Decodable>(_ soort: T.Type, sleutel: String) -> T? {
        guard let data = try? Data(contentsOf: bestand(sleutel)) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }

    /// Haalt vers op en bewaart dat, of valt terug op wat er eerder lag.
    /// `vanCache` zegt de aanroeper of dit een terugval is, zodat die het kan
    /// laten zien in plaats van een verse lijst voor te wenden.
    static func metTerugval<T: Codable>(
        sleutel: String, _ ophalen: @Sendable () async throws -> T
    ) async -> (waarde: T?, vanCache: Bool) {
        if let vers = try? await ophalen() {
            bewaar(vers, sleutel: sleutel)
            return (vers, false)
        }
        return (lees(T.self, sleutel: sleutel), true)
    }
}
