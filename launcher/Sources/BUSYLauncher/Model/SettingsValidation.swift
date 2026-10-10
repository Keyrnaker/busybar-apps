import Foundation

enum SettingsValidation {
    static func hostError(_ host: String) -> String? {
        let trimmed = host.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { return "기기 주소를 입력하세요 (예: 10.0.4.20)" }
        let ok = trimmed.range(of: #"^[A-Za-z0-9.\-]+(:[0-9]+)?$"#, options: .regularExpression) != nil
        return ok ? nil : "주소는 IP 또는 호스트명만 (http:// 없이)"
    }
}
