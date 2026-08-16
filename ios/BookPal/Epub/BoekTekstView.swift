import SwiftUI
import UIKit

/// Leesinstellingen die de lezer live kan omzetten.
@MainActor
@Observable
final class LeesInstellingen {
    var lettergrootte: Double {
        didSet { UserDefaults.standard.set(lettergrootte, forKey: "epubLettergrootte") }
    }
    var regelafstand: Double {
        didSet { UserDefaults.standard.set(regelafstand, forKey: "epubRegelafstand") }
    }

    init() {
        let bewaard = UserDefaults.standard.double(forKey: "epubLettergrootte")
        lettergrootte = bewaard > 0 ? bewaard : 18
        let afstand = UserDefaults.standard.double(forKey: "epubRegelafstand")
        regelafstand = afstand > 0 ? afstand : 1.4
    }
}

/// Eén blok opgemaakte boektekst.
///
/// `NSAttributedString(html:)` doet het echte werk: die begrijpt koppen,
/// cursief, lijsten én `file://`-afbeeldingen, dus de plaatjes uit de epub komen
/// gewoon in de tekst te staan. Zelf een HTML-subset naar SwiftUI-views vertalen
/// zou veel meer code zijn en minder goed.
struct OpgemaakteTekst: View {
    let html: String
    let lettergrootte: Double
    let regelafstand: Double
    let donker: Bool

    @State private var opgemaakt: NSAttributedString?

    var body: some View {
        Group {
            if let opgemaakt {
                // Een UITextView en geen SwiftUI-`Text`: die laatste negeert
                // `lineHeightMultiple`, en juist de regelafstand maakt bij een
                // boek het verschil tussen lezen en turen.
                TekstBlok(attributed: opgemaakt)
            } else {
                // Geen "bezig"-tekst: die zou bij elk blok even opflitsen.
                Color.clear.frame(height: 1)
            }
        }
        .task(id: sleutel) { opgemaakt = Self.gecachet(sleutel: sleutel, maak: maak) }
    }

    private var sleutel: String { "\(html.hashValue)-\(lettergrootte)-\(regelafstand)-\(donker)" }

    /// HTML omzetten is duur, dus één keer per blok en per opmaakstand.
    ///
    /// Blijft op de hoofdthread, want `NSAttributedString(html:)` is WebKit
    /// onder water en die eist dat. Dat is precies waarom een hoofdstuk eerst in
    /// blokken wordt geknipt: een heel hoofdstuk zou hier merkbaar blokkeren,
    /// een alinea niet.
    private static let cache = NSCache<NSString, NSAttributedString>()

    private static func gecachet(
        sleutel: String, maak: () -> NSAttributedString?
    ) -> NSAttributedString? {
        if let klaar = cache.object(forKey: sleutel as NSString) { return klaar }
        guard let nieuw = maak() else { return nil }
        cache.setObject(nieuw, forKey: sleutel as NSString)
        return nieuw
    }

    private func maak() -> NSAttributedString? {
        Self.render(html: html, grootte: lettergrootte, afstand: regelafstand, donker: donker)
    }

    static func render(
        html: String, grootte: Double, afstand: Double, donker: Bool
    ) -> NSAttributedString? {
        let kleur = donker ? "#E8E8E8" : "#111111"
        let omhulsel = """
        <meta charset="utf-8">
        <style>
          body { font-family: -apple-system, Georgia, serif; font-size: \(grootte)px;
                 line-height: \(afstand); color: \(kleur); }
          /* De marge zelf zetten: de HTML-importer geeft een `p` anders een
             royale standaardmarge, en omdat elk blok apart wordt opgemaakt
             tellen die van twee buren bij elkaar op. Op een inhoudsopgave van
             losse regels stond daardoor alles ver uit elkaar. */
          p { margin: 0 0 0.55em; }
          img { max-width: 100%; height: auto; }
          h1,h2,h3,h4,h5,h6 { line-height: 1.2; margin: 0.8em 0 0.4em; }
          blockquote { margin: 0 0 0.55em 1em; opacity: 0.85; }
        </style>
        \(html)
        """
        guard let data = omhulsel.data(using: .utf8) else { return nil }
        return try? NSAttributedString(
            data: data,
            options: [.documentType: NSAttributedString.DocumentType.html,
                      .characterEncoding: String.Encoding.utf8.rawValue],
            documentAttributes: nil
        )
    }
}

/// De UITextView eromheen: alleen lezen, geen scrollen (dat doet de lijst
/// erbuiten), en hij groeit mee met zijn inhoud.
private struct TekstBlok: UIViewRepresentable {
    let attributed: NSAttributedString

    func makeUIView(context: Context) -> UITextView {
        let weergave = UITextView()
        weergave.isEditable = false
        weergave.isScrollEnabled = false
        weergave.backgroundColor = .clear
        weergave.textContainerInset = .zero
        weergave.textContainer.lineFragmentPadding = 0
        weergave.adjustsFontForContentSizeCategory = true
        weergave.setContentCompressionResistancePriority(.required, for: .vertical)
        return weergave
    }

    func updateUIView(_ weergave: UITextView, context: Context) {
        if weergave.attributedText != attributed {
            weergave.attributedText = attributed
        }
    }

    /// Zonder dit claimt elk blok meer hoogte dan het nodig heeft: SwiftUI kent
    /// de hoogte van een UIKit-weergave niet en vult dan de voorgestelde ruimte.
    /// Bij een lijst van korte alinea's stond daardoor elke regel een halve
    /// schermhoogte uit elkaar.
    func sizeThatFits(
        _ voorstel: ProposedViewSize, uiView: UITextView, context: Context
    ) -> CGSize? {
        guard let breedte = voorstel.width, breedte > 0 else { return nil }
        let nodig = uiView.sizeThatFits(
            CGSize(width: breedte, height: .greatestFiniteMagnitude)
        )
        return CGSize(width: breedte, height: ceil(nodig.height))
    }
}
