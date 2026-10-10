import SwiftUI

struct GalleryView: View {
    @EnvironmentObject var model: LauncherModel
    @State private var entries: [GalleryEntry] = []
    @State private var status: [String: String] = [:]
    @State private var loading = false
    @State private var error: String?

    private var client: GalleryClient { GalleryClient(cacheURL: model.paths.galleryCache) }
    private var installed: Set<String> { Set(model.apps.map(\.id)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("커뮤니티 갤러리 (maxswinkels/busybar-apps)").font(.headline)
                Spacer()
                Button("새로고침") { Task { await load() } }.disabled(loading)
            }
            if let error { Text(error).foregroundStyle(.red) }
            Table(entries) {
                TableColumn("이름") { e in Text(e.manifest.name) }
                TableColumn("작성자") { e in Text(e.manifest.author) }.width(120)
                TableColumn("설명") { e in Text(e.manifest.description).lineLimit(2) }
                TableColumn("") { e in
                    HStack {
                        if let s = status[e.slug] { Text(s).font(.caption) }
                        if installed.contains(e.slug) {
                            Text("설치됨").foregroundStyle(.secondary)
                            Button("삭제") { Task { await remove(e.slug) } }
                        } else {
                            Button("설치") { Task { await install(e.slug) } }
                        }
                    }
                }.width(220)
            }
        }
        .padding(16)
        .task { await load() }
    }

    private func load() async {
        loading = true; defer { loading = false }
        do { entries = try await client.list(); error = nil } catch { self.error = error.localizedDescription }
    }

    private func install(_ slug: String) async {
        status[slug] = "내려받는 중…"
        do {
            _ = try await client.install(slug: slug, into: model.paths.apps)
            status[slug] = "완료"
            model.refreshApps()
        } catch { status[slug] = "실패: \(error.localizedDescription)" }
    }

    private func remove(_ slug: String) async {
        if model.runner.state.activeAppID == slug { await model.stopCurrent() }
        try? FileManager.default.removeItem(at: model.paths.apps.appendingPathComponent(slug))
        try? FileManager.default.removeItem(at: model.paths.venvs.appendingPathComponent(slug))
        try? FileManager.default.removeItem(at: model.paths.logs.appendingPathComponent("\(slug).log"))
        status[slug] = nil
        model.refreshApps()
    }
}
