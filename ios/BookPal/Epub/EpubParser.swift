import Foundation
import ZIPFoundation

/// Leest een epub (een zip met XHTML) uit tot hoofdstukken in leesvolgorde.
///
/// Overgenomen uit Daniels Plantpal, waar deze aanpak zich al bewezen heeft.
/// De architectuur ging uit van foliate-js in een WKWebView, hergebruikt van de
/// web-lezer; native tekenen is bewust anders gekozen. Wat dat oplevert:
/// selecteerbare tekst, echte leesinstellingen, en geen JavaScript-brug. Wat het
/// kost staat in `EpubLezerView`: de web-lezer bewaart zijn plek als CFI en die
/// kunnen wij niet maken.
///
/// Alleen DRM-vrije epubs; dat is precies wat er in de eigen bibliotheek staat.
enum EpubParser {

    enum Fout: LocalizedError {
        case geenArchief, geenContainer, geenOpf, leeg

        var errorDescription: String? {
            switch self {
            case .geenArchief: return "geen geldig epub-archief"
            case .geenContainer: return "container.xml ontbreekt"
            case .geenOpf: return "inhoudsopgave (OPF) ontbreekt"
            case .leeg: return "geen leesbare tekst gevonden"
            }
        }
    }

    struct Hoofdstuk: Identifiable, Sendable {
        let id: Int          // de plek in de spine; meteen de leesvolgorde
        let titel: String
        let html: String
        let tekens: Int
    }

    struct Inhoud: Sendable {
        let titel: String
        let auteur: String
        let hoofdstukken: [Hoofdstuk]
    }

    /// - Parameters:
    ///   - url: het gedownloade epub-bestand.
    ///   - beeldmap: waar afbeeldingen uitgepakt worden. Ze gaan naar schijf en
    ///     niet als base64 in de tekst: dat laatste blies in Plantpal het
    ///     geheugen op en liet grote boeken vastlopen.
    static func parse(url: URL, beeldmap: URL) throws -> Inhoud {
        guard let archief = try? Archive(url: url, accessMode: .read) else { throw Fout.geenArchief }

        // 1. container.xml → pad naar het OPF-bestand.
        guard let containerXML = tekst(uit: "META-INF/container.xml", archief) else {
            throw Fout.geenContainer
        }
        guard let opfPad = attribuut(in: containerXML, tag: "rootfile", attribuut: "full-path") else {
            throw Fout.geenOpf
        }
        let opfMap = (opfPad as NSString).deletingLastPathComponent

        // 2. OPF → metadata, manifest (id→href) en spine (leesvolgorde).
        guard let opf = tekst(uit: opfPad, archief) else { throw Fout.geenOpf }
        let titel = tussenTags(opf, tag: "dc:title") ?? url.deletingPathExtension().lastPathComponent
        let auteur = tussenTags(opf, tag: "dc:creator") ?? "Onbekend"
        let manifest = manifestItems(opf)
        let spine = spineVolgorde(opf)

        try? FileManager.default.createDirectory(at: beeldmap, withIntermediateDirectories: true)

        // 3. Per spine-item de opgemaakte HTML, met de afbeeldingen naar schijf.
        var hoofdstukken: [Hoofdstuk] = []
        for (index, idref) in spine.enumerated() {
            guard let href = manifest[idref] else { continue }
            let pad = opfMap.isEmpty ? href : "\(opfMap)/\(href)"
            guard let xhtml = tekst(uit: pad, archief) else { continue }

            let kaal = striptHTML(xhtml)
            // Omslag- en lege pagina's overslaan: die geven een hoofdstuk in de
            // lijst waar niets in staat.
            guard kaal.count > 40 else { continue }

            let mapVanHoofdstuk = (pad as NSString).deletingLastPathComponent
            let body = binnenBody(xhtml)
            let metBeeld = beeldenNaarSchijf(
                in: body, hoofdstukmap: mapVanHoofdstuk, archief: archief, doel: beeldmap
            )

            hoofdstukken.append(
                Hoofdstuk(
                    id: index,
                    titel: eersteKop(body) ?? "Hoofdstuk \(hoofdstukken.count + 1)",
                    html: metBeeld,
                    tekens: kaal.count
                )
            )
        }

        guard !hoofdstukken.isEmpty else { throw Fout.leeg }
        return Inhoud(titel: titel, auteur: auteur, hoofdstukken: hoofdstukken)
    }

    // MARK: - Zip

    private static func tekst(uit pad: String, _ archief: Archive) -> String? {
        guard let data = data(uit: pad, archief) else { return nil }
        return String(data: data, encoding: .utf8) ?? String(data: data, encoding: .isoLatin1)
    }

    private static func data(uit pad: String, _ archief: Archive) -> Data? {
        // Een epub verwijst intern soms met %20 en soms met een spatie; beide
        // proberen scheelt hoofdstukken die anders stil wegvallen.
        let kandidaten = [pad, pad.removingPercentEncoding ?? pad]
        for kandidaat in kandidaten {
            guard let entry = archief[kandidaat] else { continue }
            var verzameld = Data()
            guard (try? archief.extract(entry, consumer: { verzameld.append($0) })) != nil else {
                continue
            }
            return verzameld
        }
        return nil
    }

    // MARK: - Afbeeldingen

