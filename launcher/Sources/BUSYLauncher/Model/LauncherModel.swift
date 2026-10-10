import Foundation
import AppKit
import Combine

@MainActor
final class LauncherModel: ObservableObject {
    @Published var config: LauncherConfig
    @Published private(set) var apps: [AppDescriptor] = []
    @Published var notice: String? = nil
    @Published var preparing: String? = nil
    /// User chose "연결 끊기": no app runs and the bar is not polled until "연결".
    @Published private(set) var detached = false

    let paths: Paths
    let runner: AppRunner
    let bar: BarStatusMonitor
    private let store: ConfigStore
    private let bundleResources: URL?
    private let bundleURL: URL
    private let pidStore: PidStore
    private var cancellables: Set<AnyCancellable> = []

    init(paths: Paths = .live,
         factory: ChildProcessFactory = FoundationProcessFactory(),
         bundleResources: URL? = Bundle.main.resourceURL,
         bundleURL: URL = Bundle.main.bundleURL) {
        self.paths = paths
        self.store = ConfigStore(fileURL: paths.config)
        self.config = store.load()
        let pidStore = PidStore(fileURL: paths.root.appendingPathComponent("running.pid"))
        self.pidStore = pidStore
        self.runner = AppRunner(factory: factory, pidStore: pidStore)
        self.bar = BarStatusMonitor()
        self.bundleResources = bundleResources
        self.bundleURL = bundleURL
        try? paths.ensureDirectories()
        refreshApps()
        // SwiftUI only observes this object; relay the runner's and monitor's changes (icon dot, status line).
        runner.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &cancellables)
        bar.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &cancellables)
        LauncherModelRegistry.model = self
    }

    /// A previous launcher that was killed (not quit) may have left its child alive. Call once at startup,
    /// after the second-instance check: a record whose launcher is still alive belongs to that instance.
    func reapOrphans() { OrphanReaper.reap(store: pidStore) }

    // MARK: directories

    static func inferRepo(from bundleURL: URL, exists: (URL) -> Bool = { FileManager.default.fileExists(atPath: $0.path) }) -> URL? {
        var dir = bundleURL.deletingLastPathComponent()
        for _ in 0..<12 {
            if exists(dir.appendingPathComponent("pytest.ini")), exists(dir.appendingPathComponent("apps")) { return dir }
            let parent = dir.deletingLastPathComponent()
            if parent.path == dir.path { break }
            dir = parent
        }
        return nil
    }

    func devRepoURL() -> URL? {
        if let p = config.devRepoPath, !p.isEmpty { return URL(fileURLWithPath: p) }
        return Self.inferRepo(from: bundleURL)
    }

    var appDirectories: [URL] {
        var dirs = [paths.apps]
        if let repo = devRepoURL() { dirs.append(repo.appendingPathComponent("apps")) }
        dirs += config.extraAppsDirs.filter { !$0.isEmpty }.map { URL(fileURLWithPath: $0) }
        return dirs
    }

    func refreshApps() { apps = AppRegistry.scan(directories: appDirectories) }

    // MARK: running

    func isActive(_ app: AppDescriptor) -> Bool { runner.state.activeAppID == app.id }

    func failureReason(for app: AppDescriptor) -> String? {
        if case .failed(let id, let reason) = runner.state, id == app.id { return reason }
        return nil
    }

    func statusSuffix(for app: AppDescriptor) -> String {
        switch runner.state {
        case .starting(let id) where id == app.id: return " (시작 중…)"
        case .failed(let id, _) where id == app.id: return " (중단됨)"
        case .exited(let id, _) where id == app.id: return " (종료됨)"
        default: return ""
        }
    }

    var statusLine: String { detached ? "BUSY Bar · 연결 끊음" : bar.connection.label }

    func disconnect() async {
        await stopCurrent()
        bar.stop()
        detached = true
    }

    func connect() {
        detached = false
        startMonitoring()
    }

    func toggle(_ app: AppDescriptor) async {
        if detached { connect() }
        if isActive(app) { await stopCurrent(); return }
        guard let runtime = PythonRuntime.resolve(bundleResources: bundleResources, devRepo: devRepoURL()) else {
            notice = "Python 실행 환경이 없습니다. 저장소 .venv 또는 번들 런타임이 필요합니다."
            return
        }
        notice = nil
        let logURL = paths.logs.appendingPathComponent("\(app.id).log")
        let python: URL
        do {
            preparing = app.hasRequirements ? "\(app.manifest.name) 의존성 준비 중…" : nil
            python = try await PythonEnvironment.prepare(app: app, runtime: runtime, venvsDir: paths.venvs, run: PythonEnvironment.runProcess(logURL: logURL))
            preparing = nil
        } catch {
            preparing = nil
            notice = "의존성 설치 실패: \(error.localizedDescription)"
            return
        }
        await runner.start(app, command: app.command(python: python, host: config.host, token: config.token), logURL: logURL)
        if case .failed(_, let reason) = runner.state, !config.token.isEmpty, reason.contains("--token") {
            // The app has no --token flag: retry without it (spec §3).
            await runner.start(app, command: app.command(python: python, host: config.host, token: config.token, includeToken: false), logURL: logURL)
        }
        if runner.state.activeAppID == app.id {
            config.lastAppID = app.id
            saveConfig()
        } else if case .failed(_, let reason) = runner.state {
            notice = "\(app.manifest.name) 중단됨: \(reason)"
        }
    }

    func stopCurrent() async { await runner.stop() }

    func resumeLastAppIfWanted() async {
        guard config.resumeLastApp, let id = config.lastAppID, let app = apps.first(where: { $0.id == id }) else { return }
        await toggle(app)
    }

    // MARK: config & monitoring

    func saveConfig() {
        do { try store.save(config) } catch { notice = "설정 저장 실패: \(error.localizedDescription)" }
    }

    func startMonitoring() {
        bar.start { [weak self] in
            guard let self else { return ("10.0.4.20", "") }
            return (self.config.host, self.config.token)
        }
    }
}

/// The AppDelegate has no access to the SwiftUI StateObject; the model registers itself here.
enum LauncherModelRegistry {
    @MainActor static weak var model: LauncherModel?
}
