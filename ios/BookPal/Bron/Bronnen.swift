import Foundation

/// Een bron waar je series bij kunt volgen: MangaDex, het Internet Archive, of
/// een OPDS-catalogus waarvan je zelf het adres invulde.
struct Bron: Decodable, Sendable, Identifiable {
    let id: Int
    let type: String
    let name: String
    let enabled: Bool
}

/// Eén treffer bij het zoeken.
struct Zoektreffer: Decodable, Sendable, Identifiable {
    let ref: String
    let title: String
    let description: String?
    let year: Int?
    let status: String?
    let languages: [String]
    let coverURL: String?
    /// Volg je deze al? Dan wijst dit naar je eigen serie.
    let subscribedSeriesID: Int?
    /// Heb je dit al in huis onder een andere naam? Dan wordt het een uitgave
    /// van die serie in plaats van een tweede — zie de web-app, waar dezelfde
    /// vergelijking ("Shinya Shokudou" ≈ "Shinya Shokudo") wordt gedaan.
    let existingSeriesID: Int?
    let existingSeriesTitle: String?

    var id: String { ref }

    var alGevolgd: Bool { subscribedSeriesID != nil }

    enum CodingKeys: String, CodingKey {
        case ref, title, description, year, status, languages
        case coverURL = "cover_url"
        case subscribedSeriesID = "subscribed_series_id"
        case existingSeriesID = "existing_series_id"
        case existingSeriesTitle = "existing_series_title"
    }
}

/// Een vertaalgroep die deze reeks (deels) heeft gedaan.
struct Vertaalgroep: Decodable, Sendable, Identifiable {
    let id: String
    let name: String
    let chapters: Int
}

/// Een gevolgde serie.
struct Abonnement: Decodable, Sendable, Identifiable {
    let id: Int
    let sourceID: Int
    let seriesID: Int
    /// `permanent` houdt alles; `readahead` haalt er een paar vooruit en ruimt
    /// de rest weer op.
    let policy: String
    let readaheadN: Int
    let ttlDays: Int
    let language: String
    let seriesTitle: String
    let sourceTitle: String
    let chaptersTotal: Int
    let chaptersLocal: Int
    let availableGroups: [Vertaalgroep]
    let preferredGroupID: String?

    var isPermanent: Bool { policy == "permanent" }

    enum CodingKeys: String, CodingKey {
        case id, policy, language
        case sourceID = "source_id"
        case seriesID = "series_id"
        case readaheadN = "readahead_n"
        case ttlDays = "ttl_days"
        case seriesTitle = "series_title"
        case sourceTitle = "source_title"
        case chaptersTotal = "chapters_total"
        case chaptersLocal = "chapters_local"
        case availableGroups = "available_groups"
        case preferredGroupID = "preferred_group_id"
    }
}

/// Een gekoppeld account bij een tracker.
struct Trackeraccount: Decodable, Sendable, Identifiable {
    let id: Int
    let provider: String
    let enabled: Bool
    /// Proefstand: laat zien wát er gepusht zou worden, maar stuurt niets. Een
    /// nieuw account staat hier standaard op, en dat is de reden dat deze
    /// koppeling uit zichzelf onschadelijk is.
    let dryRun: Bool
    let connected: Bool
    let lastSyncAt: Date?

    var naam: String {
        switch provider {
        case "mal": return "MyAnimeList"
        case "goodreads": return "Goodreads"
        default: return provider
        }
    }

    enum CodingKeys: String, CodingKey {
        case id, provider, enabled, connected
        case dryRun = "dry_run"
        case lastSyncAt = "last_sync_at"
    }
}

/// Wat een ronde van de abonnementen-worker heeft gedaan.
struct Rondeverslag: Decodable, Sendable {
    let subscriptions: Int
    let chaptersAdded: Int
    let downloaded: Int
    let expired: Int
    let errors: [String]

    /// In gewone taal, zodat je na een ronde weet wat er gebeurd is.
    var samenvatting: String {
        var delen = ["\(subscriptions) gecontroleerd"]
        if chaptersAdded > 0 { delen.append("\(chaptersAdded) nieuw") }
        if downloaded > 0 { delen.append("\(downloaded) opgehaald") }
        if expired > 0 { delen.append("\(expired) opgeruimd") }
        if !errors.isEmpty { delen.append("\(errors.count) fout") }
        return delen.joined(separator: ", ")
    }

    enum CodingKeys: String, CodingKey {
        case subscriptions, downloaded, expired, errors
        case chaptersAdded = "chapters_added"
    }
}

/// Wat een push naar een tracker heeft gedaan.
struct Pushverslag: Decodable, Sendable {
    let provider: String
    let pushed: Int
    /// Lijsten en geen aantallen: de server zet er de reden bij, en die wil je
    /// kunnen tonen.
    let skipped: [String]
    let errors: [String]

    var samenvatting: String {
        var delen = ["\(pushed) gepusht"]
        if !skipped.isEmpty { delen.append("\(skipped.count) overgeslagen") }
        if !errors.isEmpty { delen.append("\(errors.count) fout") }
        return delen.joined(separator: ", ")
    }
}

/// Wat er voor één pagina klaarligt — voor het tabelletje in het maakmenu.
struct Paginastatus: Identifiable, Sendable {
    let index: Int
    let vertaling: PageTranslation?
    let kleur: ColourInfo?

    var id: Int { index }

    var vertaaltekst: String {
        guard let vertaling else { return "—" }
        return vertaling.fullPage ? "ingetekend" : "\(vertaling.bubbles.count) vlakken"
    }

    var kleurtekst: String {
        guard let kleur else { return "—" }
        if kleur.native { return "eigen kleur" }
        if !kleur.available { return "—" }
        return kleur.translated ? "kleur + tekst" : "kleur"
    }

    var heeftIets: Bool {
        vertaling != nil || kleur?.available == true || kleur?.native == true
    }
}
