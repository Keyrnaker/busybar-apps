import Foundation

enum AppRegistry {
    static func scan(directories: [URL], fileManager: FileManager = .default) -> [AppDescriptor] {
        var seen = Set<String>()
        var result: [AppDescriptor] = []
        for dir in directories {
            guard let entries = try? fileManager.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.isDirectoryKey], options: [.skipsHiddenFiles]) else { continue }
            for entry in entries.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                let name = entry.lastPathComponent
                if name.hasPrefix(".") || name.hasPrefix("_") || name == "tests" { continue }
                guard let app = descriptor(for: entry, fileManager: fileManager), !seen.contains(app.id) else { continue }
                seen.insert(app.id)
                result.append(app)
            }
        }
        return result.sorted { $0.manifest.name.localizedCaseInsensitiveCompare($1.manifest.name) == .orderedAscending }
    }

    static func descriptor(for directory: URL, fileManager: FileManager = .default) -> AppDescriptor? {
        var isDir: ObjCBool = false
        guard fileManager.fileExists(atPath: directory.path, isDirectory: &isDir), isDir.boolValue else { return nil }
        let has = { (file: String) in fileManager.fileExists(atPath: directory.appendingPathComponent(file).path) }
        guard has("app.py") else { return nil }
        let id = directory.lastPathComponent

        var kind = AppKind.gallery
        let parent = directory.deletingLastPathComponent()
        let repoRoot = parent.deletingLastPathComponent().standardizedFileURL
        if has("__init__.py"), parent.lastPathComponent == "apps",
           fileManager.fileExists(atPath: repoRoot.appendingPathComponent("pytest.ini").path) {
            kind = .package(repoRoot: repoRoot)
        }

        let manifestText = (try? String(contentsOf: directory.appendingPathComponent("manifest.yaml"), encoding: .utf8)) ?? ""
        let manifest = ManifestParser.parse(manifestText, fallbackName: id)
        let icon = directory.appendingPathComponent("icon.png")
        return AppDescriptor(
            id: id,
            directory: directory.standardizedFileURL,
            kind: kind,
            manifest: manifest,
            iconURL: has("icon.png") ? icon : nil,
            hasRequirements: has("requirements.txt")
        )
    }
}
