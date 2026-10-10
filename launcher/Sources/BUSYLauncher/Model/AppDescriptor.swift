import Foundation

enum AppKind: Equatable {
    case gallery
    case package(repoRoot: URL)
}

struct LaunchCommand: Equatable {
    let executable: URL
    let arguments: [String]
    let workingDirectory: URL
    let environment: [String: String]
}

struct AppDescriptor: Identifiable, Equatable {
    let id: String
    let directory: URL
    let kind: AppKind
    let manifest: AppManifest
    let iconURL: URL?
    let hasRequirements: Bool

    /// The process the launcher spawns. `includeToken=false` is the retry path for apps without a --token flag.
    func command(python: URL, host: String, token: String, includeToken: Bool = true) -> LaunchCommand {
        var args: [String]
        let cwd: URL
        switch kind {
        case .gallery:
            args = ["app.py"]
            cwd = directory
        case .package(let repoRoot):
            args = ["-m", "apps.\(id).app"]
            cwd = repoRoot
        }
        args += ["--host", host]
        if includeToken, !token.isEmpty { args += ["--token", token] }
        var env = ProcessInfo.processInfo.environment
        env["BUSYBAR_HOST"] = host
        env["BUSYBAR_TOKEN"] = token
        env["PYTHONUNBUFFERED"] = "1"
        return LaunchCommand(executable: python, arguments: args, workingDirectory: cwd, environment: env)
    }
}
