import XCTest
@testable import BUSYLauncher

final class PythonEnvironmentTests: XCTestCase {
    var tmp: URL!
    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory.appendingPathComponent("pe-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp.appendingPathComponent("app"), withIntermediateDirectories: true)
    }
    override func tearDown() { try? FileManager.default.removeItem(at: tmp) }

    private func app(requirements: String?) throws -> AppDescriptor {
        let dir = tmp.appendingPathComponent("app")
        if let r = requirements { try r.write(to: dir.appendingPathComponent("requirements.txt"), atomically: true, encoding: .utf8) }
        return AppDescriptor(id: "app", directory: dir, kind: .gallery, manifest: AppManifest(name: "A", description: "", author: ""), iconURL: nil, hasRequirements: requirements != nil)
    }
    let runtime = PythonRuntime(python: URL(fileURLWithPath: "/py"), isBundled: false)

    final class Recorder: @unchecked Sendable {
        private let lock = NSLock(); private(set) var ran: [LaunchCommand] = []
        func add(_ c: LaunchCommand) { lock.lock(); ran.append(c); lock.unlock() }
    }

    func testNoRequirementsUsesRuntimePython() async throws {
        let rec = Recorder()
        let py = try await PythonEnvironment.prepare(app: app(requirements: nil), runtime: runtime, venvsDir: tmp.appendingPathComponent("venvs"), run: { rec.add($0); return 0 })
        XCTAssertEqual(py.path, "/py"); XCTAssertTrue(rec.ran.isEmpty)
    }

    func testCreatesVenvInstallsAndStamps() async throws {
        let rec = Recorder()
        let venvs = tmp.appendingPathComponent("venvs")
        let venvPy = venvs.appendingPathComponent("app/bin/python")
        let run: PythonEnvironment.Run = { cmd in
            rec.add(cmd)
            if cmd.arguments.first == "-m", cmd.arguments[1] == "venv" {   // simulate venv creation
                try FileManager.default.createDirectory(at: venvPy.deletingLastPathComponent(), withIntermediateDirectories: true)
                FileManager.default.createFile(atPath: venvPy.path, contents: Data())
            }
            return 0
        }
        let py = try await PythonEnvironment.prepare(app: app(requirements: "requests\n"), runtime: runtime, venvsDir: venvs, run: run)
        XCTAssertEqual(py.path, venvPy.path)
        XCTAssertEqual(rec.ran.count, 2)
        XCTAssertEqual(rec.ran[0].executable.path, "/py")
        XCTAssertEqual(Array(rec.ran[0].arguments.prefix(3)), ["-m", "venv", "--system-site-packages"])
        XCTAssertEqual(rec.ran[1].executable.path, venvPy.path)
        XCTAssertEqual(Array(rec.ran[1].arguments.prefix(4)), ["-m", "pip", "install", "-r"])
        // second call: nothing to do
        _ = try await PythonEnvironment.prepare(app: app(requirements: "requests\n"), runtime: runtime, venvsDir: venvs, run: run)
        XCTAssertEqual(rec.ran.count, 2)
        // changed requirements: pip again, no venv
        _ = try await PythonEnvironment.prepare(app: app(requirements: "requests\nyaml\n"), runtime: runtime, venvsDir: venvs, run: run)
        XCTAssertEqual(rec.ran.count, 3); XCTAssertEqual(rec.ran[2].arguments[1], "pip")
    }

    func testRebuildsVenvWhenInterpreterMoved() async throws {
        let rec = Recorder()
        let venvs = tmp.appendingPathComponent("venvs")
        let venv = venvs.appendingPathComponent("app")
        // An old venv made by an interpreter that no longer exists (e.g. the .app was moved).
        try FileManager.default.createDirectory(at: venv.appendingPathComponent("bin"), withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(at: venv.appendingPathComponent("bin/python"), withDestinationURL: URL(fileURLWithPath: "/old/app/python3"))
        try "home = /old/app\nversion = 3.12.1\n".write(to: venv.appendingPathComponent("pyvenv.cfg"), atomically: true, encoding: .utf8)
        try "oldsha".write(to: venv.appendingPathComponent(".requirements.sha"), atomically: true, encoding: .utf8)
        let venvPy = venv.appendingPathComponent("bin/python")
        let run: PythonEnvironment.Run = { cmd in
            rec.add(cmd)
            if cmd.arguments.first == "-m", cmd.arguments[1] == "venv" {
                try? FileManager.default.removeItem(at: venvPy)
                try FileManager.default.createDirectory(at: venvPy.deletingLastPathComponent(), withIntermediateDirectories: true)
                FileManager.default.createFile(atPath: venvPy.path, contents: Data())
                try "home = /py-dir\n".write(to: venv.appendingPathComponent("pyvenv.cfg"), atomically: true, encoding: .utf8)
            }
            return 0
        }
        let runtime = PythonRuntime(python: URL(fileURLWithPath: "/py-dir/python3"), isBundled: true)
        _ = try await PythonEnvironment.prepare(app: app(requirements: "requests\n"), runtime: runtime, venvsDir: venvs, run: run)
        XCTAssertEqual(rec.ran.map { $0.arguments[1] }, ["venv", "pip"], "stale venv must be recreated, then requirements reinstalled")
        XCTAssertFalse(FileManager.default.fileExists(atPath: venv.appendingPathComponent(".requirements.sha").path) == false)
    }

    func testFailureThrows() async throws {
        do {
            _ = try await PythonEnvironment.prepare(app: app(requirements: "x"), runtime: runtime, venvsDir: tmp.appendingPathComponent("v"), run: { _ in 1 })
            XCTFail("should throw")
        } catch PythonEnvironmentError.commandFailed(let step, let code) {
            XCTAssertEqual(step, "venv"); XCTAssertEqual(code, 1)
        }
    }
}

final class RunProcessTests: XCTestCase {
    /// Real /bin/sh: the run helper must return the exit status and must not hang.
    func testRunProcessReturnsExitCode() async throws {
        let log = FileManager.default.temporaryDirectory.appendingPathComponent("rp-\(UUID().uuidString).log")
        let run = PythonEnvironment.runProcess(logURL: log)
        let cmd = LaunchCommand(executable: URL(fileURLWithPath: "/bin/sh"), arguments: ["-c", "echo hello; exit 3"],
                                workingDirectory: URL(fileURLWithPath: "/"), environment: [:])
        let result = Result()
        let task = Task { let c = try await run(cmd); result.set(c) }
        _ = task
        let deadline = Date().addingTimeInterval(5)
        while result.code == nil, Date() < deadline { try await Task.sleep(nanoseconds: 50_000_000) }
        XCTAssertEqual(result.code, 3, "runProcess did not finish within 5 s")
        XCTAssertTrue((try? String(contentsOf: log, encoding: .utf8))?.contains("hello") ?? false)
    }

    final class Result: @unchecked Sendable {
        private let lock = NSLock(); private var value: Int32?
        func set(_ c: Int32) { lock.lock(); value = c; lock.unlock() }
        var code: Int32? { lock.lock(); defer { lock.unlock() }; return value }
    }
}
