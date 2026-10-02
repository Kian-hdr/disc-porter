#!/bin/sh
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "${DISC_PORTER_DEV_MCP:-0}" != 1 ] && [ -z "${DISC_ARCHIVE_ENDPOINT_FILE:-}" ]; then
  for APP in "${DISC_PORTER_APP:-}" "$HOME/Applications/Disc Porter.app" "/Applications/Disc Porter.app"; do
    if [ -n "$APP" ] && [ -x "$APP/Contents/Helpers/DiscPorterHelper/disc-porter-helper" ]; then
      exec "$APP/Contents/Helpers/DiscPorterHelper/disc-porter-helper" mcp
    fi
  done
fi
VENV=${DISC_PORTER_MCP_ENV:-"$HOME/Library/Caches/DiscPorter/MCP-Dev"}
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import mcp, httpx, pydantic' >/dev/null 2>&1; then
  echo "Disc Porter MCP dependencies missing. Run: $BASE/setup.sh" >&2
  exit 1
fi
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$HOME/Library/Caches/DiscPorter/PythonBytecode}"
exec "$VENV/bin/python" "$BASE/server.py"
