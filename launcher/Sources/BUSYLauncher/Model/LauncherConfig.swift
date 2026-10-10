import Foundation

struct LauncherConfig: Codable, Equatable {
    var host: String = "10.0.4.20"
    var token: String = ""
    var resumeLastApp: Bool = true
    var lastAppID: String? = nil
    var extraAppsDirs: [String] = []
    var devRepoPath: String? = nil

    var isUSBHost: Bool { host == "10.0.4.20" }

    // Tolerate missing keys (older files) and ignore unknown ones (newer files).
    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        host = try c.decodeIfPresent(String.self, forKey: .host) ?? "10.0.4.20"
        token = try c.decodeIfPresent(String.self, forKey: .token) ?? ""
        resumeLastApp = try c.decodeIfPresent(Bool.self, forKey: .resumeLastApp) ?? true
        lastAppID = try c.decodeIfPresent(String.self, forKey: .lastAppID)
        extraAppsDirs = try c.decodeIfPresent([String].self, forKey: .extraAppsDirs) ?? []
        devRepoPath = try c.decodeIfPresent(String.self, forKey: .devRepoPath)
    }
}

final class ConfigStore {
    let fileURL: URL
    init(fileURL: URL) { self.fileURL = fileURL }

    func load() -> LauncherConfig {
        guard let data = try? Data(contentsOf: fileURL) else { return LauncherConfig() }
        do {
            return try JSONDecoder().decode(LauncherConfig.self, from: data)
        } catch {
            let backup = fileURL.deletingPathExtension().appendingPathExtension("corrupt.json")
            try? FileManager.default.removeItem(at: backup)
            try? FileManager.default.moveItem(at: fileURL, to: backup)
            return LauncherConfig()
        }
    }

    func save(_ config: LauncherConfig) throws {
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(config).write(to: fileURL, options: .atomic)
    }
}
