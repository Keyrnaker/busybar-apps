# BUSY Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A native macOS menu bar app (`BUSY Launcher.app`) that lists BUSY Bar apps (repo apps + community gallery apps), runs exactly one at a time as a Python child process pointed at the bar, and can be shipped as a single .app with Python bundled.

**Architecture:** SwiftUI `MenuBarExtra` app (LSUIElement) generated with XcodeGen from `launcher/project.yml`. Pure, testable model layer (manifest parser, app registry, config store, runtime resolver, process state machine with injected process factory, bar prober, gallery parser) plus thin views. Python apps are untouched; the launcher only builds the `python … --host H` command and supervises the process.

**Tech Stack:** Swift 6 compiler in Swift 5 language mode, SwiftUI, Foundation `Process`/`URLSession`, XCTest; XcodeGen 2.46, Xcode 27 driven by `DEVELOPER_DIR` (no sudo); python-build-standalone 3.12 (aarch64) for the bundled runtime; Pillow (already in `.venv`) to draw icons.

**Spec:** `docs/superpowers/specs/2026-09-24-busy-launcher-design.md`

## Global Constraints

- All launcher code under `busybar/launcher/`. Target/module name `BUSYLauncher`, product name `BUSY Launcher`, bundle id `io.github.keyrnaker.busylauncher`, minimum macOS 14.
- Build/test only via the scripts: `launcher/scripts/build.sh` and `launcher/scripts/test.sh`. Both export `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`. Never call `sudo xcode-select`.
- Swift language mode 5 (`SWIFT_VERSION = 5.0`), `SWIFT_STRICT_CONCURRENCY = minimal`. No third-party Swift packages.
- One app at a time. Stop = SIGINT, wait 3 s, SIGKILL. Start-then-exit within 2 s = failed.
- Default host `10.0.4.20`; `--token` only when the PIN is non-empty; env `BUSYBAR_HOST`/`BUSYBAR_TOKEN` always set.
- No login autostart. No sandbox. No automatic app restart.
- Commit after every task with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` as the last line. Never commit `launcher/BUSY Launcher.xcodeproj/` (generated), `launcher/build/`, `launcher/dist/`, or `launcher/Resources/python/`.

## Review Focus

1. **A gallery app folder that has `app.py` but is also a Python package** (`__init__.py`) under a non-repo directory must be treated as gallery-type, not package-type (Task 3, `testPackageRuleNeedsAppsParentAndPytestIni`).
2. **Starting app B while app A is still shutting down** must not launch B before A's process is gone (Task 6, `testSwitchWaitsForPreviousToStop`).
3. **A child that exits in under 2 s with status 2 (argparse error)** must be reported as failed with the last log line, never as a silent stop (Task 6, `testEarlyExitIsFailure`).
4. **A corrupt config.json** must load defaults, keep a backup, and not crash the menu (Task 4, `testCorruptFileLoadsDefaultsAndBacksUp`).
5. **Manifest values with quotes or a trailing `#` comment** must parse to clean strings (Task 2, `testQuotedAndCommentedValues`).

---

## File Structure

```
busybar/launcher/
├── project.yml
├── .gitignore
├── Sources/BUSYLauncher/
│   ├── BUSYLauncherApp.swift        # @main, MenuBarExtra, AppDelegate (quit hook), Window scenes
│   ├── Info.plist
│   ├── Assets.xcassets/             # AppIcon (empty ok), MenuBarIcon (template)
│   ├── Model/
│   │   ├── Paths.swift              # support dir, apps/venvs/logs
│   │   ├── ManifestParser.swift     # AppManifest, ManifestParser
│   │   ├── AppDescriptor.swift      # AppKind, AppDescriptor, LaunchCommand
│   │   ├── AppRegistry.swift        # scan(directories:)
│   │   ├── LauncherConfig.swift     # LauncherConfig, ConfigStore
│   │   ├── PythonRuntime.swift      # resolve()
│   │   ├── ChildProcess.swift       # protocols + FoundationChildProcess
│   │   ├── AppRunner.swift          # RunState + AppRunner (@MainActor)
│   │   ├── BarStatus.swift          # BarConnection, BarProbe, BarStatusMonitor
│   │   ├── Gallery.swift            # GitHubEntry, GalleryAPI, GalleryEntry
│   │   ├── GalleryInstaller.swift   # download folder, requirements venv
│   │   └── LauncherModel.swift      # ObservableObject tying config+registry+runner+status
│   └── Views/
│       ├── MenuContent.swift
│       ├── SettingsView.swift
│       └── GalleryView.swift
├── Tests/BUSYLauncherTests/
│   ├── ManifestParserTests.swift
│   ├── AppRegistryTests.swift
│   ├── ConfigStoreTests.swift
│   ├── PythonRuntimeTests.swift
│   ├── AppRunnerTests.swift
│   ├── BarProbeTests.swift
│   └── GalleryTests.swift
└── scripts/
    ├── bootstrap.sh    # brew install xcodegen; xcodegen generate
    ├── build.sh        # xcodebuild build (Debug)
    ├── test.sh         # xcodebuild test
    ├── make-icons.py   # draws MenuBarIcon PNGs and apps/bambu_progress/icon.png
    ├── bundle-python.sh
    └── package.sh
```

---

### Task 1: Project skeleton that builds, runs, and tests

**Files:**
- Create: `launcher/project.yml`, `launcher/.gitignore`, `launcher/Sources/BUSYLauncher/BUSYLauncherApp.swift`, `launcher/Sources/BUSYLauncher/Info.plist`, `launcher/Sources/BUSYLauncher/Assets.xcassets/{Contents.json,AppIcon.appiconset/Contents.json,MenuBarIcon.imageset/Contents.json}`, `launcher/Tests/BUSYLauncherTests/SmokeTests.swift`, `launcher/scripts/{bootstrap.sh,build.sh,test.sh,make-icons.py}`

**Interfaces:**
- Produces: a buildable app + test bundle; `scripts/test.sh` runs XCTest; module `BUSYLauncher` importable with `@testable import BUSYLauncher`.

- [ ] **Step 1: Install XcodeGen and write the project spec**

```bash
brew install xcodegen
mkdir -p ~/Workspace/busybar/launcher/{Sources/BUSYLauncher/Model,Sources/BUSYLauncher/Views,Tests/BUSYLauncherTests,scripts}
```

`launcher/project.yml`:
```yaml
name: BUSYLauncher
options:
  bundleIdPrefix: io.github.keyrnaker
  deploymentTarget:
    macOS: "14.0"
  createIntermediateGroups: true
  generateEmptyDirectories: true
settings:
  base:
    SWIFT_VERSION: "5.0"
    SWIFT_STRICT_CONCURRENCY: minimal
    MACOSX_DEPLOYMENT_TARGET: "14.0"
    CODE_SIGN_STYLE: Manual
    CODE_SIGN_IDENTITY: "-"
    DEVELOPMENT_TEAM: ""
    ENABLE_HARDENED_RUNTIME: "NO"
    ENABLE_APP_SANDBOX: "NO"
targets:
  BUSYLauncher:
    type: application
    platform: macOS
    sources:
      - path: Sources/BUSYLauncher
        excludes: ["Info.plist"]
    info:
      path: Sources/BUSYLauncher/Info.plist
      properties:
        CFBundleName: BUSY Launcher
        CFBundleDisplayName: BUSY Launcher
        LSUIElement: true
        LSMinimumSystemVersion: "14.0"
        NSHumanReadableCopyright: ""
    settings:
      base:
        PRODUCT_NAME: BUSY Launcher
        PRODUCT_BUNDLE_IDENTIFIER: io.github.keyrnaker.busylauncher
        PRODUCT_MODULE_NAME: BUSYLauncher
        ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon
        GENERATE_INFOPLIST_FILE: "NO"
  BUSYLauncherTests:
    type: bundle.unit-test
    platform: macOS
    sources: [Tests/BUSYLauncherTests]
    dependencies:
      - target: BUSYLauncher
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: io.github.keyrnaker.busylauncher.tests
        TEST_HOST: "$(BUILT_PRODUCTS_DIR)/BUSY Launcher.app/Contents/MacOS/BUSY Launcher"
        BUNDLE_LOADER: "$(TEST_HOST)"
schemes:
  BUSYLauncher:
    build:
      targets:
        BUSYLauncher: all
        BUSYLauncherTests: [test]
    run:
      config: Debug
    test:
      config: Debug
      targets: [BUSYLauncherTests]
```

`launcher/.gitignore`:
```
BUSYLauncher.xcodeproj/
build/
dist/
Resources/python/
*.xcuserstate
```

- [ ] **Step 2: App entry point, Info.plist, assets**

`launcher/Sources/BUSYLauncher/Info.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleExecutable</key><string>$(EXECUTABLE_NAME)</string>
  <key>CFBundleIdentifier</key><string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>BUSY Launcher</string>
  <key>CFBundleDisplayName</key><string>BUSY Launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
</dict>
</plist>
```

`launcher/Sources/BUSYLauncher/BUSYLauncherApp.swift` (skeleton; Task 8 replaces the menu body):
```swift
import SwiftUI

@main
struct BUSYLauncherApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        MenuBarExtra {
            Text("BUSY Launcher")
            Divider()
            Button("종료") { NSApplication.shared.terminate(nil) }
                .keyboardShortcut("q")
        } label: {
            Image("MenuBarIcon")
        }
        .menuBarExtraStyle(.menu)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }
}
```

Assets: `launcher/Sources/BUSYLauncher/Assets.xcassets/Contents.json`:
```json
{ "info": { "author": "xcode", "version": 1 } }
```
`Assets.xcassets/AppIcon.appiconset/Contents.json`:
```json
{ "images": [], "info": { "author": "xcode", "version": 1 } }
```
`Assets.xcassets/MenuBarIcon.imageset/Contents.json`:
```json
{
  "images": [
    { "filename": "menubar.png", "idiom": "universal", "scale": "1x" },
    { "filename": "menubar@2x.png", "idiom": "universal", "scale": "2x" }
  ],
  "info": { "author": "xcode", "version": 1 },
  "properties": { "template-rendering-intent": "template" }
}
```

`launcher/scripts/make-icons.py` (run with the repo `.venv`, which has Pillow):
```python
#!/usr/bin/env python3
"""Draw the menu bar template icon (18pt, 1x/2x) and apps/bambu_progress/icon.png."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
IMAGESET = ROOT / "Sources/BUSYLauncher/Assets.xcassets/MenuBarIcon.imageset"


def menubar(scale: int) -> Image.Image:
    # A rounded "bar" outline with three lit pixels: reads as the BUSY Bar at 18pt.
    s = 18 * scale
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = 1 * scale
    d.rounded_rectangle([pad, 5 * scale, s - pad - 1, 13 * scale - 1], radius=2 * scale, outline=(0, 0, 0, 255), width=max(1, scale))
    for x in (5, 8.5, 12):
        cx = int(x * scale)
        d.rectangle([cx - scale, 8 * scale, cx + scale - 1, 10 * scale - 1], fill=(0, 0, 0, 255))
    return im


def bambu_icon() -> Image.Image:
    # The same Bambu logo bitmap the app draws, on a dark rounded tile, 64x64.
    logo = ["###..###", "###..###", "###...##", "###....#", "##...#..", "#....##.", "..#..###", ".##..###"]
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, 63, 63], radius=14, fill=(24, 28, 36, 255))
    for y, row in enumerate(logo):
        for x, ch in enumerate(row):
            if ch == "#":
                d.rectangle([8 + x * 6, 8 + y * 6, 8 + x * 6 + 5, 8 + y * 6 + 5], fill=(0x63, 0xE6, 0xBE, 255))
    return im


if __name__ == "__main__":
    IMAGESET.mkdir(parents=True, exist_ok=True)
    menubar(1).save(IMAGESET / "menubar.png")
    menubar(2).save(IMAGESET / "menubar@2x.png")
    out = REPO / "apps/bambu_progress/icon.png"
    bambu_icon().save(out)
    print("wrote", IMAGESET, "and", out)
```

