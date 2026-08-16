import SwiftUI

/// Een omslag, met een plaatsvervanger zolang hij er niet is.
///
/// `AsyncImage` en niet een eigen lader: voor omslagen in een raster doet
/// URLSession's eigen cache precies genoeg, en de lezer heeft zijn eigen bron
/// omdat daar wél vooruitgeladen moet worden.
struct OmslagView: View {
    let url: URL
    let titel: String

    var body: some View {
        // Het vakje bepaalt de maat, niet het beeld. Een omslag vullend erin
        // leggen en dán knippen — andersom (beeld eerst, kader erna) rekt de
        // ene tegel breder dan de andere, want elke scan heeft zijn eigen
        // verhouding en een liggende omslag duwt de hele rij scheef.
        Color.clear
            .aspectRatio(2.0 / 3.0, contentMode: .fit)
            .overlay {
                AsyncImage(url: url) { fase in
                    switch fase {
                    case let .success(beeld):
                        beeld.resizable().scaledToFill()
                    case .failure:
                        plaatsvervanger
                    case .empty:
                        ZStack {
                            Rectangle().fill(.quaternary)
                            ProgressView()
                        }
                    @unknown default:
                        plaatsvervanger
                    }
                }
            }
            // `clipped` vóór `clipShape`: het eerste snijdt het overlopende deel
            // écht weg, het tweede tekent alleen een masker. Zonder dat blijft
            // een vullend geschaalde omslag buiten zijn vakje bestaan — zichtbaar
            // niet, maar voor tikken wel. Eén brede omslag legde zo een tikgebied
            // van 1708 punten over de buren heen, en die waren niet meer aan te
            // tikken.
            .clipped()
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .contentShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(.separator, lineWidth: 0.5))
    }

    /// Geen omslag is iets anders dan een fout: veel eigen bestanden hebben er
    /// gewoon geen. Dan liever de titel leesbaar tonen dan een kapot icoon.
    private var plaatsvervanger: some View {
        ZStack {
            Rectangle().fill(.quaternary)
            Text(titel)
                .font(.caption)
                .multilineTextAlignment(.center)
                .padding(6)
                .foregroundStyle(.secondary)
        }
    }
}
