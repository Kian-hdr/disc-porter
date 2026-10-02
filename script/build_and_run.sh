#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-run}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
BUILD_DIR="${DISC_PORTER_BUILD_DIR:-$HOME/Library/Caches/DiscPorter/SwiftPM}"
STAGING_ROOT="$HOME/Library/Caches/DiscPorter/AppBuilds"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$HOME/Library/Caches/DiscPorter/PythonBytecode}"
mkdir -p "$STAGING_ROOT"
swift build --scratch-path "$BUILD_DIR"
HELPER="packaging/dist/DiscPorterHelper/disc-porter-helper"
if [[ ! -x "$HELPER" ]] || [[ -n "$(find engine disc_porter_control -name '*.py' -newer "$HELPER" -print -quit)" ]]; then
  ./script/build_helper.sh >"$STAGING_ROOT/helper-build.log" 2>&1
fi
if [[ ! -x packaging/dist/Tools/ffmpeg ]]; then
  ./packaging/build_codecs.sh >"$STAGING_ROOT/codec-build.log" 2>&1
fi
if [[ ! -f assets/build/catalog/Assets.car ]] || [[ -n "$(find assets/DiscPorter.icon -type f -newer assets/build/catalog/Assets.car -print -quit)" ]]; then
  ./script/build_icon.sh
fi
STAGE="$(mktemp -d "$STAGING_ROOT/build-XXXXXXXX")"
APP_BUNDLE="$STAGE/Disc Porter.app"
./script/package_app.sh "$APP_BUNDLE" "$(swift build --scratch-path "$BUILD_DIR" --show-bin-path)/DiscArchive"
printf '%s\n' "$APP_BUNDLE" > "$STAGING_ROOT/latest-app.txt"
if [[ "$MODE" = --build-only ]]; then exit 0; fi
python3 ./script/runtime_gate.py
# Only the GUI closes after its processing engine has safely exited.
pkill -x DiscPorter >/dev/null 2>&1 || true
open_app() {
  if [[ -n "${DISC_PORTER_STATE_DIR:-}" ]]; then
    /usr/bin/open -n --env "DISC_PORTER_STATE_DIR=$DISC_PORTER_STATE_DIR" "$APP_BUNDLE"
  else
    /usr/bin/open -n "$APP_BUNDLE"
  fi
}
case "$MODE" in
  run) open_app ;;
  --debug|debug) lldb -- "$APP_BUNDLE/Contents/MacOS/DiscPorter" ;;
  --logs|logs) open_app; /usr/bin/log stream --info --style compact --predicate 'process == "DiscPorter"' ;;
  --telemetry|telemetry) open_app; /usr/bin/log stream --info --style compact --predicate 'subsystem == "dev.discporter.app"' ;;
  --verify|verify) open_app; sleep 1; pgrep -x DiscPorter >/dev/null ;;
  *) echo "Usage: $0 [run|--build-only|--verify|--debug|--logs|--telemetry]" >&2; exit 2 ;;
esac
