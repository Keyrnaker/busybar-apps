import Foundation

struct GitHubEntry: Decodable, Equatable {
    let name: String
    let type: String
    let path: String
    let download_url: String?
}

enum GalleryError: LocalizedError {
    case rateLimited, badSlug, http(Int), missingDownloadURL(String)
    var errorDescription: String? {
        switch self {
        case .rateLimited: return "GitHub 요청 한도에 걸렸습니다. 잠시 후 다시 시도하세요."
        case .badSlug: return "잘못된 앱 이름"
        case .http(let c): return "HTTP \(c)"
        case .missingDownloadURL(let p): return "다운로드 주소 없음: \(p)"
        }
    }
}

enum GalleryAPI {
    static let owner = "maxswinkels"
    static let repo = "busybar-apps"
    static var appsListURL: URL { contentsURL(path: "apps") }
    static func contentsURL(path: String) -> URL { URL(string: "https://api.github.com/repos/\(owner)/\(repo)/contents/\(path)")! }
    static func manifestURL(slug: String) -> URL { URL(string: "https://raw.githubusercontent.com/\(owner)/\(repo)/main/apps/\(slug)/manifest.yaml")! }
    static func parseEntries(_ data: Data) throws -> [GitHubEntry] { try JSONDecoder().decode([GitHubEntry].self, from: data) }

    static func defaultFetch(_ url: URL) async throws -> Data {
        var req = URLRequest(url: url)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("BUSY-Launcher", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await URLSession.shared.data(for: req)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        if code == 403 || code == 429 { throw GalleryError.rateLimited }
        guard (200..<300).contains(code) else { throw GalleryError.http(code) }
        return data
    }
}

struct GalleryEntry: Identifiable, Equatable {
    var id: String { slug }
    let slug: String
    let manifest: AppManifest
}

struct GalleryCache: Codable {
    struct CacheEntry: Codable { let slug: String; let name: String; let description: String; let author: String }
    let fetchedAt: Date
    let entries: [CacheEntry]
}
