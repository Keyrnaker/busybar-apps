import Foundation

enum BarConnection: Equatable {
    case unknown
    case connected(transport: String, apiVersion: String)
    case disconnected

    var label: String {
        switch self {
        case .unknown: return "BUSY Bar · 확인 중"
        case .connected(let transport, let v): return "BUSY Bar · \(transport) 연결됨 (API \(v))"
        case .disconnected: return "BUSY Bar · 연결 안 됨"
        }
    }
}

enum BarProbe {
    static func request(host: String, token: String) -> URLRequest {
        var r = URLRequest(url: URL(string: "http://\(host)/api/version")!)
        r.timeoutInterval = 2
        if !token.isEmpty { r.setValue(token, forHTTPHeaderField: "X-API-Token") }
        return r
    }

    static func interpret(host: String, data: Data?, statusCode: Int?, error: Error?) -> BarConnection {
        guard error == nil, statusCode == 200 else { return .disconnected }
        var version = "?"
        if let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let v = obj["api_semver"] as? String {
            version = v
        }
        return .connected(transport: host == "10.0.4.20" ? "USB" : "Wi-Fi", apiVersion: version)
    }
}

@MainActor
final class BarStatusMonitor: ObservableObject {
    @Published private(set) var connection: BarConnection = .unknown
    private let session: URLSession
    private var task: Task<Void, Never>?

    init(session: URLSession = .shared) { self.session = session }

    func start(interval: TimeInterval = 5, credentials: @escaping () -> (host: String, token: String)) {
        stop()
        task = Task { [weak self] in
            while !Task.isCancelled {
                let c = credentials()
                await self?.probeOnce(host: c.host, token: c.token)
                try? await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
            }
        }
    }

    func stop() { task?.cancel(); task = nil }
    var isMonitoring: Bool { task != nil }

    func probeOnce(host: String, token: String) async {
        let req = BarProbe.request(host: host, token: token)
        do {
            let (data, response) = try await session.data(for: req)
            connection = BarProbe.interpret(host: host, data: data, statusCode: (response as? HTTPURLResponse)?.statusCode, error: nil)
        } catch {
            connection = BarProbe.interpret(host: host, data: nil, statusCode: nil, error: error)
        }
    }
}
