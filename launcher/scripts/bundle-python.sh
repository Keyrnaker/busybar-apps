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
