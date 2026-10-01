#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
BUILD_DIR="${DISC_PORTER_BUILD_DIR:-$HOME/Library/Caches/DiscPorter/SwiftPM}"
swift test --scratch-path "$BUILD_DIR"
./mcp/.venv/bin/python -m unittest discover -s tests/engine -v
./mcp/.venv/bin/python -m unittest discover -s tests/mcp -v
./mcp/.venv/bin/python -m unittest discover -s tests/integration -v
