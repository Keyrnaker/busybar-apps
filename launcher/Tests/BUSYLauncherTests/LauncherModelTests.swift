import XCTest
import Combine
@testable import BUSYLauncher

@MainActor
final class LauncherModelTests: XCTestCase {
    func testInferRepoWalksUpToPytestIni() {
        let bundle = URL(fileURLWithPath: "/w/busybar/launcher/build/DerivedData/Build/Products/Debug/BUSY Launcher.app")
        let repo = LauncherModel.inferRepo(from: bundle) { url in
            url.path == "/w/busybar/pytest.ini" || url.path == "/w/busybar/apps"
        }
        XCTAssertEqual(repo?.path, "/w/busybar")
        XCTAssertNil(LauncherModel.inferRepo(from: bundle) { _ in false })
    }

    func testAppDirectoriesOrder() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("lm-\(UUID().uuidString)")
        let paths = Paths(root: root)
        let model = LauncherModel(paths: paths, factory: NullFactory(), bundleResources: nil, bundleURL: URL(fileURLWithPath: "/nowhere/x.app"))
        model.config.devRepoPath = "/repo"
        model.config.extraAppsDirs = ["/extra"]
        XCTAssertEqual(model.appDirectories.map(\.path), [paths.apps.path, "/repo/apps", "/extra"])
    }

    func testStatusSuffix() {
        let model = LauncherModel(paths: Paths(root: URL(fileURLWithPath: "/tmp/lm")), factory: NullFactory(), bundleResources: nil, bundleURL: URL(fileURLWithPath: "/nowhere/x.app"))
        let app = AppDescriptor(id: "a", directory: URL(fileURLWithPath: "/a"), kind: .gallery, manifest: AppManifest(name: "A", description: "", author: ""), iconURL: nil, hasRequirements: false)
        XCTAssertEqual(model.statusSuffix(for: app), "")
        XCTAssertFalse(model.isActive(app))
    }

    struct NullFactory: ChildProcessFactory {
        func makeProcess(command: LaunchCommand, logURL: URL) -> ChildProcess { fatalError("not used") }
    }

    /// A model whose dev repo has a fake executable python, so toggle() gets past runtime resolution.
    private func modelWithRuntime(factory: ChildProcessFactory) throws -> (LauncherModel, URL) {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("lm-\(UUID().uuidString)")
        let repo = root.appendingPathComponent("repo")
        let py = repo.appendingPathComponent(".venv/bin/python")
        try FileManager.default.createDirectory(at: py.deletingLastPathComponent(), withIntermediateDirectories: true)
        try "#!/bin/sh\n".write(to: py, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: py.path)
        let model = LauncherModel(paths: Paths(root: root.appendingPathComponent("support")), factory: factory, bundleResources: nil, bundleURL: URL(fileURLWithPath: "/nowhere/x.app"))
        model.config.devRepoPath = repo.path
        return (model, root)
    }

    func testModelPublishesWhenRunnerAndBarChange() async throws {
        let factory = AppRunnerTests.FakeFactory()
        factory.queue = [AppRunnerTests.FakeProcess(.stayAlive)]
        let (model, root) = try modelWithRuntime(factory: factory)
        defer { try? FileManager.default.removeItem(at: root) }
        var emissions = 0
        let sub = model.objectWillChange.sink { _ in emissions += 1 }
        defer { sub.cancel() }
        let app = AppDescriptor(id: "a", directory: root, kind: .gallery, manifest: AppManifest(name: "A", description: "", author: ""), iconURL: nil, hasRequirements: false)
        let before = emissions
        await model.toggle(app)
        for _ in 0..<20 { await Task.yield() }
        XCTAssertTrue(model.isActive(app))
        XCTAssertGreaterThan(emissions, before, "runner state changes must reach the model's observers")
        let beforeBar = emissions
        await model.bar.probeOnce(host: "127.0.0.1:1", token: "")
        XCTAssertGreaterThan(emissions, beforeBar, "bar status changes must reach the model's observers")
    }

    func testFailedStartSurfacesReasonInNotice() async throws {
        let factory = AppRunnerTests.FakeFactory()
        factory.queue = [AppRunnerTests.FakeProcess(.exitImmediately(code: 2, line: "app.py: error: no printers.toml"))]
        let (model, root) = try modelWithRuntime(factory: factory)
        defer { try? FileManager.default.removeItem(at: root) }
        let app = AppDescriptor(id: "a", directory: root, kind: .gallery, manifest: AppManifest(name: "A", description: "", author: ""), iconURL: nil, hasRequirements: false)
        await model.toggle(app)
        for _ in 0..<20 { await Task.yield() }
        XCTAssertEqual(model.statusSuffix(for: app), " (중단됨)")
        XCTAssertTrue(model.notice?.contains("no printers.toml") ?? false, model.notice ?? "nil")
        XCTAssertTrue(model.failureReason(for: app)?.contains("no printers.toml") ?? false)
    }

    func testDisconnectStopsAppAndMonitoringAndConnectRestores() async throws {
        let factory = AppRunnerTests.FakeFactory()
        factory.queue = [AppRunnerTests.FakeProcess(.exitOnInterrupt(afterPolls: 1)), AppRunnerTests.FakeProcess(.stayAlive)]
        let (model, root) = try modelWithRuntime(factory: factory)
        defer { try? FileManager.default.removeItem(at: root) }
        let app = AppDescriptor(id: "a", directory: root, kind: .gallery, manifest: AppManifest(name: "A", description: "", author: ""), iconURL: nil, hasRequirements: false)
        model.startMonitoring()
        XCTAssertTrue(model.bar.isMonitoring)
        await model.toggle(app)
        XCTAssertTrue(model.isActive(app))

        await model.disconnect()
        XCTAssertTrue(model.detached)
        XCTAssertFalse(model.isActive(app))
        XCTAssertFalse(model.bar.isMonitoring)
        XCTAssertEqual(model.statusLine, "BUSY Bar · 연결 끊음")
        // While detached, an app click reconnects first and then starts the app.
        await model.toggle(app)
        XCTAssertFalse(model.detached)
        XCTAssertTrue(model.bar.isMonitoring)
        XCTAssertTrue(model.isActive(app))

        await model.disconnect()
        model.connect()
        XCTAssertFalse(model.detached)
        XCTAssertTrue(model.bar.isMonitoring)
    }
}
