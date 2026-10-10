import Foundation

/// Remembers the child the launcher is running so a later launcher can clean up after a crash/kill.
struct PidStore {
    struct Record: Equatable { let pid: Int32; let executable: String; let launcherPid: Int32 }
    let fileURL: URL

    func record(pid: Int32, executable: String, launcherPid: Int32 = ProcessInfo.processInfo.processIdentifier) throws {
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try "\(pid)\n\(executable)\n\(launcherPid)\n".write(to: fileURL, atomically: true, encoding: .utf8)
    }

    func read() -> Record? {
        guard let text = try? String(contentsOf: fileURL, encoding: .utf8) else { return nil }
        let lines = text.split(separator: "\n").map(String.init)
        guard lines.count >= 3, let pid = Int32(lines[0]), let launcher = Int32(lines[2]) else { return nil }
        return Record(pid: pid, executable: lines[1], launcherPid: launcher)
    }

    func clear() { try? FileManager.default.removeItem(at: fileURL) }
}

enum OrphanReaper {
    /// Sends SIGINT to the recorded child when the launcher that recorded it is gone and the child is
    /// still the same executable. A record whose launcher is still alive (another instance) is left alone.
    @discardableResult
    static func reap(store: PidStore,
                     isAlive: (Int32) -> Bool = { Darwin.kill($0, 0) == 0 },
                     commandOf: (Int32) -> String? = commandLine(of:),
                     signal: (Int32) -> Void = { Darwin.kill($0, SIGINT) }) -> Bool {
        guard let rec = store.read() else { return false }
        if isAlive(rec.launcherPid) { return false }
        defer { store.clear() }
        guard let cmd = commandOf(rec.pid), cmd.hasPrefix(rec.executable) else { return false }
        signal(rec.pid)
        return true
    }

    static func commandLine(of pid: Int32) -> String? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/ps")
        p.arguments = ["-p", String(pid), "-o", "command="]
        let pipe = Pipe(); p.standardOutput = pipe; p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        let line = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return line.isEmpty ? nil : line
    }
}

enum TestHostGuard {
    /// True when this process is the XCTest host: never start apps or monitors then.
    static func isRunningTests(environment: [String: String] = ProcessInfo.processInfo.environment) -> Bool {
        environment["XCTestConfigurationFilePath"] != nil || environment["XCTestBundlePath"] != nil
    }
}
