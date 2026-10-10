import XCTest
@testable import BUSYLauncher

final class PythonRuntimeTests: XCTestCase {
    let res = URL(fileURLWithPath: "/App.app/Contents/Resources")
    let repo = URL(fileURLWithPath: "/repo")

    func testBundledWins() {
        let rt = PythonRuntime.resolve(bundleResources: res, devRepo: repo) { _ in true }
        XCTAssertEqual(rt, PythonRuntime(python: URL(fileURLWithPath: "/App.app/Contents/Resources/python/bin/python3"), isBundled: true))
    }

    func testFallsBackToDevVenv() {
        let rt = PythonRuntime.resolve(bundleResources: res, devRepo: repo) { $0.path.contains(".venv") }
        XCTAssertEqual(rt, PythonRuntime(python: URL(fileURLWithPath: "/repo/.venv/bin/python"), isBundled: false))
    }

    func testNoneWhenNothingExists() {
        XCTAssertNil(PythonRuntime.resolve(bundleResources: res, devRepo: repo) { _ in false })
        XCTAssertNil(PythonRuntime.resolve(bundleResources: nil, devRepo: nil) { _ in true })
    }
}
