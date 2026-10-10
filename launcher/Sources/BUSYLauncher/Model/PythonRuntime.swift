import Foundation

struct PythonRuntime: Equatable {
    let python: URL
    let isBundled: Bool

    static func resolve(bundleResources: URL?, devRepo: URL?,
                        exists: (URL) -> Bool = { FileManager.default.isExecutableFile(atPath: $0.path) }) -> PythonRuntime? {
        if let res = bundleResources {
            let bundled = res.appendingPathComponent("python/bin/python3")
            if exists(bundled) { return PythonRuntime(python: bundled, isBundled: true) }
        }
        if let repo = devRepo {
            let venv = repo.appendingPathComponent(".venv/bin/python")
            if exists(venv) { return PythonRuntime(python: venv, isBundled: false) }
        }
        return nil
    }
}
