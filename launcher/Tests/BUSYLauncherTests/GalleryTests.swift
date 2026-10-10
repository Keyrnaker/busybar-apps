import XCTest
@testable import BUSYLauncher

final class GalleryTests: XCTestCase {
    let listJSON = Data(#"""
    [{"name":"clock","type":"dir","path":"apps/clock","download_url":null},
     {"name":"README.md","type":"file","path":"apps/README.md","download_url":"https://raw/x/README.md"},
     {"name":"aquarium","type":"dir","path":"apps/aquarium","download_url":null}]
    """#.utf8)

    func testParseEntries() throws {
        let e = try GalleryAPI.parseEntries(listJSON)
        XCTAssertEqual(e.map(\.name), ["clock", "README.md", "aquarium"])
        XCTAssertEqual(GalleryAPI.appsListURL.absoluteString, "https://api.github.com/repos/maxswinkels/busybar-apps/contents/apps")
        XCTAssertEqual(GalleryAPI.manifestURL(slug: "clock").absoluteString, "https://raw.githubusercontent.com/maxswinkels/busybar-apps/main/apps/clock/manifest.yaml")
    }

    func testListReadsManifestsAndCaches() async throws {
        let cache = FileManager.default.temporaryDirectory.appendingPathComponent("gc-\(UUID().uuidString).json")
        let calls = Counter()
        let fetch: GalleryClient.Fetch = { url in
            calls.add(url.absoluteString)
            if url == GalleryAPI.appsListURL { return self.listJSON }
            if url == GalleryAPI.manifestURL(slug: "clock") { return Data("name: Clock\nauthor: max\n".utf8) }
            if url == GalleryAPI.manifestURL(slug: "aquarium") { return Data("name: Aquarium\n".utf8) }
            throw URLError(.badURL)
        }
        let clock = Clock()
        let client = GalleryClient(fetch: fetch, cacheURL: cache, now: { clock.now })
        let first = try await client.list()
        XCTAssertEqual(first.map(\.manifest.name), ["Aquarium", "Clock"])
        XCTAssertEqual(calls.count, 3)
        clock.now = clock.now.addingTimeInterval(600)
        let second = try await client.list()               // within 1h: served from cache
        XCTAssertEqual(second, first); XCTAssertEqual(calls.count, 3)
        clock.now = clock.now.addingTimeInterval(3600)
        _ = try await client.list()                          // cache expired
        XCTAssertEqual(calls.count, 6)
    }

    func testInstallDownloadsFolderRecursively() async throws {
        let appsDir = FileManager.default.temporaryDirectory.appendingPathComponent("gi-\(UUID().uuidString)")
        let fetch: GalleryClient.Fetch = { url in
            switch url.absoluteString {
            case GalleryAPI.contentsURL(path: "apps/clock").absoluteString:
                return Data(#"[{"name":"app.py","type":"file","path":"apps/clock/app.py","download_url":"https://raw/app.py"},{"name":"img","type":"dir","path":"apps/clock/img","download_url":null}]"#.utf8)
            case GalleryAPI.contentsURL(path: "apps/clock/img").absoluteString:
                return Data(#"[{"name":"a.png","type":"file","path":"apps/clock/img/a.png","download_url":"https://raw/a.png"}]"#.utf8)
            case "https://raw/app.py": return Data("print(1)".utf8)
            case "https://raw/a.png": return Data([1, 2, 3])
            default: throw URLError(.badURL)
            }
        }
        let client = GalleryClient(fetch: fetch, cacheURL: appsDir.appendingPathComponent("c.json"))
        let dir = try await client.install(slug: "clock", into: appsDir)
        XCTAssertEqual(dir.lastPathComponent, "clock")
        XCTAssertEqual(try String(contentsOf: dir.appendingPathComponent("app.py"), encoding: .utf8), "print(1)")
        XCTAssertEqual(try Data(contentsOf: dir.appendingPathComponent("img/a.png")), Data([1, 2, 3]))
        XCTAssertNotNil(AppRegistry.descriptor(for: dir))
    }

    func testInstallRejectsBadSlug() async {
        let client = GalleryClient(fetch: { _ in Data() }, cacheURL: URL(fileURLWithPath: "/tmp/x.json"))
        do { _ = try await client.install(slug: "../etc", into: URL(fileURLWithPath: "/tmp")); XCTFail() } catch {}
    }

    final class Counter: @unchecked Sendable {
        private let lock = NSLock(); private var items: [String] = []
        func add(_ s: String) { lock.lock(); items.append(s); lock.unlock() }
        var count: Int { lock.lock(); defer { lock.unlock() }; return items.count }
    }
    final class Clock: @unchecked Sendable { var now = Date(timeIntervalSince1970: 0) }
}
