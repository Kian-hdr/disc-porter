#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPYCACHEPREFIX=${PYTHONPYCACHEPREFIX:-"$HOME/Library/Caches/DiscPorter/PythonBytecode"}
mkdir -p "$PYTHONPYCACHEPREFIX"
OUT=${1:-"$ROOT/packaging/dist"}
PYTHON=${DISC_PORTER_BUILD_PYTHON:-"$ROOT/packaging/cache/Python.framework/Versions/3.13/bin/python3.13"}
if [ ! -x "$PYTHON" ]; then python3 "$ROOT/packaging/prepare_python.py" >&2; fi
ARCH=${DISC_PORTER_ARCH:-arm64}
if [ "$ARCH" = x86_64 ]; then VENV="$ROOT/packaging/.venv-x86"; else VENV="$ROOT/packaging/.venv"; fi
runpython() {
  if [ "$ARCH" = x86_64 ]; then /usr/bin/arch -x86_64 "$@"; else "$@"; fi
}
if [ ! -x "$VENV/bin/python" ]; then runpython "$PYTHON" -m venv "$VENV"; fi
runpython "$VENV/bin/python" -m pip install -r "$ROOT/packaging/requirements-build.txt" >&2
[ -f "$ROOT/disc_porter_control/server.py" ] || { echo 'Packaging-safe disc_porter_control/server.py missing' >&2; exit 1; }
runpython "$VENV/bin/python" -m PyInstaller --noconfirm --clean --distpath "$OUT" --workpath "$ROOT/packaging/build-$ARCH" "$ROOT/packaging/disc_porter_helper.spec"
"$OUT/DiscPorterHelper/disc-porter-helper" --help >/dev/null
runpython "$VENV/bin/python" "$ROOT/packaging/capture_python_notices.py" "$OUT/DiscPorterHelper/THIRD_PARTY_NOTICES"

runpython "$VENV/bin/python" "$ROOT/packaging/sign_helper.py" "$OUT/DiscPorterHelper"
