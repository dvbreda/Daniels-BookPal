import SwiftUI

/// De vertaalde tekstvlakken over de pagina heen.
///
/// Een overlay en geen ingebakken pagina: de pagina zelf blijft één gedeelde
/// afbeelding, dus aan- en uitzetten hoeft hem niet opnieuw op te halen. En de
/// tekst blijft scherp als je inzoomt, want hij wordt getekend en niet
/// meegeschaald met een plaatje. Tik op een ballon voor het origineel.
struct BallonOverlay: View {
    let bubbles: [Bubble]
    /// Het gebied waar de pagina echt staat. De vlakken zijn genormaliseerd op
    /// de pagina, niet op het scherm, en een pagina die met `scaledToFit` in
    /// beeld staat heeft balken links/rechts of boven/onder.
    let paginakader: CGRect
    @Binding var origineelVan: Bubble?

    var body: some View {
        // De maten voor de hele pagina in één keer: pas dán is te zien welke
        // ballon een uitschieter is.
        let maten = lettergroottes()
        ZStack(alignment: .topLeading) {
            // Een doorzichtig vlak dat de hele pagina vult. Zonder dit is de
            // ZStack zo groot als zijn grootste ballon, en `.frame` centreert
            // die kleine stapel dan in het grote kader — waardoor élke ballon
            // een halve pagina naar rechtsonder schoof. Vandaar ook expliciet
            // `alignment: .topLeading`: `.frame` centreert standaard.
            Color.clear
            ForEach(Array(bubbles.enumerated()), id: \.offset) { index, bubble in
                ballon(bubble, grootte: maten.indices.contains(index) ? maten[index] : 12)
            }
        }
        .frame(width: paginakader.width, height: paginakader.height, alignment: .topLeading)
        .offset(x: paginakader.minX, y: paginakader.minY)
    }

    /// Per ballon de grootste maat die past, daarna begrensd: korte kreten mogen
    /// de ballon vullen, lopende tekst krijgt overal dezelfde leesmaat.
    private func lettergroottes() -> [CGFloat] {
        let gemeten = bubbles.map { bubble -> CGFloat in
            let vlak = Ballonnen.rekOp(bubble.box)
            guard vlak.count == 4 else { return 12 }
            let breedte = max(1, (vlak[2] - vlak[0]) * paginakader.width)
            let hoogte = max(1, (vlak[3] - vlak[1]) * paginakader.height)
            // De schatting van de web-lezer als bovengrens — die houdt een kort
            // woord ervan af beeldvullend te worden.
            let schaal = Ballonnen.letterschaal(vlak: vlak, tekens: bubble.tekst.count)
            let bovengrens = max(8, min(breedte, hoogte) * 0.30 * schaal)
            return Ballonnen.passendeGrootte(
                bubble.tekst,
                // Een marge binnen de pilvorm: in de hoeken van een ronde ballon
                // past geen tekst.
                in: CGSize(width: breedte * 0.82, height: hoogte * 0.82),
                fontnaam: Striplettering.naam(
                    vet: bubble.bold, cursief: bubble.italic, kreet: bubble.isKreet
                ),
                maximum: bovengrens
            )
        }
        return Ballonnen.begrens(
            gemeten,
            tekens: bubbles.map(\.tekst.count),
            leesmaat: paginakader.height * Ballonnen.leesmaatDeel
        )
    }

    @ViewBuilder
    private func ballon(_ bubble: Bubble, grootte: CGFloat) -> some View {
        let vlak = Ballonnen.rekOp(bubble.box)
        if vlak.count == 4 {
            let x = vlak[0] * paginakader.width
            let y = vlak[1] * paginakader.height
            let breedte = max(1, (vlak[2] - vlak[0]) * paginakader.width)
            let hoogte = max(1, (vlak[3] - vlak[1]) * paginakader.height)

            Text(bubble.tekst)
                // De echte snede uit het lettertype en niet er eentje namaken:
                // Gemini geeft per vlak door of het origineel vet of cursief
                // stond, en DigitalStrip heeft daar eigen sneden voor.
                .font(.custom(
                    Striplettering.naam(
                        vet: bubble.bold, cursief: bubble.italic, kreet: bubble.isKreet
                    ),
                    size: grootte
                ))
                .minimumScaleFactor(0.3)
                .multilineTextAlignment(.center)
                .foregroundStyle(.black)
                .padding(2)
                .frame(width: breedte, height: hoogte)
                // Pilvorm: die volgt de kortste zijde, dus een vierkant vlak
                // wordt een cirkel. Dekt merkbaar minder tekening af en lijkt op
                // wat eronder zit.
                .background(
                    RoundedRectangle(cornerRadius: min(breedte, hoogte) / 2)
                        .fill(.white)
                )
                // `position` en niet `offset`: die eerste zet het midden op een
                // punt in de ouder, los van waar de lay-out hem had gelegd. Dat
                // is precies wat je wilt bij vlakken die op vaste coördinaten
                // van de pagina horen te staan.
                .position(x: x + breedte / 2, y: y + hoogte / 2)
                // Dubbeltik en geen enkele tik: één tik is bladeren. Een
                // ballon beslaat een flink deel van de pagina, dus met één tik
                // zou je precies daar niet meer kunnen omslaan.
                .onTapGesture(count: 2) { origineelVan = bubble }
        }
    }
}

/// Het origineel van één ballon, als je erop tikt.
struct OrigineelSheet: View {
    let bubble: Bubble
    @Environment(\.dismiss) private var sluit

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Origineel").font(.caption).foregroundStyle(.secondary)
                        // Genormaliseerd: los gelezen is striplettering in
                        // kapitalen geschreeuw. Op de pagina blijft hij wél in
                        // kapitalen staan.
                        Text(Kapitalen.normaliseer(bubble.source)).font(.body)
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Vertaling").font(.caption).foregroundStyle(.secondary)
                        Text(bubble.translation).font(.body)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
            }
            .navigationTitle("Tekstvlak")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Klaar") { sluit() }
                }
            }
        }
    }
}
