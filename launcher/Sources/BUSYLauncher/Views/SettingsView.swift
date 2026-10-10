import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var model: LauncherModel
    @State private var host = ""
    @State private var token = ""
    @State private var resume = true
    @State private var devRepo = ""
    @State private var extraDirs = ""

    var body: some View {
        Form {
            Section("BUSY Bar") {
                TextField("기기 주소", text: $host, prompt: Text("10.0.4.20"))
                if let err = SettingsValidation.hostError(host) { Text(err).foregroundStyle(.red).font(.caption) }
                SecureField("액세스 PIN (Wi-Fi 전용)", text: $token)
            }
            Section("앱") {
                Toggle("런처를 열 때 마지막 앱 다시 시작", isOn: $resume)
                TextField("개발 저장소 경로 (비우면 자동 추론)", text: $devRepo)
                TextField("추가 앱 폴더 (여러 개는 ; 로 구분)", text: $extraDirs)
            }
            HStack {
                Spacer()
                Button("저장") { save() }.disabled(SettingsValidation.hostError(host) != nil).keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 460)
        .onAppear(perform: load)
    }

    private func load() {
        host = model.config.host; token = model.config.token; resume = model.config.resumeLastApp
        devRepo = model.config.devRepoPath ?? ""; extraDirs = model.config.extraAppsDirs.joined(separator: "; ")
    }

    private func save() {
        model.config.host = host.trimmingCharacters(in: .whitespaces)
        model.config.token = token
        model.config.resumeLastApp = resume
        model.config.devRepoPath = devRepo.isEmpty ? nil : devRepo
        model.config.extraAppsDirs = extraDirs.split(separator: ";").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        model.saveConfig()
        model.refreshApps()
    }
}
