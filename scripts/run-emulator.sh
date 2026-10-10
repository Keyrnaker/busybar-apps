#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/tools/busybar-emulator" && exec node server.js   # http://127.0.0.1:8080
