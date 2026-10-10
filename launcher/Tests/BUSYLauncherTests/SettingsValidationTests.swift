import XCTest
@testable import BUSYLauncher

final class SettingsValidationTests: XCTestCase {
    func testHost() {
        XCTAssertNil(SettingsValidation.hostError("10.0.4.20"))
        XCTAssertNil(SettingsValidation.hostError("busybar.local:8080"))
        XCTAssertNotNil(SettingsValidation.hostError(""))
        XCTAssertNotNil(SettingsValidation.hostError("http://x"))
        XCTAssertNotNil(SettingsValidation.hostError("a b"))
    }
}
