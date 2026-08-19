import SwiftUI
import WebKit

/// De Oneindige Bieb, in een webweergave.
///
/// Die app draait op dezelfde NAS op poort 1996 en is server-gerenderde HTML
/// zonder client-JS — gebouwd voor e-ink, en dus precies het soort pagina dat
/// zich in een webweergave net zo goed gedraagt als in Safari. Een eigen GUI
/// nabouwen zou werk zijn dat niets toevoegt zolang die pagina's het al doen.
///
/// De tab verschijnt alleen als de bieb antwoordt. Een tab die naar een dode
/// poort wijst is erger dan geen tab: dan tik je erop en staar je naar een
/// foutmelding zonder te weten of het aan jou ligt.
struct BiebView: View {
    let adres: URL

    @State private var laadt = true
    @State private var fout: String?

    var body: some View {
        ZStack {
            Webweergave(adres: adres, laadt: $laadt, fout: $fout)
            if laadt {
                ProgressView("De bieb openen…")
            }
            if let fout {
                ContentUnavailableView {
                    Label("Bieb niet bereikbaar", systemImage: "books.vertical")
                } description: {
                    Text(fout)
                }
            }
        }
        .ignoresSafeArea(edges: .bottom)
    }
}

/// `WKWebView` in SwiftUI. Bewust zonder eigen navigatiebalk: de bieb heeft
/// zijn eigen menu bovenin, en twee balken boven elkaar is verwarrend.
private struct Webweergave: UIViewRepresentable {
    let adres: URL
    @Binding var laadt: Bool
    @Binding var fout: String?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let weergave = WKWebView()
        weergave.navigationDelegate = context.coordinator
        weergave.allowsBackForwardNavigationGestures = true
        weergave.load(URLRequest(url: adres))
        return weergave
    }

    func updateUIView(_ weergave: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate {
        private let ouder: Webweergave

        init(_ ouder: Webweergave) { self.ouder = ouder }

        func webView(_ weergave: WKWebView, didFinish navigatie: WKNavigation!) {
            ouder.laadt = false
            ouder.fout = nil
        }

        func webView(
            _ weergave: WKWebView, didFail navigatie: WKNavigation!, withError fout: Error
        ) {
            ouder.laadt = false
            ouder.fout = fout.localizedDescription
        }

        func webView(
            _ weergave: WKWebView,
            didFailProvisionalNavigation navigatie: WKNavigation!,
            withError fout: Error
        ) {
            ouder.laadt = false
            ouder.fout = fout.localizedDescription
        }
    }
}

/// Kijkt of de bieb draait, zodat de tab alleen verschijnt als er iets te zien is.
@MainActor
@Observable
final class Bieb {
    static let gedeeld = Bieb()

    private(set) var adres: URL?

    private init() {}

    /// Op dezelfde host als BookPal, poort 1996. Afgeleid en niet apart in te
    /// stellen: het is dezelfde NAS, en nog een adresveld is nog een ding dat
    /// uit de pas kan lopen.
    func zoek(bij server: URL?) async {
        guard let host = server?.host() else { adres = nil; return }
        guard var onderdelen = URLComponents(string: "http://\(host)") else { return }
        onderdelen.port = 1996
        guard let kandidaat = onderdelen.url else { adres = nil; return }

        var verzoek = URLRequest(url: kandidaat)
        verzoek.timeoutInterval = 4
        verzoek.httpMethod = "HEAD"
        guard let (_, antwoord) = try? await URLSession.shared.data(for: verzoek),
              let http = antwoord as? HTTPURLResponse, (200..<400).contains(http.statusCode)
        else {
            adres = nil
            return
        }
        adres = kandidaat
    }
}
