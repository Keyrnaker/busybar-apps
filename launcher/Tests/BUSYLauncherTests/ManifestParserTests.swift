import XCTest
@testable import BUSYLauncher

final class ManifestParserTests: XCTestCase {
    func testParsesFlatKeys() {
        let text = """
        name: Clock
        author: maxswinkels
        description: Clock widget - big time, refreshed every second.
        tags:
          - clock
          - time
        preview: ./preview.png
        """
        let m = ManifestParser.parse(text, fallbackName: "clock")
        XCTAssertEqual(m, AppManifest(name: "Clock", description: "Clock widget - big time, refreshed every second.", author: "maxswinkels"))
    }

    func testQuotedAndCommentedValues() {
        let text = """
        name: "Audio Visualizer"   # shown in menu
        description: 'Live: mic spectrum'
        author: someone # handle
        """
        let m = ManifestParser.parse(text, fallbackName: "x")
        XCTAssertEqual(m.name, "Audio Visualizer")
        XCTAssertEqual(m.description, "Live: mic spectrum")
        XCTAssertEqual(m.author, "someone")
    }

    func testMissingKeysFallBack() {
        let m = ManifestParser.parse("tags:\n  - a\n", fallbackName: "my-app")
        XCTAssertEqual(m, AppManifest(name: "my-app", description: "", author: ""))
        XCTAssertEqual(ManifestParser.parse("", fallbackName: "z").name, "z")
    }

    func testListItemsAreNotKeys() {
        let text = "tags:\n  - name: not-a-name\nname: Real\n"
        XCTAssertEqual(ManifestParser.parse(text, fallbackName: "f").name, "Real")
    }
}
