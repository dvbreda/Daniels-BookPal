import Foundation

/// Knipt hoofdstuk-HTML in losse blokken: alinea's, koppen, plaatjes, citaten,
/// lijsten.
///
/// Overgenomen uit Plantpal, en om twee redenen nodig. Een heel hoofdstuk in één
/// keer naar `NSAttributedString` duwen is traag en kost veel geheugen; per blok
/// kan het lui en gecachet. En het blok is meteen de eenheid waarin de leesplek
/// bewaard wordt — fijner dan een teken-offset, want een blok blijft hetzelfde
/// als je de letters groter zet.
enum HTMLBlokken {
    static func splits(_ html: String) -> [String] {
        // Blok-elementen op het hoogste niveau; wat ertussen valt is losse
        // tekst die we alsnog als alinea meenemen.
        let patroon =
            "<(p|h[1-6]|figure|blockquote|ul|ol|dl|div|table|pre)\\b[^>]*>.*?</\\1>"
            + "|<(img|hr)\\b[^>]*/?>"
        guard let regex = try? NSRegularExpression(
            pattern: patroon, options: [.caseInsensitive, .dotMatchesLineSeparators]
        ) else { return [html] }

        let ns = html as NSString
        var blokken: [String] = []
        var cursor = 0

        func voegLosseTekstToe(_ stuk: String) {
            let kaal = stuk
                .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !kaal.isEmpty { blokken.append("<p>\(stuk)</p>") }
        }

        for match in regex.matches(in: html, range: NSRange(location: 0, length: ns.length)) {
            if match.range.location > cursor {
                voegLosseTekstToe(
                    ns.substring(with: NSRange(
                        location: cursor, length: match.range.location - cursor
                    ))
                )
            }
            blokken.append(ns.substring(with: match.range))
            cursor = match.range.location + match.range.length
        }
        if cursor < ns.length { voegLosseTekstToe(ns.substring(from: cursor)) }

        return blokken.isEmpty ? [html] : blokken
    }
}
