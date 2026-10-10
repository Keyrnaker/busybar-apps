import XCTest
@testable import BUSYLauncher

final class AppRegistryTests: XCTestCase {
    var tmp: URL!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory.appendingPathComponent("registry-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    }
    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: tmp) }

    private func write(_ rel: String, _ text: String = "") throws {
        let url = tmp.appendingPathComponent(rel)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try text.write(to: url, atomically: true, encoding: .utf8)
    }

    func testGalleryAppDetectedWithManifestAndIcon() throws {
        try write("gallery/clock/app.py", "print('hi')")
        try write("gallery/clock/manifest.yaml", "name: Clock\nauthor: max\n")
        try write("gallery/clock/icon.png", "png")
        try write("gallery/notes.txt", "x")
        try write("gallery/.hidden/app.py")
        let apps = AppRegistry.scan(directories: [tmp.appendingPathComponent("gallery")])
        XCTAssertEqual(apps.map(\.id), ["clock"])
        let clock = apps[0]
        XCTAssertEqual(clock.kind, .gallery)
        XCTAssertEqual(clock.manifest.name, "Clock")
        XCTAssertEqual(clock.iconURL?.lastPathComponent, "icon.png")
        XCTAssertFalse(clock.hasRequirements)
        let cmd = clock.command(python: URL(fileURLWithPath: "/py"), host: "10.0.4.20", token: "")
        XCTAssertEqual(cmd.executable.path, "/py")
        XCTAssertEqual(cmd.arguments, ["app.py", "--host", "10.0.4.20"])
        XCTAssertEqual(cmd.workingDirectory.standardizedFileURL, clock.directory.standardizedFileURL)
        XCTAssertEqual(cmd.environment["BUSYBAR_HOST"], "10.0.4.20")
        XCTAssertEqual(cmd.environment["BUSYBAR_TOKEN"], "")
    }

    func testPackageAppInRepo() throws {
        try write("repo/pytest.ini", "[pytest]")
        try write("repo/apps/__init__.py")
        try write("repo/apps/bambu_progress/__init__.py")
        try write("repo/apps/bambu_progress/app.py")
        try write("repo/apps/bambu_progress/requirements.txt", "aiomqtt")
        let apps = AppRegistry.scan(directories: [tmp.appendingPathComponent("repo/apps")])
        XCTAssertEqual(apps.map(\.id), ["bambu_progress"])
        let app = apps[0]
        XCTAssertEqual(app.kind, .package(repoRoot: tmp.appendingPathComponent("repo").standardizedFileURL))
        XCTAssertEqual(app.manifest.name, "bambu_progress")
        XCTAssertTrue(app.hasRequirements)
        let cmd = app.command(python: URL(fileURLWithPath: "/py"), host: "192.168.1.5", token: "1234")
        XCTAssertEqual(cmd.arguments, ["-m", "apps.bambu_progress.app", "--host", "192.168.1.5", "--token", "1234"])
        XCTAssertEqual(cmd.workingDirectory.standardizedFileURL, tmp.appendingPathComponent("repo").standardizedFileURL)
        XCTAssertEqual(cmd.environment["BUSYBAR_TOKEN"], "1234")
        let noToken = app.command(python: URL(fileURLWithPath: "/py"), host: "h", token: "1234", includeToken: false)
        XCTAssertEqual(noToken.arguments, ["-m", "apps.bambu_progress.app", "--host", "h"])
    }

    func testPackageRuleNeedsAppsParentAndPytestIni() throws {
        // __init__.py present, but not under a repo "apps/" dir with pytest.ini: it's a gallery app.
        try write("dl/foo/__init__.py")
        try write("dl/foo/app.py")
        let apps = AppRegistry.scan(directories: [tmp.appendingPathComponent("dl")])
        XCTAssertEqual(apps[0].kind, .gallery)
        XCTAssertEqual(apps[0].command(python: URL(fileURLWithPath: "/py"), host: "h", token: "").arguments, ["app.py", "--host", "h"])
    }

    func testDuplicateIdsFirstDirectoryWinsAndSortedByName() throws {
        try write("a/zeta/app.py"); try write("a/zeta/manifest.yaml", "name: Zeta\n")
        try write("a/alpha/app.py"); try write("a/alpha/manifest.yaml", "name: Alpha\n")
        try write("b/zeta/app.py"); try write("b/zeta/manifest.yaml", "name: Zeta From B\n")
        try write("a/tests/app.py"); try write("a/_skip/app.py")
        let apps = AppRegistry.scan(directories: [tmp.appendingPathComponent("a"), tmp.appendingPathComponent("b")])
        XCTAssertEqual(apps.map(\.manifest.name), ["Alpha", "Zeta"])
        XCTAssertEqual(AppRegistry.scan(directories: [tmp.appendingPathComponent("missing")]), [])
    }
}
