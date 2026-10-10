import XCTest
@testable import BUSYLauncher

final class OrphanReaperTests: XCTestCase {
    var file: URL!
    override func setUp() { file = FileManager.default.temporaryDirectory.appendingPathComponent("pid-\(UUID().uuidString)") }
    override func tearDown() { try? FileManager.default.removeItem(at: file) }

    func testRecordAndClear() throws {
        let store = PidStore(fileURL: file)
        try store.record(pid: 4242, executable: "/py", launcherPid: 100)
        XCTAssertEqual(store.read(), PidStore.Record(pid: 4242, executable: "/py", launcherPid: 100))
        store.clear()
        XCTAssertNil(store.read())
    }

    func testReapOnlyWhenRecordingLauncherIsDead() throws {
        let store = PidStore(fileURL: file)
        var signalled: [Int32] = []
        // The launcher that recorded it is still alive (another instance): leave both alone, keep the record.
        try store.record(pid: 4242, executable: "/py", launcherPid: 100)
        XCTAssertFalse(OrphanReaper.reap(store: store, isAlive: { $0 == 100 }, commandOf: { _ in "/py app.py --host h" }, signal: { signalled.append($0) }))
        XCTAssertEqual(signalled, []); XCTAssertNotNil(store.read())
        // Launcher dead, child alive with the recorded executable: reaped.
        XCTAssertTrue(OrphanReaper.reap(store: store, isAlive: { _ in false }, commandOf: { _ in "/py app.py --host h" }, signal: { signalled.append($0) }))
        XCTAssertEqual(signalled, [4242]); XCTAssertNil(store.read())
        // Pid reused by something else (even with --host in it): not signalled, file cleared.
        try store.record(pid: 99, executable: "/py", launcherPid: 100)
        XCTAssertFalse(OrphanReaper.reap(store: store, isAlive: { _ in false }, commandOf: { _ in "/usr/bin/other --host x" }, signal: { signalled.append($0) }))
        XCTAssertEqual(signalled, [4242]); XCTAssertNil(store.read())
        // Process gone: nothing to do.
        try store.record(pid: 7, executable: "/py", launcherPid: 100)
        XCTAssertFalse(OrphanReaper.reap(store: store, isAlive: { _ in false }, commandOf: { _ in nil }, signal: { signalled.append($0) }))
        XCTAssertNil(store.read())
    }

    func testIsRunningUnderXCTest() {
        XCTAssertTrue(TestHostGuard.isRunningTests(environment: ["XCTestConfigurationFilePath": "/x"]))
        XCTAssertTrue(TestHostGuard.isRunningTests(environment: ["XCTestBundlePath": "/x"]))
        XCTAssertFalse(TestHostGuard.isRunningTests(environment: [:]))
    }
}