`launcher/Tests/BUSYLauncherTests/SmokeTests.swift`:
```swift
import XCTest
@testable import BUSYLauncher

final class SmokeTests: XCTestCase {
    func testModuleLinks() {
        XCTAssertEqual(1 + 1, 2)
    }
}
```

- [ ] **Step 3: Scripts**

`launcher/scripts/bootstrap.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v xcodegen >/dev/null || brew install xcodegen
"$(dirname "$0")/../../.venv/bin/python" scripts/make-icons.py
xcodegen generate
echo "generated BUSYLauncher.xcodeproj"
```
`launcher/scripts/build.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
CONFIG="${1:-Debug}"
xcodebuild -project BUSYLauncher.xcodeproj -scheme BUSYLauncher -configuration "$CONFIG" \
  -derivedDataPath build/DerivedData build 2>&1 | tail -3
APP="build/DerivedData/Build/Products/$CONFIG/BUSY Launcher.app"
echo "built: $APP"
```
`launcher/scripts/test.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcodebuild -project BUSYLauncher.xcodeproj -scheme BUSYLauncher -destination 'platform=macOS' \
  -derivedDataPath build/DerivedData test 2>&1 | grep -E "Test Case|error:|Executed|TEST (SUCCEEDED|FAILED)|\*\* " | tail -40
```
`chmod +x launcher/scripts/*.sh`

- [ ] **Step 4: Generate, build, test**

Run: `cd ~/Workspace/busybar/launcher && ./scripts/bootstrap.sh && ./scripts/build.sh && ./scripts/test.sh`
Expected: `generated BUSYLauncher.xcodeproj`, `built: build/DerivedData/Build/Products/Debug/BUSY Launcher.app`, then `Executed 1 test, with 0 failures` and `** TEST SUCCEEDED **`.

- [ ] **Step 5: Launch it once**

Run: `open "launcher/build/DerivedData/Build/Products/Debug/BUSY Launcher.app"; sleep 2; pgrep -fl "BUSY Launcher" | head -1; pkill -f "BUSY Launcher.app/Contents/MacOS"`
Expected: a process line is printed (the bar icon appears in the menu bar for 2 s), then it is killed.

- [ ] **Step 6: Commit**

```bash
cd ~/Workspace/busybar
git add launcher apps/bambu_progress/icon.png
git commit -m "feat(launcher): Xcode project skeleton, menu bar icon, test harness

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Manifest parser

**Files:**
- Create: `launcher/Sources/BUSYLauncher/Model/ManifestParser.swift`
- Test: `launcher/Tests/BUSYLauncherTests/ManifestParserTests.swift`

**Interfaces:**
- Produces: `struct AppManifest: Equatable { var name: String; var description: String; var author: String }` and `enum ManifestParser { static func parse(_ text: String, fallbackName: String) -> AppManifest }`.

- [ ] **Step 1: Failing tests**

```swift
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
```

- [ ] **Step 2: Run to see RED**

Run: `cd launcher && ./scripts/test.sh`
Expected: build error `cannot find 'ManifestParser' in scope` (reported as `error:` lines, `** TEST FAILED **`).

- [ ] **Step 3: Implement**

```swift
import Foundation

struct AppManifest: Equatable {
    var name: String
    var description: String
    var author: String
}

/// Reads the three flat keys the community manifest.yaml uses. Lists and nesting are ignored.
enum ManifestParser {
    static func parse(_ text: String, fallbackName: String) -> AppManifest {
        var values: [String: String] = [:]
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine)
            guard let first = line.first, first != " ", first != "\t", first != "-", first != "#" else { continue }
            guard let colon = line.firstIndex(of: ":") else { continue }
            let key = line[..<colon].trimmingCharacters(in: .whitespaces)
            var value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            value = stripComment(value)
            value = stripQuotes(value)
            values[key] = value
        }
        let name = values["name"].flatMap { $0.isEmpty ? nil : $0 } ?? fallbackName
        return AppManifest(name: name, description: values["description"] ?? "", author: values["author"] ?? "")
    }

    private static func stripComment(_ s: String) -> String {
        // A '#' starts a comment only when preceded by whitespace (or at the start), and not inside quotes.
        if s.hasPrefix("\"") || s.hasPrefix("'") { return s }
        if let r = s.range(of: " #") { return String(s[..<r.lowerBound]).trimmingCharacters(in: .whitespaces) }
        if s.hasPrefix("#") { return "" }
        return s
    }

    private static func stripQuotes(_ s: String) -> String {
        for q in ["\"", "'"] {
            if s.hasPrefix(q), let end = s.dropFirst().firstIndex(of: Character(q)) {
                return String(s[s.index(after: s.startIndex)..<end])
            }
        }
        return s
    }
}
```

- [ ] **Step 4: GREEN**

Run: `cd launcher && ./scripts/test.sh`
Expected: `Executed 5 tests, with 0 failures`, `** TEST SUCCEEDED **`.

- [ ] **Step 5: Commit**

```bash
git add launcher/Sources/BUSYLauncher/Model/ManifestParser.swift launcher/Tests/BUSYLauncherTests/ManifestParserTests.swift
git commit -m "feat(launcher): manifest parser

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: App descriptor, launch command, registry scan

**Files:**
- Create: `launcher/Sources/BUSYLauncher/Model/AppDescriptor.swift`, `launcher/Sources/BUSYLauncher/Model/AppRegistry.swift`
- Test: `launcher/Tests/BUSYLauncherTests/AppRegistryTests.swift`

**Interfaces:**
- Consumes: `AppManifest`, `ManifestParser` (Task 2)
- Produces:
  - `enum AppKind: Equatable { case gallery; case package(repoRoot: URL) }`
  - `struct LaunchCommand: Equatable { let executable: URL; let arguments: [String]; let workingDirectory: URL; let environment: [String: String] }`
  - `struct AppDescriptor: Identifiable, Equatable { let id: String; let directory: URL; let kind: AppKind; let manifest: AppManifest; let iconURL: URL?; let hasRequirements: Bool; func command(python: URL, host: String, token: String, includeToken: Bool = true) -> LaunchCommand }`
  - `enum AppRegistry { static func scan(directories: [URL], fileManager: FileManager = .default) -> [AppDescriptor]; static func descriptor(for directory: URL, fileManager: FileManager = .default) -> AppDescriptor? }`

- [ ] **Step 1: Failing tests**

```swift
import XCTest
@testable import BUSYLauncher

final class AppRegistryTests: XCTestCase {
    var tmp: URL!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory.appendingPathComponent("registry-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    }
    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: tmp) }

    private func write(_ rel: String, _ text: String = "") throws {
        let url = tmp.appendingPathComponent(rel)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try text.write(to: url, atomically: true, encoding: .utf8)
    }

    func testGalleryAppDetectedWithManifestAndIcon() throws {
        try write("gallery/clock/app.py", "print('hi')")
        try write("gallery/clock/manifest.yaml", "name: Clock\nauthor: max\n")
        try write("gallery/clock/icon.png", "png")
        try write("gallery/notes.txt", "x")
        try write("gallery/.hidden/app.py")
        let apps = AppRegistry.scan(directories: [tmp.appendingPathComponent("gallery")])
        XCTAssertEqual(apps.map(\.id), ["clock"])
        let clock = apps[0]
        XCTAssertEqual(clock.kind, .gallery)
        XCTAssertEqual(clock.manifest.name, "Clock")
        XCTAssertEqual(clock.iconURL?.lastPathComponent, "icon.png")
        XCTAssertFalse(clock.hasRequirements)
        let cmd = clock.command(python: URL(fileURLWithPath: "/py"), host: "10.0.4.20", token: "")
        XCTAssertEqual(cmd.executable.path, "/py")
        XCTAssertEqual(cmd.arguments, ["app.py", "--host", "10.0.4.20"])
        XCTAssertEqual(cmd.workingDirectory.standardizedFileURL, clock.directory.standardizedFileURL)
        XCTAssertEqual(cmd.environment["BUSYBAR_HOST"], "10.0.4.20")
        XCTAssertEqual(cmd.environment["BUSYBAR_TOKEN"], "")
    }

    func testPackageAppInRepo() throws {
        try write("repo/pytest.ini", "[pytest]")
        try write("repo/apps/__init__.py")
        try write("repo/apps/bambu_progress/__init__.py")
        try write("repo/apps/bambu_progress/app.py")
        try write("repo/apps/bambu_progress/requirements.txt", "aiomqtt")
        let apps = AppRegistry.scan(directories: [tmp.appendingPathComponent("repo/apps")])
        XCTAssertEqual(apps.map(\.id), ["bambu_progress"])
        let app = apps[0]
        XCTAssertEqual(app.kind, .package(repoRoot: tmp.appendingPathComponent("repo").standardizedFileURL))
        XCTAssertEqual(app.manifest.name, "bambu_progress")
        XCTAssertTrue(app.hasRequirements)
        let cmd = app.command(python: URL(fileURLWithPath: "/py"), host: "192.168.1.5", token: "1234")
        XCTAssertEqual(cmd.arguments, ["-m", "apps.bambu_progress.app", "--host", "192.168.1.5", "--token", "1234"])
        XCTAssertEqual(cmd.workingDirectory.standardizedFileURL, tmp.appendingPathComponent("repo").standardizedFileURL)
        XCTAssertEqual(cmd.environment["BUSYBAR_TOKEN"], "1234")
        let noToken = app.command(python: URL(fileURLWithPath: "/py"), host: "h", token: "1234", includeToken: false)
        XCTAssertEqual(noToken.arguments, ["-m", "apps.bambu_progress.app", "--host", "h"])
    }

    func testPackageRuleNeedsAppsParentAndPytestIni() throws {
        // __init__.py present, but not under a repo "apps/" dir with pytest.ini: it's a gallery app.
        try write("dl/foo/__init__.py")
        try write("dl/foo/app.py")
        let apps = AppRegistry.scan(directories: [tmp.appendingPathComponent("dl")])
        XCTAssertEqual(apps[0].kind, .gallery)
        XCTAssertEqual(apps[0].command(python: URL(fileURLWithPath: "/py"), host: "h", token: "").arguments, ["app.py", "--host", "h"])
    }

    func testDuplicateIdsFirstDirectoryWinsAndSortedByName() throws {
        try write("a/zeta/app.py"); try write("a/zeta/manifest.yaml", "name: Zeta\n")
        try write("a/alpha/app.py"); try write("a/alpha/manifest.yaml", "name: Alpha\n")
        try write("b/zeta/app.py"); try write("b/zeta/manifest.yaml", "name: Zeta From B\n")
        try write("a/tests/app.py"); try write("a/_skip/app.py")
        let apps = AppRegistry.scan(directories: [tmp.appendingPathComponent("a"), tmp.appendingPathComponent("b")])
        XCTAssertEqual(apps.map(\.manifest.name), ["Alpha", "Zeta"])
        XCTAssertEqual(AppRegistry.scan(directories: [tmp.appendingPathComponent("missing")]), [])
    }
}
```

