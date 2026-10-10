import XCTest
@testable import BUSYLauncher

/// Talks to the real GitHub API. Skipped unless TEST_RUNNER_GALLERY_LIVE=1 is passed to xcodebuild.
final class GalleryLiveTests: XCTestCase {
    func testListAndInstallClock() async throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["GALLERY_LIVE"] == "1", "set TEST_RUNNER_GALLERY_LIVE=1")
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("gallery-live-\(UUID().uuidString)")
        let client = GalleryClient(cacheURL: tmp.appendingPathComponent("cache.json"))
        let entries = try await client.list()
        XCTAssertGreaterThan(entries.count, 30)
        XCTAssertTrue(entries.contains { $0.slug == "clock" && $0.manifest.name == "Clock" })
        let dir = try await client.install(slug: "clock", into: tmp.appendingPathComponent("apps"))
        let app = try XCTUnwrap(AppRegistry.descriptor(for: dir))
        XCTAssertEqual(app.manifest.name, "Clock")
        XCTAssertTrue(FileManager.default.fileExists(atPath: dir.appendingPathComponent("app.py").path))
        print("GALLERY_LIVE_DIR=\(dir.path)")
    }
}
