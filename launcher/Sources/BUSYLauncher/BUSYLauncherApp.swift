import SwiftUI
import AppKit

@main
struct BUSYLauncherApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = LauncherModel()

    var body: some Scene {
        MenuBarExtra {
            MenuContent()
                .environmentObject(model)
                .onAppear { model.refreshApps() }
        } label: {
            Image(model.runner.isBusy ? "MenuBarIconActive" : "MenuBarIcon")
        }
        .menuBarExtraStyle(.menu)

        Settings {
            SettingsView().environmentObject(model)
        }

        Window("갤러리", id: "gallery") {
            GalleryView().environmentObject(model)
        }
        .defaultSize(width: 640, height: 480)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        // Second instance guard (spec §10).
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: Bundle.main.bundleIdentifier ?? "")
            .filter { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }
        if !others.isEmpty {
            NSApp.activate(ignoringOtherApps: true)
            let alert = NSAlert(); alert.messageText = "BUSY Launcher가 이미 실행 중입니다."; alert.runModal()
            NSApp.terminate(nil)
            return
        }
        if TestHostGuard.isRunningTests() { return }   // the XCTest host must never start apps
        Task { @MainActor in
            guard let model = LauncherModelRegistry.model else { return }
            model.reapOrphans()
            model.startMonitoring()
            await model.resumeLastAppIfWanted()
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model = LauncherModelRegistry.model, model.runner.isBusy else { return .terminateNow }
        Task { @MainActor in
            await model.stopCurrent()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