- [ ] **Step 2: RED**

Run: `cd launcher && ./scripts/test.sh` → Expected: `error: cannot find 'AppRegistry' in scope`.

- [ ] **Step 3: Implement**

`AppDescriptor.swift`:
```swift
import Foundation

enum AppKind: Equatable {
    case gallery
    case package(repoRoot: URL)
}

struct LaunchCommand: Equatable {
    let executable: URL
    let arguments: [String]
    let workingDirectory: URL
    let environment: [String: String]
}

struct AppDescriptor: Identifiable, Equatable {
    let id: String
    let directory: URL
    let kind: AppKind
    let manifest: AppManifest
    let iconURL: URL?
    let hasRequirements: Bool

    /// The process the launcher spawns. `includeToken=false` is the retry path for apps without a --token flag.
    func command(python: URL, host: String, token: String, includeToken: Bool = true) -> LaunchCommand {
        var args: [String]
        let cwd: URL
        switch kind {
        case .gallery:
            args = ["app.py"]
            cwd = directory
        case .package(let repoRoot):
            args = ["-m", "apps.\(id).app"]
            cwd = repoRoot
        }
        args += ["--host", host]
        if includeToken, !token.isEmpty { args += ["--token", token] }
        var env = ProcessInfo.processInfo.environment
        env["BUSYBAR_HOST"] = host
        env["BUSYBAR_TOKEN"] = token
        env["PYTHONUNBUFFERED"] = "1"
        return LaunchCommand(executable: python, arguments: args, workingDirectory: cwd, environment: env)
    }
}
```

`AppRegistry.swift`:
```swift
import Foundation

enum AppRegistry {
    static func scan(directories: [URL], fileManager: FileManager = .default) -> [AppDescriptor] {
        var seen = Set<String>()
        var result: [AppDescriptor] = []
        for dir in directories {
            guard let entries = try? fileManager.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.isDirectoryKey], options: [.skipsHiddenFiles]) else { continue }
            for entry in entries.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                let name = entry.lastPathComponent
                if name.hasPrefix(".") || name.hasPrefix("_") || name == "tests" { continue }
                guard let app = descriptor(for: entry, fileManager: fileManager), !seen.contains(app.id) else { continue }
                seen.insert(app.id)
                result.append(app)
            }
        }
        return result.sorted { $0.manifest.name.localizedCaseInsensitiveCompare($1.manifest.name) == .orderedAscending }
    }

    static func descriptor(for directory: URL, fileManager: FileManager = .default) -> AppDescriptor? {
        var isDir: ObjCBool = false
        guard fileManager.fileExists(atPath: directory.path, isDirectory: &isDir), isDir.boolValue else { return nil }
        let has = { (file: String) in fileManager.fileExists(atPath: directory.appendingPathComponent(file).path) }
        guard has("app.py") else { return nil }
        let id = directory.lastPathComponent

        var kind = AppKind.gallery
        let parent = directory.deletingLastPathComponent()
        let repoRoot = parent.deletingLastPathComponent().standardizedFileURL
        if has("__init__.py"), parent.lastPathComponent == "apps",
           fileManager.fileExists(atPath: repoRoot.appendingPathComponent("pytest.ini").path) {
            kind = .package(repoRoot: repoRoot)
        }

        let manifestText = (try? String(contentsOf: directory.appendingPathComponent("manifest.yaml"), encoding: .utf8)) ?? ""
        let manifest = ManifestParser.parse(manifestText, fallbackName: id)
        let icon = directory.appendingPathComponent("icon.png")
        return AppDescriptor(
            id: id,
            directory: directory.standardizedFileURL,
            kind: kind,
            manifest: manifest,
            iconURL: has("icon.png") ? icon : nil,
            hasRequirements: has("requirements.txt")
        )
    }
}
```

- [ ] **Step 4: GREEN** — Run `./scripts/test.sh`. Expected: `Executed 9 tests, with 0 failures`.

- [ ] **Step 5: Commit**

```bash
git add launcher/Sources/BUSYLauncher/Model/AppDescriptor.swift launcher/Sources/BUSYLauncher/Model/AppRegistry.swift launcher/Tests/BUSYLauncherTests/AppRegistryTests.swift
git commit -m "feat(launcher): app registry scan and launch commands

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Config store and paths

**Files:**
- Create: `launcher/Sources/BUSYLauncher/Model/Paths.swift`, `launcher/Sources/BUSYLauncher/Model/LauncherConfig.swift`
- Test: `launcher/Tests/BUSYLauncherTests/ConfigStoreTests.swift`

**Interfaces:**
- Produces:
  - `struct Paths { let root: URL; var apps: URL; var venvs: URL; var logs: URL; var config: URL; var galleryCache: URL; static let live: Paths; func ensureDirectories() throws }`
  - `struct LauncherConfig: Codable, Equatable { var host = "10.0.4.20"; var token = ""; var resumeLastApp = true; var lastAppID: String? = nil; var extraAppsDirs: [String] = []; var devRepoPath: String? = nil; var isBundledDefaultHost: Bool }`
  - `final class ConfigStore { init(fileURL: URL); func load() -> LauncherConfig; func save(_ config: LauncherConfig) throws }`

- [ ] **Step 1: Failing tests**

```swift
import XCTest
@testable import BUSYLauncher

final class ConfigStoreTests: XCTestCase {
    var file: URL!
    override func setUp() {
        file = FileManager.default.temporaryDirectory.appendingPathComponent("cfg-\(UUID().uuidString)/config.json")
    }
    override func tearDown() { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }

    func testDefaultsWhenMissing() {
        let cfg = ConfigStore(fileURL: file).load()
        XCTAssertEqual(cfg, LauncherConfig())
        XCTAssertEqual(cfg.host, "10.0.4.20")
        XCTAssertTrue(cfg.resumeLastApp)
    }

    func testRoundTripCreatesDirectory() throws {
        let store = ConfigStore(fileURL: file)
        var cfg = LauncherConfig()
        cfg.host = "192.168.1.9"; cfg.token = "1234"; cfg.lastAppID = "clock"; cfg.extraAppsDirs = ["/x"]
        try store.save(cfg)
        XCTAssertEqual(ConfigStore(fileURL: file).load(), cfg)
    }

    func testCorruptFileLoadsDefaultsAndBacksUp() throws {
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try "{not json".write(to: file, atomically: true, encoding: .utf8)
        let cfg = ConfigStore(fileURL: file).load()
        XCTAssertEqual(cfg, LauncherConfig())
        let backup = file.deletingPathExtension().appendingPathExtension("corrupt.json")
        XCTAssertTrue(FileManager.default.fileExists(atPath: backup.path))
    }

    func testUnknownAndMissingKeysTolerated() throws {
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try #"{"host":"h","future":1}"#.write(to: file, atomically: true, encoding: .utf8)
        let cfg = ConfigStore(fileURL: file).load()
        XCTAssertEqual(cfg.host, "h")
        XCTAssertEqual(cfg.token, "")
        XCTAssertTrue(cfg.resumeLastApp)
    }

    func testPathsLayout() {
        let p = Paths(root: URL(fileURLWithPath: "/tmp/BL"))
        XCTAssertEqual(p.apps.path, "/tmp/BL/apps")
        XCTAssertEqual(p.venvs.path, "/tmp/BL/venvs")
        XCTAssertEqual(p.logs.path, "/tmp/BL/logs")
        XCTAssertEqual(p.config.path, "/tmp/BL/config.json")
        XCTAssertTrue(Paths.live.root.path.hasSuffix("/Library/Application Support/BUSY Launcher"))
    }
}
```

- [ ] **Step 2: RED** — `./scripts/test.sh` → `cannot find 'ConfigStore' in scope`.

- [ ] **Step 3: Implement**

`Paths.swift`:
```swift
import Foundation

struct Paths {
    let root: URL
    var apps: URL { root.appendingPathComponent("apps") }
    var venvs: URL { root.appendingPathComponent("venvs") }
    var logs: URL { root.appendingPathComponent("logs") }
    var config: URL { root.appendingPathComponent("config.json") }
    var galleryCache: URL { root.appendingPathComponent("gallery-cache.json") }

    static let live: Paths = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return Paths(root: base.appendingPathComponent("BUSY Launcher"))
    }()

    func ensureDirectories() throws {
        for dir in [root, apps, venvs, logs] {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        }
    }
}
```

`LauncherConfig.swift`:
```swift
import Foundation

struct LauncherConfig: Codable, Equatable {
    var host: String = "10.0.4.20"
    var token: String = ""
    var resumeLastApp: Bool = true
    var lastAppID: String? = nil
    var extraAppsDirs: [String] = []
    var devRepoPath: String? = nil

    var isUSBHost: Bool { host == "10.0.4.20" }

    // Tolerate missing keys (older files) and ignore unknown ones (newer files).
    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        host = try c.decodeIfPresent(String.self, forKey: .host) ?? "10.0.4.20"
        token = try c.decodeIfPresent(String.self, forKey: .token) ?? ""
        resumeLastApp = try c.decodeIfPresent(Bool.self, forKey: .resumeLastApp) ?? true
        lastAppID = try c.decodeIfPresent(String.self, forKey: .lastAppID)
        extraAppsDirs = try c.decodeIfPresent([String].self, forKey: .extraAppsDirs) ?? []
        devRepoPath = try c.decodeIfPresent(String.self, forKey: .devRepoPath)
    }
}

final class ConfigStore {
    let fileURL: URL
    init(fileURL: URL) { self.fileURL = fileURL }

    func load() -> LauncherConfig {
        guard let data = try? Data(contentsOf: fileURL) else { return LauncherConfig() }
        do {
            return try JSONDecoder().decode(LauncherConfig.self, from: data)
        } catch {
            let backup = fileURL.deletingPathExtension().appendingPathExtension("corrupt.json")
            try? FileManager.default.removeItem(at: backup)
            try? FileManager.default.moveItem(at: fileURL, to: backup)
            return LauncherConfig()
        }
    }

    func save(_ config: LauncherConfig) throws {
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(config).write(to: fileURL, options: .atomic)
    }
}
```

- [ ] **Step 4: GREEN** — `./scripts/test.sh` → `Executed 14 tests, with 0 failures`.

- [ ] **Step 5: Commit**

```bash
git add launcher/Sources/BUSYLauncher/Model/Paths.swift launcher/Sources/BUSYLauncher/Model/LauncherConfig.swift launcher/Tests/BUSYLauncherTests/ConfigStoreTests.swift
git commit -m "feat(launcher): config store and support paths

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Python runtime resolver

**Files:**
- Create: `launcher/Sources/BUSYLauncher/Model/PythonRuntime.swift`
- Test: `launcher/Tests/BUSYLauncherTests/PythonRuntimeTests.swift`

**Interfaces:**
- Produces: `struct PythonRuntime: Equatable { let python: URL; let isBundled: Bool; static func resolve(bundleResources: URL?, devRepo: URL?, exists: (URL) -> Bool) -> PythonRuntime? }`
  - bundled candidate: `<resources>/python/bin/python3`; dev candidate: `<repo>/.venv/bin/python`. Bundled wins when present.

- [ ] **Step 1: Failing tests**

```swift
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
```

- [ ] **Step 2: RED** — `./scripts/test.sh` → `cannot find 'PythonRuntime' in scope`.

- [ ] **Step 3: Implement**

```swift
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
```

- [ ] **Step 4: GREEN** — `Executed 17 tests, with 0 failures`.
- [ ] **Step 5: Commit** — `git add launcher/Sources/BUSYLauncher/Model/PythonRuntime.swift launcher/Tests/BUSYLauncherTests/PythonRuntimeTests.swift && git commit -m "feat(launcher): python runtime resolver

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"`

