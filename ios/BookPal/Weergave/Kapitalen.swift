import Foundation

/// Striplettering in kapitalen terugbrengen tot gewone zinnen.
///
/// Alleen voor het paneeltje waarin je het origineel naleest. Op de pagina zelf
/// blijft de tekst in kapitalen staan — dát is de lettering, en een vertaling in
/// onderkast daartussen valt op als ingeplakt. Maar los gelezen, in een blokje
/// tekst, leest "WAIT, YOU'RE PRESIDENT NARISAWA!" als geschreeuw.
enum Kapitalen {
    /// Zinnen met een hoofdletter, de rest klein — maar alleen als de brontekst
    /// écht helemaal in kapitalen staat. Een zin die al normaal geschreven is
    /// blijft onaangeroerd; daar zou omzetten juist informatie weggooien.
    static func normaliseer(_ tekst: String) -> String {
        guard isHelemaalKapitaal(tekst) else { return tekst }

        var uit = ""
        var beginZin = true
        var vorige: Character?

        for teken in tekst.lowercased() {
            if beginZin, teken.isLetter {
                uit.append(Character(teken.uppercased()))
                beginZin = false
            } else {
                uit.append(teken)
            }
            // Na een punt, vraagteken of uitroepteken begint een nieuwe zin.
            // Puntjes (…) tellen als één einde, niet als drie.
            if ".!?".contains(teken) {
                beginZin = true
            } else if teken.isLetter || teken.isNumber {
                beginZin = false
            }
            vorige = teken
        }
        _ = vorige

        return herstelIk(uit)
    }

    /// Is dit helemaal in kapitalen gezet? Bij minder dan drie letters valt daar
    /// niets over te zeggen — "EH?" is geen schreeuw maar een kreet.
    static func isHelemaalKapitaal(_ tekst: String) -> Bool {
        let letters = tekst.filter(\.isLetter)
        guard letters.count >= 3 else { return false }
        return letters.allSatisfy(\.isUppercase)
    }

    /// Het Engelse "I" weer als hoofdletter. Zonder dit lees je "i know" en dat
    /// ziet er verkeerder uit dan het probleem dat we oplosten.
    private static func herstelIk(_ tekst: String) -> String {
        tekst.replacingOccurrences(
            of: "\\bi\\b",
            with: "I",
            options: [.regularExpression]
        )
    }
}
