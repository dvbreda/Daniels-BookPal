import SwiftUI

/// De balk boven een lijst die uit `Bibliotheekcache` komt in plaats van vers
/// opgehaald te zijn — zodat je weet dat wat je ziet mogelijk niet meer klopt
/// met wat er nu echt op de NAS staat.
struct Offlinebanner: View {
    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "wifi.slash")
            Text("Geen verbinding — dit is de laatste bekende stand.")
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .padding(.horizontal)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.orange.opacity(0.12))
    }
}