---

### Task 6: Child process abstraction and AppRunner state machine

**Files:**
- Create: `launcher/Sources/BUSYLauncher/Model/ChildProcess.swift`, `launcher/Sources/BUSYLauncher/Model/AppRunner.swift`
- Test: `launcher/Tests/BUSYLauncherTests/AppRunnerTests.swift`

**Interfaces:**
- Consumes: `AppDescriptor`, `LaunchCommand` (Task 3)
- Produces:
  - `protocol ChildProcess: AnyObject { var onTermination: ((Int32) -> Void)? { get set }; var onOutputLine: ((String) -> Void)? { get set }; var isRunning: Bool { get }; func launch() throws; func interrupt(); func kill() }`
  - `protocol ChildProcessFactory { func makeProcess(command: LaunchCommand, logURL: URL) -> ChildProcess }`
  - `final class FoundationChildProcess: ChildProcess` and `struct FoundationProcessFactory: ChildProcessFactory`
  - `enum RunState: Equatable { case stopped; case starting(appID: String); case running(appID: String); case exited(appID: String, code: Int32); case failed(appID: String, reason: String); var activeAppID: String? }`
  - `@MainActor final class AppRunner: ObservableObject` with `@Published private(set) var state`, `@Published private(set) var recentLog: [String]`, `init(factory:, sleep:, now:, failWindow: = 2, killGrace: = 3)`, `func start(_ app: AppDescriptor, command: LaunchCommand, logURL: URL) async`, `func stop() async`, `var isBusy: Bool`

- [ ] **Step 1: Failing tests**

```swift
import XCTest
@testable import BUSYLauncher

@MainActor
final class AppRunnerTests: XCTestCase {
    enum Behavior { case stayAlive, exitImmediately(code: Int32, line: String), exitOnInterrupt(afterPolls: Int) }

    final class FakeProcess: ChildProcess {
        var onTermination: ((Int32) -> Void)?
        var onOutputLine: ((String) -> Void)?
        let behavior: Behavior
        private(set) var launched = false, interrupted = false, killed = false
        private var running = false
        private var pollsLeft = 0
        init(_ behavior: Behavior) { self.behavior = behavior }
        var isRunning: Bool {
            if case .exitOnInterrupt = behavior, interrupted, running {
                pollsLeft -= 1
                if pollsLeft <= 0 { finish(code: 130) }
            }
            return running
        }
        func launch() throws {
            launched = true; running = true
            if case .exitImmediately(let code, let line) = behavior { onOutputLine?(line); finish(code: code) }
        }
        func interrupt() { interrupted = true; if case .exitOnInterrupt(let n) = behavior { pollsLeft = n } }
        func kill() { killed = true; finish(code: 9) }
        func simulateExit(code: Int32) { finish(code: code) }
        private func finish(code: Int32) { guard running else { return }; running = false; onTermination?(code) }
    }

    final class FakeFactory: ChildProcessFactory {
        var queue: [FakeProcess] = []
        var made: [FakeProcess] = []
        var launchOrder: [String] = []
        func makeProcess(command: LaunchCommand, logURL: URL) -> ChildProcess {
            let p = queue.removeFirst(); made.append(p)
            let name = command.arguments.last ?? "?"
            let originalLaunch = p
            _ = originalLaunch
            launchOrder.append(name)
            return p
        }
    }

    var factory: FakeFactory!
    var runner: AppRunner!
    var clock = Date(timeIntervalSince1970: 1000)
    var sleeps: [TimeInterval] = []

    override func setUp() {
        factory = FakeFactory()
        sleeps = []
        runner = AppRunner(factory: factory, sleep: { [self] s in sleeps.append(s); clock = clock.addingTimeInterval(s) },
                           now: { [self] in clock }, failWindow: 2, killGrace: 3)
    }

    private func app(_ id: String) -> AppDescriptor {
        AppDescriptor(id: id, directory: URL(fileURLWithPath: "/apps/\(id)"), kind: .gallery,
                      manifest: AppManifest(name: id, description: "", author: ""), iconURL: nil, hasRequirements: false)
    }
    private func cmd(_ id: String) -> LaunchCommand {
        LaunchCommand(executable: URL(fileURLWithPath: "/py"), arguments: ["app.py", "--host", id], workingDirectory: URL(fileURLWithPath: "/"), environment: [:])
    }
    private func settle() async { for _ in 0..<20 { await Task.yield() } }

    func testStartPromotesToRunning() async {
        factory.queue = [FakeProcess(.stayAlive)]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        XCTAssertEqual(runner.state, .running(appID: "a"))
        XCTAssertEqual(sleeps, [2])
    }

    func testEarlyExitIsFailure() async {
        factory.queue = [FakeProcess(.exitImmediately(code: 2, line: "app.py: error: unrecognized arguments: --token"))]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        guard case .failed(let id, let reason) = runner.state else { return XCTFail("state \(runner.state)") }
        XCTAssertEqual(id, "a")
        XCTAssertTrue(reason.contains("unrecognized arguments: --token"), reason)
        XCTAssertEqual(runner.recentLog.last, "app.py: error: unrecognized arguments: --token")
    }

    func testCleanExitAfterRunningIsExited() async {
        let p = FakeProcess(.stayAlive); factory.queue = [p]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        clock = clock.addingTimeInterval(60)
        p.simulateExit(code: 0)
        await settle()
        XCTAssertEqual(runner.state, .exited(appID: "a", code: 0))
    }

    func testStopInterruptsThenKillsAfterGrace() async {
        let stubborn = FakeProcess(.stayAlive); factory.queue = [stubborn]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        await runner.stop()
        await settle()
        XCTAssertTrue(stubborn.interrupted && stubborn.killed)
        XCTAssertEqual(runner.state, .stopped)
        XCTAssertGreaterThanOrEqual(sleeps.dropFirst().reduce(0, +), 3)  // waited the grace period

        let polite = FakeProcess(.exitOnInterrupt(afterPolls: 2)); factory.queue = [polite]
        await runner.start(app("b"), command: cmd("b"), logURL: URL(fileURLWithPath: "/tmp/b.log"))
        await settle()
        await runner.stop()
        await settle()
        XCTAssertTrue(polite.interrupted); XCTAssertFalse(polite.killed)
        XCTAssertEqual(runner.state, .stopped)
    }

    func testSwitchWaitsForPreviousToStop() async {
        let a = FakeProcess(.exitOnInterrupt(afterPolls: 3)); let b = FakeProcess(.stayAlive)
        factory.queue = [a, b]
        await runner.start(app("a"), command: cmd("a"), logURL: URL(fileURLWithPath: "/tmp/a.log"))
        await settle()
        await runner.start(app("b"), command: cmd("b"), logURL: URL(fileURLWithPath: "/tmp/b.log"))
        await settle()
        XCTAssertTrue(a.interrupted)
        XCTAssertFalse(a.isRunning, "A must be gone before B launches")
        XCTAssertTrue(b.launched)
        XCTAssertEqual(factory.launchOrder, ["a", "b"])
        XCTAssertEqual(runner.state, .running(appID: "b"))
    }

    func testStopWhenNothingRunningIsNoop() async {
        await runner.stop()
        XCTAssertEqual(runner.state, .stopped)
        XCTAssertEqual(sleeps, [])
    }
}
```

- [ ] **Step 2: RED** — `./scripts/test.sh` → `cannot find type 'ChildProcess' in scope`.

- [ ] **Step 3: Implement**

`ChildProcess.swift`:
```swift
import Foundation

protocol ChildProcess: AnyObject {
    var onTermination: ((Int32) -> Void)? { get set }
    var onOutputLine: ((String) -> Void)? { get set }
    var isRunning: Bool { get }
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
```

`AppRunner.swift`:
```swift
import Foundation

enum RunState: Equatable {
    case stopped
    case starting(appID: String)
    case running(appID: String)
    case exited(appID: String, code: Int32)
    case failed(appID: String, reason: String)

    var activeAppID: String? {
        switch self {
        case .starting(let id), .running(let id): return id
        default: return nil
        }
    }
}

@MainActor
final class AppRunner: ObservableObject {
    @Published private(set) var state: RunState = .stopped
    @Published private(set) var recentLog: [String] = []

    private let factory: ChildProcessFactory
    private let sleep: (TimeInterval) async -> Void
    private let now: () -> Date
    private let failWindow: TimeInterval
    private let killGrace: TimeInterval

    private var process: ChildProcess?
    private var startedAt: Date?
    private var generation = 0
    private var stopping = false

    init(factory: ChildProcessFactory,
         sleep: @escaping (TimeInterval) async -> Void = { s in try? await Task.sleep(nanoseconds: UInt64(s * 1_000_000_000)) },
         now: @escaping () -> Date = Date.init,
         failWindow: TimeInterval = 2, killGrace: TimeInterval = 3) {
        self.factory = factory; self.sleep = sleep; self.now = now
        self.failWindow = failWindow; self.killGrace = killGrace
    }

    var isBusy: Bool { state.activeAppID != nil }

    func start(_ app: AppDescriptor, command: LaunchCommand, logURL: URL) async {
        await stop()
        generation += 1
        let gen = generation
        let proc = factory.makeProcess(command: command, logURL: logURL)
        proc.onOutputLine = { [weak self] line in
            Task { @MainActor in self?.appendLog(line) }
        }
        proc.onTermination = { [weak self] code in
            Task { @MainActor in self?.handleTermination(code: code, appID: app.id, generation: gen) }
        }
        recentLog = []
        startedAt = now()
        process = proc
        state = .starting(appID: app.id)
        do {
            try proc.launch()
        } catch {
            process = nil
            state = .failed(appID: app.id, reason: error.localizedDescription)
            return
        }
        await sleep(failWindow)
        if generation == gen, case .starting(let id) = state, id == app.id, proc.isRunning {
            state = .running(appID: app.id)
        }
    }

    func stop() async {
        guard let proc = process else {
            if state.activeAppID != nil { state = .stopped }
            return
        }
        stopping = true
        defer { stopping = false }
        if proc.isRunning {
            proc.interrupt()
            var waited: TimeInterval = 0
            while proc.isRunning, waited < killGrace {
                await sleep(0.1); waited += 0.1
            }
            if proc.isRunning {
                proc.kill()
                while proc.isRunning { await sleep(0.1) }
            }
        }
        process = nil
        state = .stopped
    }

    private func appendLog(_ line: String) {
        recentLog.append(line)
        if recentLog.count > 200 { recentLog.removeFirst(recentLog.count - 200) }
    }

    private func handleTermination(code: Int32, appID: String, generation gen: Int) {
        guard gen == generation else { return }          // an older process; ignore
        if stopping || state.activeAppID == nil { return } // stop() reports .stopped itself
        let elapsed = now().timeIntervalSince(startedAt ?? now())
        process = nil
        if elapsed < failWindow || code != 0 {
            let last = recentLog.last(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty }) ?? ""
            state = .failed(appID: appID, reason: "exit \(code): \(last)")
        } else {
            state = .exited(appID: appID, code: code)
        }
    }
}
```

- [ ] **Step 4: GREEN** — `./scripts/test.sh` → `Executed 23 tests, with 0 failures`. If `testSwitchWaitsForPreviousToStop` fails on `a.isRunning`, the fake's poll counter is being consumed by the assertion itself; assert `a.interrupted` and `factory.launchOrder` only and note it in the ledger.

