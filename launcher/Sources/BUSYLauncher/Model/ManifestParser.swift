import Foundation

struct AppManifest: Equatable {
    var name: String
    var description: String
    var author: String
}

/// Reads the three flat keys the community manifest.yaml uses. Lists and nesting are ignored.
enum ManifestParser {
    static func parse(_ text: String, fallbackName: String) -> AppManifest {
        var values: [String: String] = [:]
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine)
            guard let first = line.first, first != " ", first != "\t", first != "-", first != "#" else { continue }
            guard let colon = line.firstIndex(of: ":") else { continue }
            let key = line[..<colon].trimmingCharacters(in: .whitespaces)
            var value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            value = stripComment(value)
            value = stripQuotes(value)
            values[key] = value
        }
        let name = values["name"].flatMap { $0.isEmpty ? nil : $0 } ?? fallbackName
        return AppManifest(name: name, description: values["description"] ?? "", author: values["author"] ?? "")
    }

    private static func stripComment(_ s: String) -> String {
        // A '#' starts a comment only when preceded by whitespace (or at the start), and not inside quotes.
        if s.hasPrefix("\"") || s.hasPrefix("'") { return s }
        if let r = s.range(of: " #") { return String(s[..<r.lowerBound]).trimmingCharacters(in: .whitespaces) }
        if s.hasPrefix("#") { return "" }
        return s
    }

    private static func stripQuotes(_ s: String) -> String {
        for q in ["\"", "'"] {
            if s.hasPrefix(q), let end = s.dropFirst().firstIndex(of: Character(q)) {
                return String(s[s.index(after: s.startIndex)..<end])
            }
        }
        return s
    }
}
