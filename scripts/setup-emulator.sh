#!/usr/bin/env bash
# busybar-emulator (커뮤니티, MIT) 를 tools/ 에 클론하고 빌드한다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/tools"
if [ ! -d "$ROOT/tools/busybar-emulator" ]; then
  git clone https://github.com/maxswinkels/busybar-emulator.git "$ROOT/tools/busybar-emulator"
fi
cd "$ROOT/tools/busybar-emulator/web" && npm install && npm run build
echo "done. run: ./scripts/run-emulator.sh"