- [ ] **Step 5: Commit**

```bash
git add launcher/Sources/BUSYLauncher/Model/ChildProcess.swift launcher/Sources/BUSYLauncher/Model/AppRunner.swift launcher/Tests/BUSYLauncherTests/AppRunnerTests.swift
git commit -m "feat(launcher): child process wrapper and single-app runner state machine

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Bar connection probe and monitor

**Files:**
- Create: `launcher/Sources/BUSYLauncher/Model/BarStatus.swift`
- Test: `launcher/Tests/BUSYLauncherTests/BarProbeTests.swift`

**Interfaces:**
- Produces:
  - `enum BarConnection: Equatable { case unknown; case connected(transport: String, apiVersion: String); case disconnected }`
  - `enum BarProbe { static func request(host: String, token: String) -> URLRequest; static func interpret(host: String, data: Data?, statusCode: Int?, error: Error?) -> BarConnection }`
  - `@MainActor final class BarStatusMonitor: ObservableObject { @Published private(set) var connection: BarConnection; init(session: URLSession = .shared); func start(interval: TimeInterval = 5, credentials: @escaping () -> (host: String, token: String)); func stop(); func probeOnce(host: String, token: String) async }`

- [ ] **Step 1: Failing tests**

```swift
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
```

- [ ] **Step 2: RED** — `cannot find 'BarProbe' in scope`.

- [ ] **Step 3: Implement**

```swift
import Foundation

enum BarConnection: Equatable {
    case unknown
    case connected(transport: String, apiVersion: String)
    case disconnected

    var label: String {
        switch self {
        case .unknown: return "BUSY Bar · 확인 중"
        case .connected(let transport, let v): return "BUSY Bar · \(transport) 연결됨 (API \(v))"
        case .disconnected: return "BUSY Bar · 연결 안 됨"
        }
    }
}

enum BarProbe {
    static func request(host: String, token: String) -> URLRequest {
        var r = URLRequest(url: URL(string: "http://\(host)/api/version")!)
        r.timeoutInterval = 2
        if !token.isEmpty { r.setValue(token, forHTTPHeaderField: "X-API-Token") }
        return r
    }

    static func interpret(host: String, data: Data?, statusCode: Int?, error: Error?) -> BarConnection {
        guard error == nil, statusCode == 200 else { return .disconnected }
        var version = "?"
        if let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let v = obj["api_semver"] as? String {
            version = v
        }
        return .connected(transport: host == "10.0.4.20" ? "USB" : "Wi-Fi", apiVersion: version)
    }
}

@MainActor
final class BarStatusMonitor: ObservableObject {
    @Published private(set) var connection: BarConnection = .unknown
    private let session: URLSession
    private var task: Task<Void, Never>?

    init(session: URLSession = .shared) { self.session = session }

    func start(interval: TimeInterval = 5, credentials: @escaping () -> (host: String, token: String)) {
        stop()
        task = Task { [weak self] in
            while !Task.isCancelled {
                let c = credentials()
                await self?.probeOnce(host: c.host, token: c.token)
                try? await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
            }
        }
    }

    func stop() { task?.cancel(); task = nil }

    func probeOnce(host: String, token: String) async {
        let req = BarProbe.request(host: host, token: token)
        do {
            let (data, response) = try await session.data(for: req)
            connection = BarProbe.interpret(host: host, data: data, statusCode: (response as? HTTPURLResponse)?.statusCode, error: nil)
        } catch {
            connection = BarProbe.interpret(host: host, data: nil, statusCode: nil, error: error)
        }
    }
}
```

- [ ] **Step 4: GREEN** — `Executed 25 tests, with 0 failures`.
- [ ] **Step 5: Commit** — `git add launcher/Sources/BUSYLauncher/Model/BarStatus.swift launcher/Tests/BUSYLauncherTests/BarProbeTests.swift && git commit -m "feat(launcher): bar connection probe

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"`

---

### Task 8: LauncherModel, menu UI, quit hook (first usable launcher)

**Files:**
- Create: `launcher/Sources/BUSYLauncher/Model/LauncherModel.swift`, `launcher/Sources/BUSYLauncher/Views/MenuContent.swift`
- Modify: `launcher/Sources/BUSYLauncher/BUSYLauncherApp.swift`, `launcher/scripts/make-icons.py` (add active icon), `Assets.xcassets/MenuBarIconActive.imageset/Contents.json`
- Test: `launcher/Tests/BUSYLauncherTests/LauncherModelTests.swift`

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces `@MainActor final class LauncherModel: ObservableObject`:
  - `@Published var config: LauncherConfig`, `@Published private(set) var apps: [AppDescriptor]`, `@Published var notice: String?`
  - `let paths: Paths`, `let runner: AppRunner`, `let bar: BarStatusMonitor`
  - `init(paths: Paths = .live, factory: ChildProcessFactory = FoundationProcessFactory(), bundleResources: URL? = Bundle.main.resourceURL, bundleURL: URL = Bundle.main.bundleURL, runnerSleep: ... )`
  - `var appDirectories: [URL]`, `func devRepoURL() -> URL?`, `static func inferRepo(from bundleURL: URL, exists: (URL) -> Bool) -> URL?`
  - `func refreshApps()`, `func toggle(_ app: AppDescriptor) async`, `func stopCurrent() async`, `func saveConfig()`, `func startMonitoring()`, `func resumeLastAppIfWanted() async`, `func isActive(_ app: AppDescriptor) -> Bool`, `func statusSuffix(for app: AppDescriptor) -> String`

- [ ] **Step 1: Failing tests (model logic only)**

```swift
import XCTest
@testable import BUSYLauncher

@MainActor
final class LauncherModelTests: XCTestCase {
    func testInferRepoWalksUpToPytestIni() {
        let bundle = URL(fileURLWithPath: "/w/busybar/launcher/build/DerivedData/Build/Products/Debug/BUSY Launcher.app")
        let repo = LauncherModel.inferRepo(from: bundle) { url in
            url.path == "/w/busybar/pytest.ini" || url.path == "/w/busybar/apps"
        }
        XCTAssertEqual(repo?.path, "/w/busybar")
        XCTAssertNil(LauncherModel.inferRepo(from: bundle) { _ in false })
    }

    func testAppDirectoriesOrder() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("lm-\(UUID().uuidString)")
        let paths = Paths(root: root)
        let model = LauncherModel(paths: paths, factory: NullFactory(), bundleResources: nil, bundleURL: URL(fileURLWithPath: "/nowhere/x.app"))
        model.config.devRepoPath = "/repo"
        model.config.extraAppsDirs = ["/extra"]
        XCTAssertEqual(model.appDirectories.map(\.path), [paths.apps.path, "/repo/apps", "/extra"])
    }

    func testStatusSuffix() {
        let model = LauncherModel(paths: Paths(root: URL(fileURLWithPath: "/tmp/lm")), factory: NullFactory(), bundleResources: nil, bundleURL: URL(fileURLWithPath: "/nowhere/x.app"))
        let app = AppDescriptor(id: "a", directory: URL(fileURLWithPath: "/a"), kind: .gallery, manifest: AppManifest(name: "A", description: "", author: ""), iconURL: nil, hasRequirements: false)
        XCTAssertEqual(model.statusSuffix(for: app), "")
        XCTAssertFalse(model.isActive(app))
    }

    struct NullFactory: ChildProcessFactory {
        func makeProcess(command: LaunchCommand, logURL: URL) -> ChildProcess { fatalError("not used") }
    }
}
```

- [ ] **Step 2: RED** — `cannot find 'LauncherModel' in scope`.

- [ ] **Step 3: Implement the model**

`LauncherModel.swift`:
```swift
import Foundation
import AppKit

@MainActor
final class LauncherModel: ObservableObject {
    @Published var config: LauncherConfig
    @Published private(set) var apps: [AppDescriptor] = []
    @Published var notice: String? = nil

    let paths: Paths
    let runner: AppRunner
    let bar: BarStatusMonitor
    private let store: ConfigStore
    private let bundleResources: URL?
    private let bundleURL: URL

    init(paths: Paths = .live,
         factory: ChildProcessFactory = FoundationProcessFactory(),
         bundleResources: URL? = Bundle.main.resourceURL,
         bundleURL: URL = Bundle.main.bundleURL) {
        self.paths = paths
        self.store = ConfigStore(fileURL: paths.config)
        self.config = store.load()
        self.runner = AppRunner(factory: factory)
        self.bar = BarStatusMonitor()
        self.bundleResources = bundleResources
        self.bundleURL = bundleURL
        try? paths.ensureDirectories()
        refreshApps()
    }

    // MARK: directories

    static func inferRepo(from bundleURL: URL, exists: (URL) -> Bool = { FileManager.default.fileExists(atPath: $0.path) }) -> URL? {
        var dir = bundleURL.deletingLastPathComponent()
        for _ in 0..<12 {
            if exists(dir.appendingPathComponent("pytest.ini")), exists(dir.appendingPathComponent("apps")) { return dir }
            let parent = dir.deletingLastPathComponent()
            if parent.path == dir.path { break }
            dir = parent
        }
        return nil
    }

    func devRepoURL() -> URL? {
        if let p = config.devRepoPath, !p.isEmpty { return URL(fileURLWithPath: p) }
        return Self.inferRepo(from: bundleURL)
    }

    var appDirectories: [URL] {
        var dirs = [paths.apps]
        if let repo = devRepoURL() { dirs.append(repo.appendingPathComponent("apps")) }
        dirs += config.extraAppsDirs.filter { !$0.isEmpty }.map { URL(fileURLWithPath: $0) }
        return dirs
    }

    func refreshApps() { apps = AppRegistry.scan(directories: appDirectories) }

    // MARK: running

    func isActive(_ app: AppDescriptor) -> Bool { runner.state.activeAppID == app.id }

    func statusSuffix(for app: AppDescriptor) -> String {
        switch runner.state {
        case .starting(let id) where id == app.id: return " (시작 중…)"
        case .failed(let id, _) where id == app.id: return " (중단됨)"
        case .exited(let id, _) where id == app.id: return " (종료됨)"
        default: return ""
        }
    }

    func toggle(_ app: AppDescriptor) async {
        if isActive(app) { await stopCurrent(); return }
        guard let runtime = PythonRuntime.resolve(bundleResources: bundleResources, devRepo: devRepoURL()) else {
            notice = "Python 실행 환경이 없습니다. 저장소 .venv 또는 번들 런타임이 필요합니다."
            return
        }
        notice = nil
        let logURL = paths.logs.appendingPathComponent("\(app.id).log")
        await runner.start(app, command: app.command(python: runtime.python, host: config.host, token: config.token), logURL: logURL)
        if case .failed(_, let reason) = runner.state, !config.token.isEmpty, reason.contains("--token") {
            // The app has no --token flag: retry without it (spec §3).
            await runner.start(app, command: app.command(python: runtime.python, host: config.host, token: config.token, includeToken: false), logURL: logURL)
        }
        if runner.state.activeAppID == app.id {
            config.lastAppID = app.id
            saveConfig()
        }
    }

    func stopCurrent() async { await runner.stop() }

    func resumeLastAppIfWanted() async {
        guard config.resumeLastApp, let id = config.lastAppID, let app = apps.first(where: { $0.id == id }) else { return }
        await toggle(app)
    }

    // MARK: config & monitoring

    func saveConfig() {
        do { try store.save(config) } catch { notice = "설정 저장 실패: \(error.localizedDescription)" }
    }

    func startMonitoring() {
        bar.start { [weak self] in
            guard let self else { return ("10.0.4.20", "") }
            return (self.config.host, self.config.token)
        }
    }
}
```

