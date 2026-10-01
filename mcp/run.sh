#!/bin/sh
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$BASE/.venv/bin/python" ] || ! "$BASE/.venv/bin/python" -c 'import mcp, httpx, pydantic' >/dev/null 2>&1; then
  echo "Disc Porter MCP dependencies missing. Run: $BASE/setup.sh" >&2
  exit 1
fi
exec "$BASE/.venv/bin/python" "$BASE/server.py"
