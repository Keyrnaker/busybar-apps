import Foundation

final class GalleryClient {
    typealias Fetch = (URL) async throws -> Data
    private let fetch: Fetch
    private let cacheURL: URL
    private let now: () -> Date
    private let cacheTTL: TimeInterval = 3600

    init(fetch: @escaping Fetch = GalleryAPI.defaultFetch, cacheURL: URL, now: @escaping () -> Date = Date.init) {
        self.fetch = fetch; self.cacheURL = cacheURL; self.now = now
    }

    func list() async throws -> [GalleryEntry] {
        if let data = try? Data(contentsOf: cacheURL),
           let cache = try? JSONDecoder().decode(GalleryCache.self, from: data),
           now().timeIntervalSince(cache.fetchedAt) < cacheTTL {
            return cache.entries.map { GalleryEntry(slug: $0.slug, manifest: AppManifest(name: $0.name, description: $0.description, author: $0.author)) }
        }
        let dirs = try GalleryAPI.parseEntries(try await fetch(GalleryAPI.appsListURL)).filter { $0.type == "dir" }
        var entries: [GalleryEntry] = []
        for d in dirs {
            let text = (try? String(decoding: await fetch(GalleryAPI.manifestURL(slug: d.name)), as: UTF8.self)) ?? ""
            entries.append(GalleryEntry(slug: d.name, manifest: ManifestParser.parse(text, fallbackName: d.name)))
        }
        entries.sort { $0.manifest.name.localizedCaseInsensitiveCompare($1.manifest.name) == .orderedAscending }
        let cache = GalleryCache(fetchedAt: now(), entries: entries.map { .init(slug: $0.slug, name: $0.manifest.name, description: $0.manifest.description, author: $0.manifest.author) })
        try? FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? JSONEncoder().encode(cache).write(to: cacheURL, options: .atomic)
        return entries
    }

    func install(slug: String, into appsDir: URL) async throws -> URL {
        guard slug.range(of: #"^[A-Za-z0-9_\-]+$"#, options: .regularExpression) != nil else { throw GalleryError.badSlug }
        let staging = appsDir.appendingPathComponent(".staging-\(slug)")
        try? FileManager.default.removeItem(at: staging)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        try await download(path: "apps/\(slug)", into: staging)
        let final = appsDir.appendingPathComponent(slug)
        try? FileManager.default.removeItem(at: final)
        try FileManager.default.moveItem(at: staging, to: final)
        return final
    }

    private func download(path: String, into dir: URL) async throws {
        let entries = try GalleryAPI.parseEntries(try await fetch(GalleryAPI.contentsURL(path: path)))
        for e in entries {
            let target = dir.appendingPathComponent(e.name)
            if e.type == "dir" {
                try FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
                try await download(path: e.path, into: target)
            } else if e.type == "file" {
                guard let raw = e.download_url, let url = URL(string: raw) else { throw GalleryError.missingDownloadURL(e.path) }
                try (try await fetch(url)).write(to: target, options: .atomic)
            }
        }
    }
}
