import Foundation
import Security

/// De eigen Gemini-sleutel, voor als de app zonder NAS vertaalt.
///
/// In de Keychain en niet in `UserDefaults`: de serversleutel heeft eerder
/// een keer in platte tekst in de containerlogs gestaan (zie CLAUDE.md), en
/// een tweede kopie van diezelfde soort sleutel hoort niet in een leesbaar
/// plist-bestand op het toestel te staan. De Keychain is hier geen overkill —
/// het is de standaardplek voor precies dit soort geheim.
enum Sleutelketen {
    private static let dienst = "nl.danielvanbreda.bookpal.gemini"

    static func bewaar(_ sleutel: String) {
        verwijder()
        guard !sleutel.isEmpty else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: dienst,
            kSecValueData as String: Data(sleutel.utf8),
            // Alleen op dit toestel, ontgrendeld: een Gemini-sleutel hoeft niet
            // mee te gaan in een iCloud-back-up van de sleutelhanger.
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    static func lees() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: dienst,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var resultaat: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &resultaat) == errSecSuccess,
              let data = resultaat as? Data
        else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func verwijder() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: dienst,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
