import Foundation

/// De pagina's die je al gezien hebt, of die vooraf zijn binnengehaald, op
/// schijf — zodat een hoofdstuk dat je eerder las ook zonder NAS teruggeeft.
///
/// Eén budget voor de hele bibliotheek. Ligt er een boek in dat beschermd is
/// (zie `Prioriteiten`), dan slaat het opruimen die map helemaal over; al het
/// andere ruimt op leeftijd op, de langst niet bekeken pagina het eerst.
///
/// Een `actor` en geen `@MainActor`-klasse: schrijven gebeurt vanuit
/// `Beeldlader` terwijl er ondertussen ook gelezen kan worden, en dit is
/// bestandswerk dat niet op de hoofdthread hoort te wachten.
actor Paginacache {
    static let gedeeld = Paginacache()

    private let basis: URL
    private var gebruikteBytes: Int64
    private static let gebruikSleutel = "offline.paginaBytes"

    private init() {
        let cache = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        basis = cache.appendingPathComponent("paginas", isDirectory: true)
        try? FileManager.default.createDirectory(at: basis, withIntermediateDirectories: true)
        gebruikteBytes = Int64(UserDefaults.standard.integer(forKey: Self.gebruikSleutel))
    }

    var omvang: Int64 { gebruikteBytes }

    private func boekMap(serieID: Int, boek: Int) -> URL {
        basis.appendingPathComponent("\(serieID)", isDirectory: true)
            .appendingPathComponent("\(boek)", isDirectory: true)
    }

    /// De cachesleutel van `Beeldlader` kan leestekens bevatten (een dubbele
    /// punt achter een taalcode); een hash is altijd een geldige bestandsnaam.
    private func bestand(serieID: Int, boek: Int, sleutel: String) -> URL {
        boekMap(serieID: serieID, boek: boek).appendingPathComponent("\(abs(sleutel.hashValue)).dat")
    }

    func lees(serieID: Int, boek: Int, sleutel: String) -> Data? {
        let pad = bestand(serieID: serieID, boek: boek, sleutel: sleutel)
        guard let data = try? Data(contentsOf: pad) else { return nil }
        // Lezen is ook "nog in gebruik": de mtime bijwerken houdt de pagina uit
        // de eerstvolgende opruimronde.
        try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: pad.path)
        return data
    }

    func schrijf(_ data: Data, serieID: Int, boek: Int, sleutel: String) {
        let map = boekMap(serieID: serieID, boek: boek)
        try? FileManager.default.createDirectory(at: map, withIntermediateDirectories: true)
        let pad = bestand(serieID: serieID, boek: boek, sleutel: sleutel)
        let oud = oudeGrootte(pad)
        guard (try? data.write(to: pad)) != nil else { return }
        gebruikteBytes += Int64(data.count) - oud
        bewaarGebruik()
    }

    private func oudeGrootte(_ pad: URL) -> Int64 {
        guard let attributen = try? FileManager.default.attributesOfItem(atPath: pad.path),
              let grootte = attributen[.size] as? Int64
        else { return 0 }
        return grootte
    }

    private func bewaarGebruik() {
        UserDefaults.standard.set(Int(gebruikteBytes), forKey: Self.gebruikSleutel)
    }

    /// Ruimt op tot onder de limiet als dat nodig is. Series in
    /// `prioriteitSeries` en boeken in `beschermdeBoeken` blijven altijd staan
    /// — die twee zijn de enige twee dingen die deze functie hoeft te weten
    /// over de rest van de app, en ze komen als waarden binnen zodat deze
    /// actor niet naar `Prioriteiten` op de hoofdthread hoeft te wachten.
    func ruimOpIndienNodig(
        limiet: Int64, prioriteitSeries: Set<Int>, beschermdeBoeken: Set<Int>
    ) {
        guard gebruikteBytes > limiet else { return }
        let fm = FileManager.default
        guard let serieMappen = try? fm.contentsOfDirectory(at: basis, includingPropertiesForKeys: nil)
        else { return }

        var kandidaten: [(pad: URL, mtime: Date, bytes: Int64)] = []
        for serieMap in serieMappen {
            guard let serieID = Int(serieMap.lastPathComponent),
                  !prioriteitSeries.contains(serieID),
                  let boekMappen = try? fm.contentsOfDirectory(
                    at: serieMap, includingPropertiesForKeys: nil
                  )
            else { continue }
            for boekMap in boekMappen {
                guard let boekID = Int(boekMap.lastPathComponent), !beschermdeBoeken.contains(boekID)
                else { continue }
                kandidaten.append(contentsOf: bestanden(in: boekMap))
            }
        }

        for kandidaat in kandidaten.sorted(by: { $0.mtime < $1.mtime }) {
            guard gebruikteBytes > limiet else { break }
            try? fm.removeItem(at: kandidaat.pad)
            gebruikteBytes -= kandidaat.bytes
        }
        bewaarGebruik()
    }

    private func bestanden(in map: URL) -> [(pad: URL, mtime: Date, bytes: Int64)] {
        let sleutels: [URLResourceKey] = [.contentModificationDateKey, .fileSizeKey]
        guard let inhoud = try? FileManager.default.contentsOfDirectory(
            at: map, includingPropertiesForKeys: sleutels
        ) else { return [] }
        return inhoud.compactMap { pad in
            guard let waarden = try? pad.resourceValues(forKeys: Set(sleutels)),
                  let mtime = waarden.contentModificationDate,
                  let bytes = waarden.fileSize
            else { return nil }
            return (pad, mtime, Int64(bytes))
        }
    }

    /// Alles weggooien, voor de knop in Instellingen.
    func maakLeeg() {
        try? FileManager.default.removeItem(at: basis)
        try? FileManager.default.createDirectory(at: basis, withIntermediateDirectories: true)
        gebruikteBytes = 0
        bewaarGebruik()
    }
}
