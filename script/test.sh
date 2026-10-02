#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
BUILD_DIR="${DISC_PORTER_BUILD_DIR:-$HOME/Library/Caches/DiscPorter/SwiftPM}"
MCP_ENV="${DISC_PORTER_MCP_ENV:-$HOME/Library/Caches/DiscPorter/MCP-Dev}"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$HOME/Library/Caches/DiscPorter/PythonBytecode}"
export DISC_PORTER_DEV_MCP=1
swift test --scratch-path "$BUILD_DIR"
"$MCP_ENV/bin/python" -m unittest discover -s tests/engine -v
"$MCP_ENV/bin/python" -m unittest discover -s tests/mcp -v
"$MCP_ENV/bin/python" -m unittest discover -s tests/integration -v
