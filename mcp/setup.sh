#!/bin/sh
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${DISC_ARCHIVE_PYTHON:-python3}
if ! "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
  for candidate in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.13; do
    if [ -x "$candidate" ]; then PYTHON=$candidate; break; fi
  done
fi
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
"$PYTHON" -m venv "$BASE/.venv"
"$BASE/.venv/bin/python" -m pip install -r "$BASE/requirements.txt" >&2
