import XCTest
@testable import BUSYLauncher

@MainActor
final class AppRunnerTests: XCTestCase {
    enum Behavior { case stayAlive, exitImmediately(code: Int32, line: String), exitOnInterrupt(afterPolls: Int) }

    final class FakeProcess: ChildProcess {
        var onTermination: ((Int32) -> Void)?
        var onOutputLine: ((String) -> Void)?
        let behavior: Behavior
        private(set) var launched = false, interrupted = false, killed = false
        private var running = false
        private var pollsLeft = 0
        init(_ behavior: Behavior) { self.behavior = behavior }
        var pid: Int32? { running ? 4242 : nil }
        var isRunning: Bool {
            if case .exitOnInterrupt = behavior, interrupted, running {
                pollsLeft -= 1
                if pollsLeft <= 0 { finish(code: 130) }
            }
            return running
        }
        func launch() throws {
            launched = true; running = true
            if case .exitImmediately(let code, let line) = behavior { onOutputLine?(line); finish(code: code) }
        }
        func interrupt() { interrupted = true; if case .exitOnInterrupt(let n) = behavior { pollsLeft = n } }
        func kill() { killed = true; finish(code: 9) }
        func simulateExit(code: Int32) { finish(code: code) }
        private func finish(code: Int32) { guard running else { return }; running = false; onTermination?(code) }
    }

    final class FakeFactory: ChildProcessFactory {
        var queue: [FakeProcess] = []
        var made: [FakeProcess] = []
        var launchOrder: [String] = []
        func makeProcess(command: LaunchCommand, logURL: URL) -> ChildProcess {
            let p = queue.removeFirst(); made.append(p)
            launchOrder.append(command.arguments.last ?? "?")
            return p
        }
    }

    var factory: FakeFactory!
    var runner: AppRunner!
    var clock = Date(timeIntervalSince1970: 1000)
    var sleeps: [TimeInterval] = []

    override func setUp() {
        factory = FakeFactory()
        sleeps = []
        runner = AppRunner(factory: factory, sleep: { [self] s in sleeps.append(s); clock = clock.addingTimeInterval(s) },
                           now: { [self] in clock }, failWindow: 2, killGrace: 3)
    }

    private func app(_ id: String) -> AppDescriptor {
        AppDescriptor(id: id, directory: URL(fileURLWithPath: "/apps/\(id)"), kind: .gallery,
                      manifest: AppManifest(name: id, description: "", author: ""), iconURL: nil, hasRequirements: false)
    }
    private func cmd(_ id: String) -> LaunchCommand {
        LaunchCommand(executable: URL(fileURLWithPath: "/py"), arguments: ["app.py", "--host", id], workingDirectory: URL(fileURLWithPath: "/"), environment: [:])
    }
    private func settle() async { for _ in 0..<20 { await Task.yield() } }

    func testStartPromotesToRunning() async {
        factory.queue = [FakeProcess(.stayAlive)]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        XCTAssertEqual(runner.state, .running(appID: "a"))
        XCTAssertEqual(sleeps, [2])
    }

    func testEarlyExitIsFailure() async {
        factory.queue = [FakeProcess(.exitImmediately(code: 2, line: "app.py: error: unrecognized arguments: --token"))]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        guard case .failed(let id, let reason) = runner.state else { return XCTFail("state \(runner.state)") }
        XCTAssertEqual(id, "a")
        XCTAssertTrue(reason.contains("unrecognized arguments: --token"), reason)
        XCTAssertEqual(runner.recentLog.last, "app.py: error: unrecognized arguments: --token")
    }

    func testCleanExitAfterRunningIsExited() async {
        let p = FakeProcess(.stayAlive); factory.queue = [p]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        clock = clock.addingTimeInterval(60)
        p.simulateExit(code: 0)
        await settle()
        XCTAssertEqual(runner.state, .exited(appID: "a", code: 0))
    }

    func testStopInterruptsThenKillsAfterGrace() async {
        let stubborn = FakeProcess(.stayAlive); factory.queue = [stubborn]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        await runner.stop()
        await settle()
        XCTAssertTrue(stubborn.interrupted && stubborn.killed)
        XCTAssertEqual(runner.state, .stopped)
        XCTAssertGreaterThanOrEqual(sleeps.dropFirst().reduce(0, +), 3)  // waited the grace period

        let polite = FakeProcess(.exitOnInterrupt(afterPolls: 2)); factory.queue = [polite]
        await runner.start(app("b"), command: cmd("b"), logURL: URL(fileURLWithPath: "/tmp/b.log"))
        await settle()
        await runner.stop()
        await settle()
        XCTAssertTrue(polite.interrupted); XCTAssertFalse(polite.killed)
        XCTAssertEqual(runner.state, .stopped)
    }

    func testSwitchWaitsForPreviousToStop() async {
        let a = FakeProcess(.exitOnInterrupt(afterPolls: 3)); let b = FakeProcess(.stayAlive)
        factory.queue = [a, b]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        await runner.start(app("b"), command: cmd("b"), logURL: URL(fileURLWithPath: "/tmp/b.log"))
        await settle()
        XCTAssertTrue(a.interrupted)
        XCTAssertFalse(a.isRunning, "A must be gone before B launches")
        XCTAssertTrue(b.launched)
        XCTAssertEqual(factory.launchOrder, ["a", "b"])
        XCTAssertEqual(runner.state, .running(appID: "b"))
    }

    func testStopWhenNothingRunningIsNoop() async {
        await runner.stop()
        XCTAssertEqual(runner.state, .stopped)
        XCTAssertEqual(sleeps, [])
    }

    func testConcurrentStartsRunOnlyTheLast() async {
        // Two starts issued while A is still shutting down. Which of B/C wins the queue is a
        // scheduling detail; the invariant is: exactly one child ends up running and tracked,
        // every other child was interrupted and is gone.
        let a = FakeProcess(.exitOnInterrupt(afterPolls: 3)), b = FakeProcess(.exitOnInterrupt(afterPolls: 2)), c = FakeProcess(.exitOnInterrupt(afterPolls: 2))
        factory.queue = [a, b, c]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        async let sb: Void = runner.start(app("b"), command: cmd("b"), logURL: URL(fileURLWithPath: "/tmp/b.log"))
        async let sc: Void = runner.start(app("c"), command: cmd("c"), logURL: URL(fileURLWithPath: "/tmp/c.log"))
        _ = await (sb, sc)
        await settle()
        XCTAssertEqual(factory.launchOrder.first, "a")
        XCTAssertEqual(Set(factory.launchOrder), ["a", "b", "c"])
        XCTAssertTrue(a.interrupted && !a.isRunning)
        guard case .running(let winner) = runner.state else { return XCTFail("state \(runner.state)") }
        XCTAssertEqual(winner, factory.launchOrder.last)
        let loser = winner == "b" ? c : b
        let winnerProc = winner == "b" ? b : c
        XCTAssertTrue(loser.interrupted, "the app that lost the race must have been stopped")
        XCTAssertFalse(loser.isRunning)
        XCTAssertTrue(winnerProc.isRunning)
    }
}
