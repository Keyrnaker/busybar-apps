import SwiftUI
import AppKit

struct MenuContent: View {
    @EnvironmentObject var model: LauncherModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Text(model.statusLine)
        if let notice = model.notice { Text(notice) }
        if let preparing = model.preparing { Text(preparing) }
        Divider()
        if model.apps.isEmpty {
            Text("앱이 없습니다 · 갤러리에서 설치하거나 앱 폴더에 넣으세요")
        }
        ForEach(model.apps) { app in
            Toggle(isOn: Binding(get: { model.isActive(app) }, set: { _ in Task { await model.toggle(app) } })) {
                Label {
                    Text(app.manifest.name + model.statusSuffix(for: app))
                } icon: {
                    if let url = app.iconURL, let img = NSImage(contentsOf: url) {
                        Image(nsImage: resized(img))
                    } else {
                        Image(systemName: "app.dashed")
                    }
                }
            }
            if let reason = model.failureReason(for: app) {
                Text("   ↳ \(reason)")
            }
        }
        Divider()
        if model.detached {
            Button("BUSY Bar 연결") { model.connect() }
        } else {
            Button("BUSY Bar 연결 끊기") { Task { await model.disconnect() } }
        }
        Button("갤러리에서 설치…") { openWindow(id: "gallery"); NSApp.activate(ignoringOtherApps: true) }
        Button("앱 폴더 열기") { NSWorkspace.shared.open(model.paths.apps) }
        Button("로그 보기") { NSWorkspace.shared.open(model.paths.logs) }
        SettingsLink { Text("설정…") }
        Button("새로고침") { model.refreshApps() }
        Divider()
        Button("종료") { Task { await model.stopCurrent(); NSApplication.shared.terminate(nil) } }
            .keyboardShortcut("q")
    }

    private func resized(_ image: NSImage) -> NSImage {
        let target = NSSize(width: 16, height: 16)
        let out = NSImage(size: target)
        out.lockFocus()
        image.draw(in: NSRect(origin: .zero, size: target), from: .zero, operation: .sourceOver, fraction: 1)
        out.unlockFocus()
        return out
    }
}