    /// Haalt elke `<img src="…">` uit het archief en zet er een `file://`-adres
    /// voor in de plaats, zodat `NSAttributedString(html:)` hem inline toont.
    private static func beeldenNaarSchijf(
        in html: String, hoofdstukmap: String, archief: Archive, doel: URL
    ) -> String {
        let patroon = "src\\s*=\\s*[\"']([^\"']+)[\"']"
        guard let regex = try? NSRegularExpression(pattern: patroon, options: [.caseInsensitive]) else {
            return html
        }
        let ns = html as NSString
        var uit = html

        // Achterstevoren vervangen, anders schuiven de posities op.
        for match in regex.matches(in: html, range: NSRange(location: 0, length: ns.length)).reversed() {
            let bereik = match.range(at: 1)
            let bron = ns.substring(with: bereik)
            guard !bron.hasPrefix("data:"), !bron.hasPrefix("http") else { continue }

            let inArchief = normaliseer(pad: bron, vanuit: hoofdstukmap)
            guard let beeld = data(uit: inArchief, archief) else { continue }

            let naam = (inArchief as NSString).lastPathComponent
            let bestand = doel.appendingPathComponent(naam)
            if !FileManager.default.fileExists(atPath: bestand.path) {
                try? beeld.write(to: bestand)
            }
            uit = (uit as NSString).replacingCharacters(in: bereik, with: bestand.absoluteString)
        }
        return uit
    }

    /// "../Images/p1.jpg" vanuit "OEBPS/Text" wordt "OEBPS/Images/p1.jpg".
    static func normaliseer(pad: String, vanuit map: String) -> String {
        let samen = map.isEmpty ? pad : "\(map)/\(pad)"
        var delen: [String] = []
        for deel in samen.split(separator: "/", omittingEmptySubsequences: true) {
            if deel == ".." { delen.removeLast(delen.isEmpty ? 0 : 1) } else if deel != "." {
                delen.append(String(deel))
            }
        }
        return delen.joined(separator: "/")
    }

    // MARK: - XML zonder parser

    /// Bewust met reguliere expressies en geen `XMLParser`: een OPF is klein en
    /// voorspelbaar, en een streaming parser voor drie velden is meer machinerie
    /// dan het probleem groot is. Dezelfde afweging als in Plantpal.
    static func attribuut(in xml: String, tag: String, attribuut: String) -> String? {
        let patroon = "<\(tag)\\b[^>]*\\b\(attribuut)\\s*=\\s*[\"']([^\"']+)[\"']"
        return eersteGroep(patroon, in: xml)
    }

    static func tussenTags(_ xml: String, tag: String) -> String? {
        guard let ruw = eersteGroep("<\(tag)\\b[^>]*>(.*?)</\(tag)>", in: xml) else { return nil }
        let schoon = striptHTML(ruw)
        return schoon.isEmpty ? nil : schoon
    }

    static func manifestItems(_ opf: String) -> [String: String] {
        var items: [String: String] = [:]
        let patroon = "<item\\b[^>]*>"
        guard let regex = try? NSRegularExpression(pattern: patroon, options: [.caseInsensitive]) else {
            return items
        }
        let ns = opf as NSString
        for match in regex.matches(in: opf, range: NSRange(location: 0, length: ns.length)) {
            let tag = ns.substring(with: match.range)
            guard let id = eersteGroep("\\bid\\s*=\\s*[\"']([^\"']+)[\"']", in: tag),
                  let href = eersteGroep("\\bhref\\s*=\\s*[\"']([^\"']+)[\"']", in: tag)
            else { continue }
            items[id] = href
        }
        return items
    }

    static func spineVolgorde(_ opf: String) -> [String] {
        guard let spine = eersteGroep("<spine\\b[^>]*>(.*?)</spine>", in: opf) else { return [] }
        let patroon = "idref\\s*=\\s*[\"']([^\"']+)[\"']"
        guard let regex = try? NSRegularExpression(pattern: patroon, options: [.caseInsensitive]) else {
            return []
        }
        let ns = spine as NSString
        return regex.matches(in: spine, range: NSRange(location: 0, length: ns.length)).map {
            ns.substring(with: $0.range(at: 1))
        }
    }

    static func binnenBody(_ xhtml: String) -> String {
        eersteGroep("<body\\b[^>]*>(.*?)</body>", in: xhtml) ?? xhtml
    }

    static func eersteKop(_ html: String) -> String? {
        guard let ruw = eersteGroep("<h[1-6]\\b[^>]*>(.*?)</h[1-6]>", in: html) else { return nil }
        let schoon = striptHTML(ruw)
        return schoon.isEmpty ? nil : String(schoon.prefix(80))
    }

    static func striptHTML(_ html: String) -> String {
        html
            .replacingOccurrences(of: "<script\\b[^>]*>.*?</script>", with: " ",
                                  options: [.regularExpression, .caseInsensitive])
            .replacingOccurrences(of: "<style\\b[^>]*>.*?</style>", with: " ",
                                  options: [.regularExpression, .caseInsensitive])
            .replacingOccurrences(of: "<[^>]+>", with: " ", options: .regularExpression)
            .replacingOccurrences(of: "&nbsp;", with: " ")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .replacingOccurrences(of: "&#39;", with: "'")
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func eersteGroep(_ patroon: String, in tekst: String) -> String? {
        guard let regex = try? NSRegularExpression(
            pattern: patroon, options: [.caseInsensitive, .dotMatchesLineSeparators]
        ) else { return nil }
        let ns = tekst as NSString
        guard let match = regex.firstMatch(in: tekst, range: NSRange(location: 0, length: ns.length)),
              match.numberOfRanges > 1
        else { return nil }
        return ns.substring(with: match.range(at: 1))
    }
}