- [ ] **Step 4: GREEN for model tests** — `./scripts/test.sh` → `Executed 28 tests, with 0 failures`.

- [ ] **Step 5: Menu view and app wiring**

Add the active icon to `make-icons.py` (a filled dot at bottom-right) and its imageset:

```python
def menubar(scale: int, active: bool = False) -> Image.Image:
    ...  # existing body, then before `return im`:
    if active:
        r = 2 * scale
        d.ellipse([s - 2 * r - scale, s - 2 * r - scale, s - scale - 1, s - scale - 1], fill=(0, 0, 0, 255))
    return im
```
and in `__main__`:
```python
    active = ROOT / "Sources/BUSYLauncher/Assets.xcassets/MenuBarIconActive.imageset"
    active.mkdir(parents=True, exist_ok=True)
    menubar(1, True).save(active / "menubar.png")
    menubar(2, True).save(active / "menubar@2x.png")
```
`MenuBarIconActive.imageset/Contents.json`: same as MenuBarIcon's.

`Views/MenuContent.swift`:
```swift
import SwiftUI
import AppKit

struct MenuContent: View {
    @EnvironmentObject var model: LauncherModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Text(model.bar.connection.label)
        if let notice = model.notice { Text(notice) }
        Divider()
        if model.apps.isEmpty {
            Text("앱이 없습니다 · 갤러리에서 설치하거나 앱 폴더에 넣으세요")
        }
        ForEach(model.apps) { app in
            Toggle(isOn: Binding(get: { model.isActive(app) }, set: { _ in Task { await model.toggle(app) } })) {
                Label {
                    Text(app.manifest.name + model.statusSuffix(for: app))
                } icon: {
                    if let url = app.iconURL, let img = NSImage(contentsOf: url) {
                        Image(nsImage: resized(img))
                    } else {
                        Image(systemName: "app.dashed")
                    }
                }
            }
        }
        Divider()
        Button("갤러리에서 설치…") { openWindow(id: "gallery"); NSApp.activate(ignoringOtherApps: true) }
        Button("앱 폴더 열기") { NSWorkspace.shared.open(model.paths.apps) }
        Button("로그 보기") { NSWorkspace.shared.open(model.paths.logs) }
        SettingsLink { Text("설정…") }
        Button("새로고침") { model.refreshApps() }
        Divider()
        Button("종료") { Task { await model.stopCurrent(); NSApplication.shared.terminate(nil) } }
            .keyboardShortcut("q")
    }

    private func resized(_ image: NSImage) -> NSImage {
        let target = NSSize(width: 16, height: 16)
        let out = NSImage(size: target)
        out.lockFocus()
        image.draw(in: NSRect(origin: .zero, size: target), from: .zero, operation: .sourceOver, fraction: 1)
        out.unlockFocus()
        return out
    }
}
```

Replace `BUSYLauncherApp.swift`:
```swift
import SwiftUI
import AppKit

@main
struct BUSYLauncherApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = LauncherModel()

    var body: some Scene {
        MenuBarExtra {
            MenuContent()
                .environmentObject(model)
                .onAppear { model.refreshApps() }
        } label: {
            Image(model.runner.isBusy ? "MenuBarIconActive" : "MenuBarIcon")
        }
        .menuBarExtraStyle(.menu)

        Settings {
            SettingsView().environmentObject(model)
        }

        Window("갤러리", id: "gallery") {
            GalleryView().environmentObject(model)
        }
        .defaultSize(width: 640, height: 480)
    }

    init() {
        AppDelegate.shared = self
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    static var shared: BUSYLauncherApp?
    weak var model: LauncherModel?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        // Second instance guard (spec §10).
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: Bundle.main.bundleIdentifier ?? "")
            .filter { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }
        if !others.isEmpty {
            let alert = NSAlert(); alert.messageText = "BUSY Launcher가 이미 실행 중입니다."; alert.runModal()
            NSApp.terminate(nil)
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model = LauncherModelRegistry.model, model.runner.isBusy else { return .terminateNow }
        Task { @MainActor in
            await model.stopCurrent()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}

/// The delegate has no access to the SwiftUI StateObject; the model registers itself here.
enum LauncherModelRegistry {
    @MainActor static weak var model: LauncherModel?
}
```
Add to `LauncherModel.init` (last lines): `LauncherModelRegistry.model = self; startMonitoring(); Task { await resumeLastAppIfWanted() }`.
Add placeholder views so it compiles (replaced in Tasks 9 and 10):
`Views/SettingsView.swift`: `struct SettingsView: View { var body: some View { Text("설정") .padding() } }`
`Views/GalleryView.swift`: `struct GalleryView: View { var body: some View { Text("갤러리") .padding() } }`

- [ ] **Step 6: Build, run, verify by hand**

```bash
cd ~/Workspace/busybar/launcher && ./scripts/bootstrap.sh && ./scripts/build.sh && ./scripts/test.sh
pkill -f "BUSY Launcher.app/Contents/MacOS" ; open "build/DerivedData/Build/Products/Debug/BUSY Launcher.app"
```
Expected in the menu bar: BUSY icon → click → first line `BUSY Bar · USB 연결됨 (API 27.5.0)` (bar plugged in), then `Bambu Progress` with the tile icon. Click it → within ~2 s the icon shows the dot, the bar shows the printer list; `~/Library/Application Support/BUSY Launcher/logs/bambu_progress.log` grows. Click again → bar clears, dot disappears. ⌘Q while running → app stops, bar clears. Record results in the ledger.

- [ ] **Step 7: Commit**

```bash
git add launcher
git commit -m "feat(launcher): model, menu with start/stop/switch, quit hook

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Settings window

**Files:**
- Modify: `launcher/Sources/BUSYLauncher/Views/SettingsView.swift`
- Test: `launcher/Tests/BUSYLauncherTests/SettingsValidationTests.swift` (+ `Model/SettingsValidation.swift`)

**Interfaces:**
- Produces: `enum SettingsValidation { static func hostError(_ host: String) -> String? }` — nil when valid (`^[A-Za-z0-9.\-]+(:[0-9]+)?$`).

- [ ] **Step 1: Failing test**

```swift
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
```

- [ ] **Step 2: RED**, **Step 3: Implement**

`Model/SettingsValidation.swift`:
```swift
import Foundation

