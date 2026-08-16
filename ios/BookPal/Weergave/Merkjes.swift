import SwiftUI

/// Wat er voor deze pagina klaarligt aan vertaling en kleur.
///
/// Los van de knoppen, en dat is het punt: een knop zegt wat er gebeurt als je
/// hem indrukt, een merkje zegt wat er ís. Die twee door elkaar halen — een
/// uitgegrijsde knop die zowel "staat uit" als "is er niet" moet betekenen —
/// laat je raden welke van de twee het is.
///
/// "Al in kleur van de tekenaar" is bewust een eigen tekst en geen lege plek:
/// daar valt niets in te kleuren, en dat is iets anders dan "nog niet gedaan".
struct Merkjes: View {
    let vertaling: PageTranslation?
    let kleur: ColourInfo?

    var body: some View {
        HStack(spacing: 10) {
            merkje(
                icoon: "character.bubble",
                tekst: vertaaltekst,
                aan: vertaling != nil
            )
            merkje(
                icoon: kleur?.native == true ? "paintbrush.pointed" : "paintpalette",
                tekst: kleurtekst,
                aan: kleur?.available == true || kleur?.native == true
            )
        }
        .font(.caption2)
    }

    private var vertaaltekst: String {
        guard let vertaling else { return "geen vertaling" }
        // De beeldstanden leveren een hele hertekende pagina; de tekststand
        // losse vlakken die wij zelf tekenen. Dat verschil zie je op de pagina,
        // dus hoort het merkje het te noemen.
        return vertaling.fullPage ? "ingetekend" : "\(vertaling.bubbles.count) vlakken"
    }

    private var kleurtekst: String {
        guard let kleur else { return "…" }
        if kleur.native { return "al in kleur" }
        if !kleur.available { return "geen kleur" }
        return kleur.translated ? "kleur + tekst" : "kleur"
    }

    private func merkje(icoon: String, tekst: String, aan: Bool) -> some View {
        Label(tekst, systemImage: icoon)
            .labelStyle(.titleAndIcon)
            .foregroundStyle(aan ? .primary : .tertiary)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(
                Capsule().fill(aan ? Color.accentColor.opacity(0.18) : Color.clear)
            )
            .overlay(
                Capsule().strokeBorder(.separator, lineWidth: aan ? 0 : 0.5)
            )
    }
}
