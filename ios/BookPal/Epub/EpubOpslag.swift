import Foundation

/// Haalt het epub-bestand op van de server en houdt het vast.
///
/// Een epub kan tientallen megabytes zijn en verandert niet meer zodra hij er
/// staat, dus hij wordt één keer opgehaald en daarna van schijf gelezen. Dat is
/// meteen het begin van offline lezen: wat je een keer geopend hebt, kun je
/// zonder NAS opnieuw openen.
enum EpubOpslag {

    enum Fout: LocalizedError {
        case download(Int)

        var errorDescription: String? {
            switch self {
            case let .download(status): return "het epub-bestand kwam terug met \(status)."
            }
        }
    }

    static var map: URL {
        let basis = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        let map = basis.appendingPathComponent("epubs", isDirectory: true)
        try? FileManager.default.createDirectory(at: map, withIntermediateDirectories: true)
        return map
    }

    static func bestand(boek: Int) -> URL {
        map.appendingPathComponent("boek-\(boek).epub")
    }

    static func beeldmap(boek: Int) -> URL {
        map.appendingPathComponent("boek-\(boek)-beeld", isDirectory: true)
    }

    static func staatKlaar(boek: Int) -> Bool {
        FileManager.default.fileExists(atPath: bestand(boek: boek).path)
    }

    /// Haalt het bestand op als het er nog niet is.
    ///
    /// - Parameter voortgang: fractie 0…1, of `nil` zolang de server geen lengte
    ///   meegeeft. Een epub van honderden MB's zonder balk is niet te
    ///   onderscheiden van een vastloper — dezelfde reden als in de web-app.
    static func haal(
        client: Client, boek: Int, voortgang: @MainActor @escaping (Double?) -> Void
    ) async throws -> URL {
        let doel = bestand(boek: boek)
        if FileManager.default.fileExists(atPath: doel.path) { return doel }

        let bron = client.basis.appending(path: "api/books/\(boek)/file")
        let (stroom, antwoord) = try await URLSession.shared.bytes(from: bron)
        if let http = antwoord as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw Fout.download(http.statusCode)
        }

        let verwacht = antwoord.expectedContentLength
        var data = Data()
        if verwacht > 0 { data.reserveCapacity(Int(verwacht)) }
        var laatsteMelding = 0

        for try await byte in stroom {
            data.append(byte)
            // Niet bij elke byte een update: dat is honderdduizenden keren de
            // hoofdthread wakker maken voor een balk die toch niet zo fijn kan.
            if data.count - laatsteMelding > 262_144 {
                laatsteMelding = data.count
                let fractie = verwacht > 0 ? Double(data.count) / Double(verwacht) : nil
                await MainActor.run { voortgang(fractie) }
            }
        }

        try data.write(to: doel)
        await MainActor.run { voortgang(1) }
        return doel
    }

    /// Hoeveel er op dit toestel staat, als leesbare tekst.
    static func omvang() -> String {
        let beheer = FileManager.default
        guard let inhoud = try? beheer.contentsOfDirectory(
            at: map, includingPropertiesForKeys: [.fileSizeKey], options: []
        ) else { return "niets" }
        var bytes = 0
        for pad in inhoud {
            // Ook de uitgepakte beeldmappen meetellen; die zijn samen groter
            // dan de epubs zelf.
            if let telling = beheer.enumerator(at: pad, includingPropertiesForKeys: [.fileSizeKey]) {
                for geval in telling {
                    if let bestand = geval as? URL,
                       let maat = try? bestand.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                        bytes += maat
                    }
                }
            }
            if let maat = try? pad.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                bytes += maat
            }
        }
        guard bytes > 0 else { return "niets" }
        return ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }

    /// Alles weggooien wat we van boeken hebben bewaard.
    static func maakLeeg() {
        try? FileManager.default.removeItem(at: map)
    }

    /// Alles van dit boek weggooien: bestand én uitgepakte plaatjes.
    static func gooiWeg(boek: Int) {
        try? FileManager.default.removeItem(at: bestand(boek: boek))
        try? FileManager.default.removeItem(at: beeldmap(boek: boek))
    }
}