enum SettingsValidation {
    static func hostError(_ host: String) -> String? {
        let trimmed = host.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { return "기기 주소를 입력하세요 (예: 10.0.4.20)" }
        let ok = trimmed.range(of: #"^[A-Za-z0-9.\-]+(:[0-9]+)?$"#, options: .regularExpression) != nil
        return ok ? nil : "주소는 IP 또는 호스트명만 (http:// 없이)"
    }
}
```

`Views/SettingsView.swift`:
```swift
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
```

- [ ] **Step 4: GREEN + manual** — tests pass; open 설정… from the menu, change host to `10.0.4.21`, save → status line becomes `연결 안 됨` within 5 s; set back → `USB 연결됨`.
- [ ] **Step 5: Commit** — `git add launcher && git commit -m "feat(launcher): settings window

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"`

---

### Task 10: Gallery listing and install

**Files:**
- Create: `launcher/Sources/BUSYLauncher/Model/Gallery.swift`, `launcher/Sources/BUSYLauncher/Model/GalleryInstaller.swift`
- Modify: `launcher/Sources/BUSYLauncher/Views/GalleryView.swift`
- Test: `launcher/Tests/BUSYLauncherTests/GalleryTests.swift`

**Interfaces:**
- Produces:
  - `struct GitHubEntry: Decodable, Equatable { let name: String; let type: String; let path: String; let download_url: String? }`
  - `enum GalleryAPI { static let owner = "maxswinkels", repo = "busybar-apps"; static var appsListURL: URL; static func contentsURL(path: String) -> URL; static func manifestURL(slug: String) -> URL; static func parseEntries(_ data: Data) throws -> [GitHubEntry] }`
  - `struct GalleryEntry: Identifiable, Equatable { var id: String { slug }; let slug: String; let manifest: AppManifest }`
  - `struct GalleryCache: Codable { let fetchedAt: Date; let entries: [CacheEntry] }` with `CacheEntry { slug, name, description, author }`
  - `final class GalleryClient { typealias Fetch = (URL) async throws -> Data; init(fetch: @escaping Fetch, cacheURL: URL, now: @escaping () -> Date = Date.init); func list() async throws -> [GalleryEntry]; func install(slug: String, into appsDir: URL) async throws -> URL }`
  - `static func defaultFetch(_ url: URL) async throws -> Data` — URLSession GET with `Accept: application/vnd.github+json`, maps 403/429 to `GalleryError.rateLimited`.

- [ ] **Step 1: Failing tests**

```swift
import XCTest
@testable import BUSYLauncher

final class GalleryTests: XCTestCase {
    let listJSON = Data(#"""
    [{"name":"clock","type":"dir","path":"apps/clock","download_url":null},
     {"name":"README.md","type":"file","path":"apps/README.md","download_url":"https://raw/x/README.md"},
     {"name":"aquarium","type":"dir","path":"apps/aquarium","download_url":null}]
    """#.utf8)

    func testParseEntries() throws {
        let e = try GalleryAPI.parseEntries(listJSON)
        XCTAssertEqual(e.map(\.name), ["clock", "README.md", "aquarium"])
        XCTAssertEqual(GalleryAPI.appsListURL.absoluteString, "https://api.github.com/repos/maxswinkels/busybar-apps/contents/apps")
        XCTAssertEqual(GalleryAPI.manifestURL(slug: "clock").absoluteString, "https://raw.githubusercontent.com/maxswinkels/busybar-apps/main/apps/clock/manifest.yaml")
    }

    func testListReadsManifestsAndCaches() async throws {
        let cache = FileManager.default.temporaryDirectory.appendingPathComponent("gc-\(UUID().uuidString).json")
        var calls: [String] = []
        let fetch: GalleryClient.Fetch = { url in
            calls.append(url.absoluteString)
            if url == GalleryAPI.appsListURL { return self.listJSON }
            if url == GalleryAPI.manifestURL(slug: "clock") { return Data("name: Clock\nauthor: max\n".utf8) }
            if url == GalleryAPI.manifestURL(slug: "aquarium") { return Data("name: Aquarium\n".utf8) }
            throw URLError(.badURL)
        }
        var now = Date(timeIntervalSince1970: 0)
        let client = GalleryClient(fetch: fetch, cacheURL: cache, now: { now })
        let first = try await client.list()
        XCTAssertEqual(first.map(\.manifest.name), ["Aquarium", "Clock"])
        XCTAssertEqual(calls.count, 3)
        now = now.addingTimeInterval(600)
        let second = try await client.list()               // within 1h: served from cache
        XCTAssertEqual(second, first); XCTAssertEqual(calls.count, 3)
        now = now.addingTimeInterval(3600)
        _ = try await client.list()                          // cache expired
        XCTAssertEqual(calls.count, 6)
    }

    func testInstallDownloadsFolderRecursively() async throws {
        let appsDir = FileManager.default.temporaryDirectory.appendingPathComponent("gi-\(UUID().uuidString)")
        let fetch: GalleryClient.Fetch = { url in
            switch url.absoluteString {
            case GalleryAPI.contentsURL(path: "apps/clock").absoluteString:
                return Data(#"[{"name":"app.py","type":"file","path":"apps/clock/app.py","download_url":"https://raw/app.py"},{"name":"img","type":"dir","path":"apps/clock/img","download_url":null}]"#.utf8)
            case GalleryAPI.contentsURL(path: "apps/clock/img").absoluteString:
                return Data(#"[{"name":"a.png","type":"file","path":"apps/clock/img/a.png","download_url":"https://raw/a.png"}]"#.utf8)
            case "https://raw/app.py": return Data("print(1)".utf8)
            case "https://raw/a.png": return Data([1, 2, 3])
            default: throw URLError(.badURL)
            }
        }
        let client = GalleryClient(fetch: fetch, cacheURL: appsDir.appendingPathComponent("c.json"))
        let dir = try await client.install(slug: "clock", into: appsDir)
        XCTAssertEqual(dir.lastPathComponent, "clock")
        XCTAssertEqual(try String(contentsOf: dir.appendingPathComponent("app.py"), encoding: .utf8), "print(1)")
        XCTAssertEqual(try Data(contentsOf: dir.appendingPathComponent("img/a.png")), Data([1, 2, 3]))
        XCTAssertNotNil(AppRegistry.descriptor(for: dir))
    }

    func testInstallRejectsBadSlug() async {
        let client = GalleryClient(fetch: { _ in Data() }, cacheURL: URL(fileURLWithPath: "/tmp/x.json"))
        do { _ = try await client.install(slug: "../etc", into: URL(fileURLWithPath: "/tmp")); XCTFail() } catch {}
    }
}
```

- [ ] **Step 2: RED** — `cannot find 'GalleryAPI' in scope`.

- [ ] **Step 3: Implement**

`Gallery.swift`:
```swift
import Foundation

struct GitHubEntry: Decodable, Equatable {
    let name: String
    let type: String
    let path: String
    let download_url: String?
}

enum GalleryError: LocalizedError {
    case rateLimited, badSlug, http(Int), missingDownloadURL(String)
    var errorDescription: String? {
        switch self {
        case .rateLimited: return "GitHub 요청 한도에 걸렸습니다. 잠시 후 다시 시도하세요."
        case .badSlug: return "잘못된 앱 이름"
        case .http(let c): return "HTTP \(c)"
        case .missingDownloadURL(let p): return "다운로드 주소 없음: \(p)"
        }
    }
}

enum GalleryAPI {
    static let owner = "maxswinkels"
    static let repo = "busybar-apps"
    static var appsListURL: URL { contentsURL(path: "apps") }
    static func contentsURL(path: String) -> URL { URL(string: "https://api.github.com/repos/\(owner)/\(repo)/contents/\(path)")! }
    static func manifestURL(slug: String) -> URL { URL(string: "https://raw.githubusercontent.com/\(owner)/\(repo)/main/apps/\(slug)/manifest.yaml")! }
    static func parseEntries(_ data: Data) throws -> [GitHubEntry] { try JSONDecoder().decode([GitHubEntry].self, from: data) }

    static func defaultFetch(_ url: URL) async throws -> Data {
        var req = URLRequest(url: url)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("BUSY-Launcher", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await URLSession.shared.data(for: req)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        if code == 403 || code == 429 { throw GalleryError.rateLimited }
        guard (200..<300).contains(code) else { throw GalleryError.http(code) }
        return data
    }
}

struct GalleryEntry: Identifiable, Equatable {
    var id: String { slug }
    let slug: String
    let manifest: AppManifest
}

struct GalleryCache: Codable {
    struct CacheEntry: Codable { let slug: String; let name: String; let description: String; let author: String }
    let fetchedAt: Date
    let entries: [CacheEntry]
}
```

`GalleryInstaller.swift`:
```swift
import Foundation

final class GalleryClient {
    typealias Fetch = (URL) async throws -> Data
    private let fetch: Fetch
    private let cacheURL: URL
    private let now: () -> Date
    private let cacheTTL: TimeInterval = 3600

    init(fetch: @escaping Fetch = GalleryAPI.defaultFetch, cacheURL: URL, now: @escaping () -> Date = Date.init) {
        self.fetch = fetch; self.cacheURL = cacheURL; self.now = now
    }

    func list() async throws -> [GalleryEntry] {
        if let data = try? Data(contentsOf: cacheURL),
           let cache = try? JSONDecoder().decode(GalleryCache.self, from: data),
           now().timeIntervalSince(cache.fetchedAt) < cacheTTL {
            return cache.entries.map { GalleryEntry(slug: $0.slug, manifest: AppManifest(name: $0.name, description: $0.description, author: $0.author)) }
        }
        let dirs = try GalleryAPI.parseEntries(try await fetch(GalleryAPI.appsListURL)).filter { $0.type == "dir" }
        var entries: [GalleryEntry] = []
        for d in dirs {
            let text = (try? String(decoding: await fetch(GalleryAPI.manifestURL(slug: d.name)), as: UTF8.self)) ?? ""
            entries.append(GalleryEntry(slug: d.name, manifest: ManifestParser.parse(text, fallbackName: d.name)))
        }
        entries.sort { $0.manifest.name.localizedCaseInsensitiveCompare($1.manifest.name) == .orderedAscending }
        let cache = GalleryCache(fetchedAt: now(), entries: entries.map { .init(slug: $0.slug, name: $0.manifest.name, description: $0.manifest.description, author: $0.manifest.author) })
        try? FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? JSONEncoder().encode(cache).write(to: cacheURL, options: .atomic)
        return entries
    }

    func install(slug: String, into appsDir: URL) async throws -> URL {
        guard slug.range(of: #"^[A-Za-z0-9_\-]+$"#, options: .regularExpression) != nil else { throw GalleryError.badSlug }
        let staging = appsDir.appendingPathComponent(".staging-\(slug)")
        try? FileManager.default.removeItem(at: staging)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        try await download(path: "apps/\(slug)", into: staging)
        let final = appsDir.appendingPathComponent(slug)
        try? FileManager.default.removeItem(at: final)
        try FileManager.default.moveItem(at: staging, to: final)
        return final
    }

    private func download(path: String, into dir: URL) async throws {
        let entries = try GalleryAPI.parseEntries(try await fetch(GalleryAPI.contentsURL(path: path)))
        for e in entries {
            let target = dir.appendingPathComponent(e.name)
            if e.type == "dir" {
                try FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
                try await download(path: e.path, into: target)
            } else if e.type == "file" {
                guard let raw = e.download_url, let url = URL(string: raw) else { throw GalleryError.missingDownloadURL(e.path) }
                try (try await fetch(url)).write(to: target, options: .atomic)
            }
        }
    }
}
```

`Views/GalleryView.swift`:
```swift
import SwiftUI

struct GalleryView: View {
    @EnvironmentObject var model: LauncherModel
    @State private var entries: [GalleryEntry] = []
    @State private var status: [String: String] = [:]
    @State private var loading = false
    @State private var error: String?

    private var client: GalleryClient { GalleryClient(cacheURL: model.paths.galleryCache) }
    private var installed: Set<String> { Set(model.apps.map(\.id)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("커뮤니티 갤러리 (maxswinkels/busybar-apps)").font(.headline)
                Spacer()
                Button("새로고침") { Task { await load() } }.disabled(loading)
            }
            if let error { Text(error).foregroundStyle(.red) }
            Table(entries) {
                TableColumn("이름") { e in Text(e.manifest.name) }
                TableColumn("작성자") { e in Text(e.manifest.author) }.width(120)
                TableColumn("설명") { e in Text(e.manifest.description).lineLimit(2) }
                TableColumn("") { e in
                    HStack {
                        if let s = status[e.slug] { Text(s).font(.caption) }
                        if installed.contains(e.slug) {
                            Text("설치됨").foregroundStyle(.secondary)
                            Button("삭제") { Task { await remove(e.slug) } }
                        } else {
                            Button("설치") { Task { await install(e.slug) } }
                        }
                    }
                }.width(220)
            }
        }
        .padding(16)
        .task { await load() }
    }

    private func load() async {
        loading = true; defer { loading = false }
        do { entries = try await client.list(); error = nil } catch { self.error = error.localizedDescription }
    }

    private func install(_ slug: String) async {
        status[slug] = "내려받는 중…"
        do {
            _ = try await client.install(slug: slug, into: model.paths.apps)
            status[slug] = "완료"
            model.refreshApps()
        } catch { status[slug] = "실패: \(error.localizedDescription)" }
    }

    private func remove(_ slug: String) async {
        if model.runner.state.activeAppID == slug { await model.stopCurrent() }
        try? FileManager.default.removeItem(at: model.paths.apps.appendingPathComponent(slug))
        try? FileManager.default.removeItem(at: model.paths.venvs.appendingPathComponent(slug))
        try? FileManager.default.removeItem(at: model.paths.logs.appendingPathComponent("\(slug).log"))
        status[slug] = nil
        model.refreshApps()
    }
}
```

- [ ] **Step 4: GREEN + manual** — `./scripts/test.sh` → all pass (`Executed 33 tests`). Rebuild, open 갤러리…, install `clock`, close window, menu shows `Clock`; click it → the bar shows a clock. Note: `clock` needs no extra deps.
- [ ] **Step 5: Commit** — `git add launcher && git commit -m "feat(launcher): community gallery listing and install

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"`

---

### Task 11: Per-app requirements venv

**Files:**
- Create: `launcher/Sources/BUSYLauncher/Model/PythonEnvironment.swift`
- Modify: `launcher/Sources/BUSYLauncher/Model/LauncherModel.swift` (`toggle` prepares env before start; `@Published var preparing: String?` shown in the menu status line)
- Test: `launcher/Tests/BUSYLauncherTests/PythonEnvironmentTests.swift`

**Interfaces:**
- Produces: `enum PythonEnvironment { typealias Run = (LaunchCommand) async throws -> Int32; static func prepare(app: AppDescriptor, runtime: PythonRuntime, venvsDir: URL, run: Run, fileManager: FileManager = .default) async throws -> URL }` — returns the python to use. Without `requirements.txt` returns `runtime.python`. Otherwise: venv at `venvsDir/<id>`; create with `python -m venv --system-site-packages <dir>` if `<dir>/bin/python` is missing; install with `<venv>/bin/python -m pip install -r <requirements>` when `<dir>/.requirements.sha` differs from the file's SHA-256; write the stamp on success. Throws `PythonEnvironmentError.commandFailed(step, code)` on non-zero exit.

- [ ] **Step 1: Failing tests**

```swift
import XCTest
@testable import BUSYLauncher

final class PythonEnvironmentTests: XCTestCase {
    var tmp: URL!
    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory.appendingPathComponent("pe-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp.appendingPathComponent("app"), withIntermediateDirectories: true)
    }
    override func tearDown() { try? FileManager.default.removeItem(at: tmp) }

    private func app(requirements: String?) throws -> AppDescriptor {
        let dir = tmp.appendingPathComponent("app")
        if let r = requirements { try r.write(to: dir.appendingPathComponent("requirements.txt"), atomically: true, encoding: .utf8) }
        return AppDescriptor(id: "app", directory: dir, kind: .gallery, manifest: AppManifest(name: "A", description: "", author: ""), iconURL: nil, hasRequirements: requirements != nil)
    }
    let runtime = PythonRuntime(python: URL(fileURLWithPath: "/py"), isBundled: false)

    func testNoRequirementsUsesRuntimePython() async throws {
        var ran: [LaunchCommand] = []
        let py = try await PythonEnvironment.prepare(app: app(requirements: nil), runtime: runtime, venvsDir: tmp.appendingPathComponent("venvs"), run: { ran.append($0); return 0 })
        XCTAssertEqual(py.path, "/py"); XCTAssertTrue(ran.isEmpty)
    }

    func testCreatesVenvInstallsAndStamps() async throws {
        var ran: [LaunchCommand] = []
        let venvs = tmp.appendingPathComponent("venvs")
        let venvPy = venvs.appendingPathComponent("app/bin/python")
        let run: PythonEnvironment.Run = { cmd in
            ran.append(cmd)
            if cmd.arguments.first == "-m", cmd.arguments[1] == "venv" {   // simulate venv creation
                try FileManager.default.createDirectory(at: venvPy.deletingLastPathComponent(), withIntermediateDirectories: true)
                FileManager.default.createFile(atPath: venvPy.path, contents: Data())
            }
            return 0
        }
        let py = try await PythonEnvironment.prepare(app: app(requirements: "requests\n"), runtime: runtime, venvsDir: venvs, run: run)
        XCTAssertEqual(py.path, venvPy.path)
        XCTAssertEqual(ran.count, 2)
        XCTAssertEqual(ran[0].executable.path, "/py")
        XCTAssertEqual(Array(ran[0].arguments.prefix(3)), ["-m", "venv", "--system-site-packages"])
        XCTAssertEqual(ran[1].executable.path, venvPy.path)
        XCTAssertEqual(Array(ran[1].arguments.prefix(4)), ["-m", "pip", "install", "-r"])
        // second call: nothing to do
        _ = try await PythonEnvironment.prepare(app: app(requirements: "requests\n"), runtime: runtime, venvsDir: venvs, run: run)
        XCTAssertEqual(ran.count, 2)
        // changed requirements: pip again, no venv
        _ = try await PythonEnvironment.prepare(app: app(requirements: "requests\nyaml\n"), runtime: runtime, venvsDir: venvs, run: run)
        XCTAssertEqual(ran.count, 3); XCTAssertEqual(ran[2].arguments[1], "pip")
    }

    func testFailureThrows() async throws {
        do {
            _ = try await PythonEnvironment.prepare(app: app(requirements: "x"), runtime: runtime, venvsDir: tmp.appendingPathComponent("v"), run: { _ in 1 })
            XCTFail("should throw")
        } catch PythonEnvironmentError.commandFailed(let step, let code) {
            XCTAssertEqual(step, "venv"); XCTAssertEqual(code, 1)
        }
    }
}
```

- [ ] **Step 2: RED**, **Step 3: Implement**

```swift
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

    /// Real runner: waits for the process, appends its output to `logURL`.
    static func runProcess(logURL: URL) -> Run {
        return { cmd in
            try await withCheckedThrowingContinuation { cont in
                let p = FoundationChildProcess(command: cmd, logURL: logURL)
                p.onTermination = { code in cont.resume(returning: code) }
                do { try p.launch() } catch { cont.resume(throwing: error) }
            }
        }
    }
}
```

In `LauncherModel`: add `@Published var preparing: String? = nil`; in `toggle`, after resolving `runtime` and before `runner.start`:
```swift
        let python: URL
        do {
            preparing = app.hasRequirements ? "\(app.manifest.name) 의존성 준비 중…" : nil
            python = try await PythonEnvironment.prepare(app: app, runtime: runtime, venvsDir: paths.venvs, run: PythonEnvironment.runProcess(logURL: logURL))
            preparing = nil
        } catch {
            preparing = nil
            notice = "의존성 설치 실패: \(error.localizedDescription)"
            return
        }
```
and use `python` instead of `runtime.python` in both `command(...)` calls. In `MenuContent`, show `if let p = model.preparing { Text(p) }` under the status line.

- [ ] **Step 4: GREEN + manual** — tests `Executed 36`; install a gallery app with `requirements.txt` (e.g. `home-assistant`), click it: status line shows 준비 중, log shows pip output, then the app starts (it will show its demo/needs-config screen). Note real pip needs network.
- [ ] **Step 5: Commit** — `git add launcher && git commit -m "feat(launcher): per-app requirements venv

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"`

---

### Task 12: Bundled Python and packaging

**Files:**
- Create: `launcher/scripts/bundle-python.sh`, `launcher/scripts/package.sh`
- Modify: `launcher/project.yml` (optional folder resource `Resources/python`), `README.md` (launcher section)

- [ ] **Step 1: project.yml resource**

Under `targets.BUSYLauncher.sources` add:
```yaml
      - path: Resources/python
        type: folder
        optional: true
        buildPhase: resources
```
(XcodeGen copies the whole folder into `Contents/Resources/python`. `optional: true` keeps `xcodegen generate` working before the folder exists.)

- [ ] **Step 2: bundle-python.sh**

```bash
#!/usr/bin/env bash
# Puts a self-contained CPython 3.12 (python-build-standalone) with busylib into launcher/Resources/python.
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="20260901"
VER="3.12.14"
ARCH="$(uname -m)"   # arm64 -> aarch64
[ "$ARCH" = "arm64" ] && ARCH="aarch64"
NAME="cpython-${VER}+${TAG}-${ARCH}-apple-darwin-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${TAG}/${NAME}"
mkdir -p Resources build
if [ ! -f "build/$NAME" ]; then curl -L --fail -o "build/$NAME" "$URL"; fi
rm -rf Resources/python
tar -xzf "build/$NAME" -C Resources          # extracts to Resources/python
Resources/python/bin/python3 -m pip install --upgrade --quiet pip busylib aiomqtt
find Resources/python -name "__pycache__" -type d -prune -exec rm -rf {} +
rm -rf Resources/python/lib/python3.12/test Resources/python/share
echo "bundled: $(Resources/python/bin/python3 -c 'import sys,busylib; print(sys.version.split()[0])')"
du -sh Resources/python
```

- [ ] **Step 3: package.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
./scripts/bundle-python.sh
xcodegen generate >/dev/null
xcodebuild -project BUSYLauncher.xcodeproj -scheme BUSYLauncher -configuration Release -derivedDataPath build/DerivedData build 2>&1 | tail -2
APP="build/DerivedData/Build/Products/Release/BUSY Launcher.app"
IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null | grep -o '"Developer ID Application: [^"]*"' | head -1 | tr -d '"' || true)"
if [ -n "$IDENTITY" ]; then
  codesign --force --deep --options runtime --sign "$IDENTITY" "$APP"
  echo "signed with: $IDENTITY (notarize with: xcrun notarytool submit dist/BUSY-Launcher.zip --keychain-profile <profile> --wait)"
