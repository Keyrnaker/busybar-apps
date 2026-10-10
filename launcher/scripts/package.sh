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
