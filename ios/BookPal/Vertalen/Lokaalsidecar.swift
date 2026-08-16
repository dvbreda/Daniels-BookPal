import Foundation

/// Sidecarbestanden die de telefoon zelf gemaakt heeft, in dezelfde
/// naamgeving als de server (`bookpal.translate.sidecar`) — zodat een upload
/// via `/api/sidecars/{boek}/{naam}` zonder vertaalslag aankomt.
///
/// Anders dan op de server hoeft de telefoon de hoofdstukmap niet te kennen:
/// de server zoekt die zelf op aan de hand van het boek-id
/// (`inventory.pad_voor`). Hier is de map dus gewoon het boek-id — puur
/// lokale boekhouding, die na een geslaagde sync ook weer weg mag.
enum Lokaalsidecar {
    static let basis: URL = {
        let documenten = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let map = documenten.appendingPathComponent("lokale-sidecars", isDirectory: true)
        try? FileManager.default.createDirectory(at: map, withIntermediateDirectories: true)
        return map
    }()

    private static func paginaStam(_ index: Int) -> String {
        String(format: "p%04d", index)
    }

    /// `p0007-nl-image_fast.webp` — zie `sidecar.image_path` op de server.
    static func hertekendNaam(pagina: Int, taal: String, zwaar: Bool) -> String {
        "\(paginaStam(pagina))-\(taal)-\(zwaar ? "image_pro" : "image_fast").webp"
    }

    /// `p0007-kleur.webp` — zie `sidecar.variant_path` op de server.
    static func kleurNaam(pagina: Int) -> String {
        "\(paginaStam(pagina))-kleur.webp"
    }

    private static func boekMap(_ boek: Int) -> URL {
        let map = basis.appendingPathComponent("\(boek)", isDirectory: true)
        try? FileManager.default.createDirectory(at: map, withIntermediateDirectories: true)
        return map
    }

    static func bewaar(_ data: Data, naam: String, boek: Int) {
        try? data.write(to: boekMap(boek).appendingPathComponent(naam))
    }

    static func lees(naam: String, boek: Int) -> Data? {
        try? Data(contentsOf: boekMap(boek).appendingPathComponent(naam))
    }

    /// Weg nadat een sync 'm veilig bij de NAS heeft afgeleverd — anders blijft
    /// dezelfde plaat bij elke sync opnieuw meetellen als "nog niet
    /// geüpload", terwijl hij dat na de eerste keer al lang is.
    static func verwijder(naam: String, boek: Int) {
        try? FileManager.default.removeItem(at: boekMap(boek).appendingPathComponent(naam))
    }

    /// Eén regel uit de lokale inventaris, in dezelfde vorm als het manifest
    /// van `/api/sidecars` — zodat de twee rechtstreeks te vergelijken zijn.
    struct Regel {
        let boek: Int
        let naam: String
        let bytes: Int
        let gewijzigd: Date
    }

    static func alles() -> [Regel] {
        let fm = FileManager.default
        guard let boekMappen = try? fm.contentsOfDirectory(at: basis, includingPropertiesForKeys: nil)
        else { return [] }

        var regels: [Regel] = []
        for boekMap in boekMappen {
            guard let boek = Int(boekMap.lastPathComponent),
                  let bestanden = try? fm.contentsOfDirectory(
                    at: boekMap,
                    includingPropertiesForKeys: [.fileSizeKey, .contentModificationDateKey]
                  )
            else { continue }
            for bestand in bestanden {
                guard let waarden = try? bestand.resourceValues(
                    forKeys: [.fileSizeKey, .contentModificationDateKey]
                ), let bytes = waarden.fileSize, let gewijzigd = waarden.contentModificationDate
                else { continue }
                regels.append(
                    Regel(boek: boek, naam: bestand.lastPathComponent, bytes: bytes, gewijzigd: gewijzigd)
                )
            }
        }
        return regels
    }
}
