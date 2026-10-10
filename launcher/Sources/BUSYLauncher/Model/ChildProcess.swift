import Foundation

protocol ChildProcess: AnyObject {
    var onTermination: ((Int32) -> Void)? { get set }
    var onOutputLine: ((String) -> Void)? { get set }
    var isRunning: Bool { get }
    var pid: Int32? { get }
    func launch() throws
    func interrupt()
    func kill()
}

protocol ChildProcessFactory {
    func makeProcess(command: LaunchCommand, logURL: URL) -> ChildProcess
}

/// Real child process: stdout+stderr go to a log file and, line by line, to `onOutputLine`.
final class FoundationChildProcess: ChildProcess {
    var onTermination: ((Int32) -> Void)?
    var onOutputLine: ((String) -> Void)?

    private let process = Process()
    private let pipe = Pipe()
    private let logURL: URL
    private var logHandle: FileHandle?
    private var pending = Data()
    private let lock = NSLock()

    init(command: LaunchCommand, logURL: URL) {
        self.logURL = logURL
        process.executableURL = command.executable
        process.arguments = command.arguments
        process.currentDirectoryURL = command.workingDirectory
        process.environment = command.environment
        process.standardOutput = pipe
        process.standardError = pipe
    }

    var isRunning: Bool { process.isRunning }
    var pid: Int32? { process.isRunning ? process.processIdentifier : nil }

    func launch() throws {
        try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
        logHandle = try FileHandle(forWritingTo: logURL)
        logHandle?.seekToEndOfFile()
        let header = "\n=== \(ISO8601DateFormatter().string(from: Date())) \(process.executableURL?.path ?? "") \(process.arguments?.joined(separator: " ") ?? "")\n"
        logHandle?.write(Data(header.utf8))

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard let self, !data.isEmpty else { return }
            self.lock.lock(); defer { self.lock.unlock() }
            self.logHandle?.write(data)
            self.pending.append(data)
            while let nl = self.pending.firstIndex(of: 0x0A) {
                let line = String(decoding: self.pending[..<nl], as: UTF8.self)
                self.pending.removeSubrange(...nl)
                self.onOutputLine?(line)
            }
        }
        process.terminationHandler = { [weak self] p in
            guard let self else { return }
            self.pipe.fileHandleForReading.readabilityHandler = nil
            self.lock.lock()
            if !self.pending.isEmpty { self.onOutputLine?(String(decoding: self.pending, as: UTF8.self)); self.pending.removeAll() }
            try? self.logHandle?.close(); self.logHandle = nil
            self.lock.unlock()
            self.onTermination?(p.terminationStatus)
        }
        try process.run()
    }

    func interrupt() { if process.isRunning { process.interrupt() } }          // SIGINT
    func kill() { if process.isRunning { Darwin.kill(process.processIdentifier, SIGKILL) } }
}

struct FoundationProcessFactory: ChildProcessFactory {
    func makeProcess(command: LaunchCommand, logURL: URL) -> ChildProcess {
        FoundationChildProcess(command: command, logURL: logURL)
    }
}
