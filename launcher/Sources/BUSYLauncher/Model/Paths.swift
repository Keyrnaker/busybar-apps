import Foundation

struct Paths {
    let root: URL
    var apps: URL { root.appendingPathComponent("apps") }
    var venvs: URL { root.appendingPathComponent("venvs") }
    var logs: URL { root.appendingPathComponent("logs") }
    var config: URL { root.appendingPathComponent("config.json") }
    var galleryCache: URL { root.appendingPathComponent("gallery-cache.json") }

    static let live: Paths = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return Paths(root: base.appendingPathComponent("BUSY Launcher"))
    }()

    func ensureDirectories() throws {
        for dir in [root, apps, venvs, logs] {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        }
    }
}
