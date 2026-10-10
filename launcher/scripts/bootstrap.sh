#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v xcodegen >/dev/null || brew install xcodegen
"$(dirname "$0")/../../.venv/bin/python" scripts/make-icons.py
xcodegen generate
echo "generated BUSYLauncher.xcodeproj"
