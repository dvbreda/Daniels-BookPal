import Foundation

/// Welke snede van de striplettering een tekstvlak krijgt.
///
/// Gemini levert geen glyphs maar tekst, coördinaten en of het origineel vet of
/// cursief stond — de lettering is dus onze keuze. DigitalStrip heeft drie
/// echte sneden; de vierde (vet én cursief) bestaat niet.
enum Striplettering {
    static let regular = "DigitalStrip"
    static let vet = "DigitalStripBold"
    static let cursief = "DigitalStripItalic"

    /// - Parameter kreet: is dit een korte uitroep of geluidseffect? Alleen die
    ///   worden vet gezet. Bij lopende tekst zou vet een hele alinea nadruk
    ///   geven, en dat leest slechter dan het oplevert; in een strip is bold
    ///   voorbehouden aan "BOEM" en "WAT!?". Het model markeert dat verschil
    ///   niet betrouwbaar, de lengte van de tekst wel.
    static func naam(vet isVet: Bool, cursief isCursief: Bool, kreet: Bool) -> String {
        if isVet && kreet { return vet }
        if isCursief { return cursief }
        return regular
    }
}
