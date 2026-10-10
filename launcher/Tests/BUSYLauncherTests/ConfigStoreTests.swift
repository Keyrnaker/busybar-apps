import XCTest
@testable import BUSYLauncher

final class ConfigStoreTests: XCTestCase {
    var file: URL!
    override func setUp() {
        file = FileManager.default.temporaryDirectory.appendingPathComponent("cfg-\(UUID().uuidString)/config.json")
    }
    override func tearDown() { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }

    func testDefaultsWhenMissing() {
        let cfg = ConfigStore(fileURL: file).load()
        XCTAssertEqual(cfg, LauncherConfig())
        XCTAssertEqual(cfg.host, "10.0.4.20")
        XCTAssertTrue(cfg.resumeLastApp)
    }

    func testRoundTripCreatesDirectory() throws {
        let store = ConfigStore(fileURL: file)
        var cfg = LauncherConfig()
        cfg.host = "192.168.1.9"; cfg.token = "1234"; cfg.lastAppID = "clock"; cfg.extraAppsDirs = ["/x"]
        try store.save(cfg)
        XCTAssertEqual(ConfigStore(fileURL: file).load(), cfg)
    }

    func testCorruptFileLoadsDefaultsAndBacksUp() throws {
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try "{not json".write(to: file, atomically: true, encoding: .utf8)
        let cfg = ConfigStore(fileURL: file).load()
        XCTAssertEqual(cfg, LauncherConfig())
        let backup = file.deletingPathExtension().appendingPathExtension("corrupt.json")
        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.path))
    }

    func testUnknownAndMissingKeysTolerated() throws {
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try #"{"host":"h","future":1}"#.write(to: file, atomically: true, encoding: .utf8)
        let cfg = ConfigStore(fileURL: file).load()
        XCTAssertEqual(cfg.host, "h")
        XCTAssertEqual(cfg.token, "")
        XCTAssertTrue(cfg.resumeLastApp)
    }

    func testPathsLayout() {
        let p = Paths(root: URL(fileURLWithPath: "/tmp/BL"))
        XCTAssertEqual(p.apps.path, "/tmp/BL/apps")
        XCTAssertEqual(p.venvs.path, "/tmp/BL/venvs")
        XCTAssertEqual(p.logs.path, "/tmp/BL/logs")
        XCTAssertEqual(p.config.path, "/tmp/BL/config.json")
        XCTAssertTrue(Paths.live.root.path.hasSuffix("/Library/Application Support/BUSY Launcher"))
    }
}
