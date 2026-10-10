#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcodegen generate --quiet >/dev/null 2>&1 || xcodegen generate >/dev/null
CONFIG="${1:-Debug}"
xcodebuild -project BUSYLauncher.xcodeproj -scheme BUSYLauncher -configuration "$CONFIG" \
  -derivedDataPath build/DerivedData build 2>&1 | tail -3
APP="build/DerivedData/Build/Products/$CONFIG/BUSY Launcher.app"
echo "built: $APP"
