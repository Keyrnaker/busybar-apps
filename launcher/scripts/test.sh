#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcodegen generate --quiet >/dev/null 2>&1 || xcodegen generate >/dev/null
xcodebuild -project BUSYLauncher.xcodeproj -scheme BUSYLauncher -destination 'platform=macOS' \
  -derivedDataPath build/DerivedData test 2>&1 \
  | grep -E "\.swift:[0-9]+:[0-9]+: error:|Test Case .* (passed|failed)|Executed [0-9]+ tests?|TEST (SUCCEEDED|FAILED)|error: Cannot|BUILD FAILED" \
  | sort -u | tail -40
