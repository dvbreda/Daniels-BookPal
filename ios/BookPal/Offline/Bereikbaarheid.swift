import Network
import Observation

/// Is er ígens netwerk? Zegt niets over de NAS specifiek — dat weet je pas na
/// een geslaagde aanroep — maar het scheelt een timeout van een paar seconden
/// wachten op elk scherm terwijl je in het vliegtuig zit.
@MainActor
@Observable
final class Bereikbaarheid {
    static let gedeeld = Bereikbaarheid()

    private(set) var heeftNetwerk = true
    private let monitor = NWPathMonitor()

    private init() {
        monitor.pathUpdateHandler = { [weak self] pad in
            Task { @MainActor in self?.heeftNetwerk = pad.status == .satisfied }
        }
        monitor.start(queue: DispatchQueue(label: "bookpal.netwerkstatus"))
    }
}
