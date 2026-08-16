import SwiftUI

/// Alles wat je aan de weergave kunt omzetten, achter één knop.
///
/// Dezelfde afweging als aan de webkant, waar de leesbalk was uitgegroeid tot
/// zestien knoppen: op een telefoon is dat vier regels over je strip heen. In de
/// balk staat alleen wat je tijdens het lezen echt omzet; de rest zit hier.
struct LezerInstellingenSheet: View {
    @Binding var weergave: Weergavestand
    @Binding var dubbel: Bool
    @Binding var passend: Passend
    @Binding var rastervorm: Rastervorm
    @Binding var bijsnijden: Bool
    @Binding var contrast: Int
    @Binding var rechtsNaarLinks: Bool
    @Binding var paneelmarge: Double

    @Environment(\.dismiss) private var sluit

    private var doorlopend: Bool { weergave == .doorlopend }
    private var rasterAan: Bool { rastervorm.cellen > 0 }

    var body: some View {
        NavigationStack {
            Form {
                Section("Weergave") {
                    Picker("Weergave", selection: $weergave) {
                        ForEach(Weergavestand.allCases) { stand in
                            Text(stand.naam).tag(stand)
                        }
                    }
                    .pickerStyle(.segmented)

                    Toggle("Dubbele pagina's", isOn: $dubbel)
                        // Bij doorlopend scrollen bestaan spreads niet, en bij
                        // rasterzoom kijk je juist naar een deel van één pagina.
                        .disabled(doorlopend || rasterAan)

                    Picker("Leesrichting", selection: $rechtsNaarLinks) {
                        Text("Links → rechts").tag(false)
                        Text("Rechts → links").tag(true)
                    }
                }

                Section("Passend maken") {
                    Picker("Passend", selection: $passend) {
                        ForEach(Passend.allCases) { stand in
                            Text(stand.naam).tag(stand)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section {
                    Picker("Raster", selection: $rastervorm) {
                        Text("Uit").tag(Rastervorm.uit)
                        ForEach(Rastervorm.keuzes) { vorm in
                            Text(vorm.naam).tag(vorm)
                        }
                    }
                    .disabled(doorlopend)
                } header: {
                    Text("Rasterzoom")
                } footer: {
                    Text(
                        "Tikken gaat per cel, op ware grootte — rechts verder, links terug. "
                            + "Een mangapagina is op een telefoon anders leesbaar noch te "
                            + "overzien. Ook met de rasterknop in de leesbalk door te lopen."
                    )
                }

                Section {
                    VStack(alignment: .leading) {
                        Text("Marge rond een paneel: \(Int(paneelmarge * 100))%")
                        Slider(value: $paneelmarge, in: 0...0.10, step: 0.01)
                    }
                } header: {
                    Text("Panelen")
                } footer: {
                    Text(
                        "Lucht rondom het paneel, als deel van de paginabreedte. Nul zet het "
                            + "paneel strak in beeld; wat marge laat zien waar het op de "
                            + "bladzijde staat."
                    )
                }

                Section {
                    Toggle("Bijsnijden", isOn: $bijsnijden)
                    Toggle(
                        "Contrast oprekken",
                        isOn: Binding(
                            get: { contrast > 100 },
                            set: { contrast = $0 ? 140 : 100 }
                        )
                    )
                } header: {
                    Text("Beeld")
                } footer: {
                    Text(
                        "Bijsnijden haalt de egale rand weg — op een klein scherm zo een vijfde. "
                            + "Contrast helpt bij bleke scans. Allebei doet de server."
                    )
                }

                Section {
                    Text(
                        "Vertalen en inkleuren kost geld en gebeurt daarom in de web-app, "
                            + "niet hier. Wat er al ligt zie je wel: de knoppen in de leesbalk "
                            + "staan aan zodra er voor deze pagina iets klaarstaat."
                    )
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Weergave")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Klaar") { sluit() }
                }
            }
        }
    }
}
