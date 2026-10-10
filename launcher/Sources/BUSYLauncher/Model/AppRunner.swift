import Foundation

enum RunState: Equatable {
    case stopped
    case starting(appID: String)
    case running(appID: String)
    case exited(appID: String, code: Int32)
    case failed(appID: String, reason: String)

    var activeAppID: String? {
        switch self {
        case .starting(let id), .running(let id): return id
        default: return nil
        }
    }
}

@MainActor
final class AppRunner: ObservableObject {
    @Published private(set) var state: RunState = .stopped
    @Published private(set) var recentLog: [String] = []

    private let factory: ChildProcessFactory
    private let sleep: (TimeInterval) async -> Void
    private let now: () -> Date
    private let failWindow: TimeInterval
    private let killGrace: TimeInterval
    private let pidStore: PidStore?

    private var process: ChildProcess?
    private var startedAt: Date?
    private var generation = 0
    private var stopping = false
    private var queue: Task<Void, Never>?   // start/stop run strictly one after another

    init(factory: ChildProcessFactory,
         sleep: @escaping (TimeInterval) async -> Void = { s in try? await Task.sleep(nanoseconds: UInt64(s * 1_000_000_000)) },
         now: @escaping () -> Date = Date.init,
         failWindow: TimeInterval = 2, killGrace: TimeInterval = 3, pidStore: PidStore? = nil) {
        self.factory = factory; self.sleep = sleep; self.now = now
        self.failWindow = failWindow; self.killGrace = killGrace; self.pidStore = pidStore
    }

    var isBusy: Bool { state.activeAppID != nil }

    func start(_ app: AppDescriptor, command: LaunchCommand, logURL: URL) async {
        await serialized { await self.startNow(app, command: command, logURL: logURL) }
    }

    func stop() async {
        await serialized { await self.stopNow() }
    }

    /// Chains the operation behind whatever is already queued, so two quick menu clicks can never
    /// interleave a stop and two starts (which would leave an untracked child running).
    private func serialized(_ op: @escaping @MainActor () async -> Void) async {
        let previous = queue
        let task = Task { @MainActor in
            await previous?.value
            await op()
        }
        queue = task
        await task.value
    }

    private func startNow(_ app: AppDescriptor, command: LaunchCommand, logURL: URL) async {
        await stopNow()
        generation += 1
        let gen = generation
        let proc = factory.makeProcess(command: command, logURL: logURL)
        proc.onOutputLine = { [weak self] line in
            Task { @MainActor in self?.appendLog(line) }
        }
        proc.onTermination = { [weak self] code in
            Task { @MainActor in self?.handleTermination(code: code, appID: app.id, generation: gen) }
        }
        recentLog = []
        startedAt = now()
        process = proc
        state = .starting(appID: app.id)
        do {
            try proc.launch()
        } catch {
            process = nil
            state = .failed(appID: app.id, reason: error.localizedDescription)
            return
        }
        if let pid = proc.pid { try? pidStore?.record(pid: pid, executable: command.executable.path) }
        await sleep(failWindow)
        if generation == gen, case .starting(let id) = state, id == app.id, proc.isRunning {
            state = .running(appID: app.id)
        }
    }

    private func stopNow() async {
        guard let proc = process else {
            if state.activeAppID != nil { state = .stopped }
            return
        }
        stopping = true
        defer { stopping = false }
        if proc.isRunning {
            proc.interrupt()
            var waited: TimeInterval = 0
            while proc.isRunning, waited < killGrace {
                await sleep(0.1); waited += 0.1
            }
            if proc.isRunning {
                proc.kill()
                while proc.isRunning { await sleep(0.1) }
            }
        }
        process = nil
        pidStore?.clear()
        state = .stopped
    }

    private func appendLog(_ line: String) {
        recentLog.append(line)
        if recentLog.count > 200 { recentLog.removeFirst(recentLog.count - 200) }
    }

    private func handleTermination(code: Int32, appID: String, generation gen: Int) {
        guard gen == generation else { return }          // an older process; ignore
        if stopping || state.activeAppID == nil { return } // stop() reports .stopped itself
        let elapsed = now().timeIntervalSince(startedAt ?? now())
        process = nil
        pidStore?.clear()
        if elapsed < failWindow || code != 0 {
            let last = recentLog.last(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty }) ?? ""
            state = .failed(appID: appID, reason: "exit \(code): \(last)")
        } else {
            state = .exited(appID: appID, code: code)
        }
    }
}
