import XCTest
@testable import BUSYLauncher

final class BarProbeTests: XCTestCase {
    func testRequestShape() {
        let r = BarProbe.request(host: "10.0.4.20", token: "")
        XCTAssertEqual(r.url?.absoluteString, "http://10.0.4.20/api/version")
        XCTAssertEqual(r.timeoutInterval, 2)
        XCTAssertNil(r.value(forHTTPHeaderField: "X-API-Token"))
        let t = BarProbe.request(host: "192.168.1.2", token: "1234")
        XCTAssertEqual(t.value(forHTTPHeaderField: "X-API-Token"), "1234")
    }

    func testInterpret() {
        let ok = Data(#"{"api_semver":"27.5.0"}"#.utf8)
        XCTAssertEqual(BarProbe.interpret(host: "10.0.4.20", data: ok, statusCode: 200, error: nil), .connected(transport: "USB", apiVersion: "27.5.0"))
        XCTAssertEqual(BarProbe.interpret(host: "192.168.1.2", data: ok, statusCode: 200, error: nil), .connected(transport: "Wi-Fi", apiVersion: "27.5.0"))
        XCTAssertEqual(BarProbe.interpret(host: "h", data: Data("{}".utf8), statusCode: 200, error: nil), .connected(transport: "Wi-Fi", apiVersion: "?"))
        XCTAssertEqual(BarProbe.interpret(host: "h", data: nil, statusCode: 403, error: nil), .disconnected)
        XCTAssertEqual(BarProbe.interpret(host: "h", data: nil, statusCode: nil, error: URLError(.timedOut)), .disconnected)
    }
}
