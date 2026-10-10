import Foundation
import CryptoKit

enum PythonEnvironmentError: LocalizedError {
    case commandFailed(step: String, code: Int32)
    var errorDescription: String? { if case .commandFailed(let s, let c) = self { return "\(s) 실패 (exit \(c))" }; return nil }
}

enum PythonEnvironment {
    typealias Run = (LaunchCommand) async throws -> Int32

    static func prepare(app: AppDescriptor, runtime: PythonRuntime, venvsDir: URL, run: Run, fileManager: FileManager = .default) async throws -> URL {
        let reqFile = app.directory.appendingPathComponent("requirements.txt")
        guard app.hasRequirements, let reqData = try? Data(contentsOf: reqFile) else { return runtime.python }
        let venv = venvsDir.appendingPathComponent(app.id)
        let python = venv.appendingPathComponent("bin/python")
        let stamp = venv.appendingPathComponent(".requirements.sha")
        let sha = SHA256.hash(data: reqData).map { String(format: "%02x", $0) }.joined()

        if isStale(venv: venv, python: python, runtime: runtime, fileManager: fileManager) {
            try? fileManager.removeItem(at: venv)   // interpreter moved or vanished: rebuild from scratch
        }
        if !fileManager.fileExists(atPath: python.path) {
            try fileManager.createDirectory(at: venvsDir, withIntermediateDirectories: true)
            let code = try await run(LaunchCommand(executable: runtime.python, arguments: ["-m", "venv", "--system-site-packages", venv.path], workingDirectory: venvsDir, environment: ProcessInfo.processInfo.environment))
            guard code == 0 else { throw PythonEnvironmentError.commandFailed(step: "venv", code: code) }
        }
        if (try? String(contentsOf: stamp, encoding: .utf8)) != sha {
            let code = try await run(LaunchCommand(executable: python, arguments: ["-m", "pip", "install", "-r", reqFile.path], workingDirectory: app.directory, environment: ProcessInfo.processInfo.environment))
            guard code == 0 else { throw PythonEnvironmentError.commandFailed(step: "pip install", code: code) }
            try sha.write(to: stamp, atomically: true, encoding: .utf8)
        }
        return python
    }

    /// A venv is stale when its `bin/python` link dangles or `pyvenv.cfg` names another interpreter
    /// directory than the runtime we would use now (the .app was moved, or the dev .venv changed).
    static func isStale(venv: URL, python: URL, runtime: PythonRuntime, fileManager: FileManager = .default) -> Bool {
        let bin = python.path
        let exists = fileManager.fileExists(atPath: bin)
        let linkExists = (try? fileManager.destinationOfSymbolicLink(atPath: bin)) != nil
        if linkExists && !exists { return true }
        guard exists, let cfg = try? String(contentsOf: venv.appendingPathComponent("pyvenv.cfg"), encoding: .utf8) else { return false }
        for line in cfg.split(separator: "\n") {
            let parts = line.split(separator: "=", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
            if parts.count == 2, parts[0] == "home" {
                let expected = runtime.python.deletingLastPathComponent().standardizedFileURL.path
                return URL(fileURLWithPath: parts[1]).standardizedFileURL.path != expected
            }
        }
        return false
    }

    /// Real runner: waits for the process, appends its output to `logURL`.
    static func runProcess(logURL: URL) -> Run {
        return { cmd in
            // `p` must outlive launch(): its termination handler only holds `self` weakly, so a
            // process that is not referenced elsewhere would be deallocated and never report back.
            let p = FoundationChildProcess(command: cmd, logURL: logURL)
            return try await withCheckedThrowingContinuation { cont in
                p.onTermination = { code in
                    cont.resume(returning: code)
                    p.onTermination = nil   // break the p -> closure -> p cycle
                }
                do { try p.launch() } catch {
                    p.onTermination = nil
                    cont.resume(throwing: error)
                }
            }
        }
    }
}