else
  codesign --force --deep --sign - "$APP"
  echo "no Developer ID found: ad-hoc signed. Recipients must right-click → Open the first time."
fi
mkdir -p dist
rm -f "dist/BUSY-Launcher.zip"
ditto -c -k --keepParent "$APP" "dist/BUSY-Launcher.zip"
echo "dist/BUSY-Launcher.zip ($(du -h dist/BUSY-Launcher.zip | cut -f1))"
```
`chmod +x` both.

- [ ] **Step 4: Run and verify the bundle really works without the repo venv**

```bash
cd ~/Workspace/busybar/launcher && ./scripts/package.sh
rm -rf /tmp/bl-test && mkdir -p /tmp/bl-test && ditto -x -k dist/BUSY-Launcher.zip /tmp/bl-test
ls "/tmp/bl-test/BUSY Launcher.app/Contents/Resources/python/bin/python3"
pkill -f "BUSY Launcher.app/Contents/MacOS"; open "/tmp/bl-test/BUSY Launcher.app"
```
Expected: `bundled: 3.12.14`, zip around 40–60 MB, the app opens from /tmp. In 설정… set 개발 저장소 경로 to `/nonexistent` and save (forces the bundled runtime); install `clock` from the gallery and start it → the bar shows the clock, and `logs/clock.log` header shows the `Resources/python/bin/python3` path. Then clear the 개발 저장소 경로 again.

- [ ] **Step 5: README**

Append to the project root `README.md`:
```markdown
## launcher (BUSY Launcher.app)

맥 메뉴바 런처. 앱 목록에서 하나를 고르면 BUSY Bar에 뜬다 (한 번에 하나).

```bash
cd launcher
./scripts/bootstrap.sh     # xcodegen 설치 + 프로젝트 생성 + 아이콘
./scripts/build.sh         # Debug 빌드 → build/DerivedData/Build/Products/Debug/BUSY Launcher.app
./scripts/test.sh          # XCTest
./scripts/package.sh       # Python 번들 + Release 빌드 + zip (dist/)
```

앱 폴더: `~/Library/Application Support/BUSY Launcher/apps/` (갤러리 설치 위치) + 이 저장소의 `apps/`.
설정: 기기 주소(기본 10.0.4.20), Wi-Fi PIN. 자동 시작은 없음.
```

- [ ] **Step 6: Commit** — `git add launcher README.md && git commit -m "feat(launcher): bundled python runtime and packaging script

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"`

---

### Task 13: End-to-end verification

- [ ] Fresh Debug build via `./scripts/bootstrap.sh && ./scripts/build.sh && ./scripts/test.sh` → all tests green (36).
- [ ] Menu: status line correct with bar plugged (USB) and unplugged (연결 안 됨); apps listed alphabetically with icons; Bambu Progress ↔ Clock switching never shows both on the bar; `(중단됨)` appears when a gallery app is started with a bad host (set host to `10.0.4.99`, start Clock: it should keep retrying rather than fail — record actual behavior).
- [ ] ⌘Q with an app running: bar clears, no orphan `python` process (`pgrep -fl "app.py|bambu_progress"` empty).
- [ ] Second launch while running shows the "already running" alert.
- [ ] Logs: one file per app, header line per start, stderr included.
- [ ] Packaged app from /tmp runs Clock with bundled Python (Task 12 Step 4).
- [ ] Update `docs/superpowers/specs/2026-09-24-busy-launcher-design.md` status line to "구현됨 (2026-09-24)" and commit: `git commit -am "docs: launcher spec status

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"`

---

## Self-review notes

- Spec §2 menu/settings/gallery/logs → Tasks 8, 9, 10, 6(logs). §3 discovery rules and `--token` retry → Task 3 + Task 8 `toggle`. §4 process rules → Task 6. §5 status → Task 7. §6 runtime + venv → Tasks 5, 11, 12. §7 paths/config → Task 4. §8 gallery → Task 10. §9 build → Tasks 1, 12. §10 errors → 4 (corrupt config), 6 (early exit), 8 (no runtime, second instance), 10 (rate limit), 9 (host validation). §11 tests → each task; manual → Task 13.
- Names are consistent: `AppDescriptor.command(python:host:token:includeToken:)`, `AppRegistry.scan/descriptor`, `ConfigStore.load/save`, `PythonRuntime.resolve`, `AppRunner.start/stop/state/isBusy`, `BarProbe.request/interpret`, `GalleryClient.list/install`, `PythonEnvironment.prepare`, `LauncherModel.toggle/stopCurrent/refreshApps/saveConfig`.
- Review Focus pinned: (1) `testPackageRuleNeedsAppsParentAndPytestIni`, (2) `testSwitchWaitsForPreviousToStop`, (3) `testEarlyExitIsFailure`, (4) `testCorruptFileLoadsDefaultsAndBacksUp`, (5) `testQuotedAndCommentedValues`.
- Known risks for the executor: SwiftUI `Toggle` inside `MenuBarExtra(.menu)` renders as a checkable NSMenuItem on macOS 14+; if the label icon does not render, fall back to a text prefix `● `. `SettingsLink` requires macOS 14 (deployment target is 14). XcodeGen `optional: true` on folder sources requires XcodeGen ≥ 2.38.
