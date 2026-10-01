#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-run}"
APP_NAME="DiscPorter"
BUILD_DIR="${DISC_PORTER_BUILD_DIR:-$HOME/Library/Caches/DiscPorter/SwiftPM}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
APP_BUNDLE="$ROOT_DIR/dist/Disc Porter.app"
CONTENTS="$APP_BUNDLE/Contents"
# The persistent processing engine deliberately survives GUI relaunches.
# Never kill FFmpeg, MakeMKV or the engine from this development script.
pkill -x "$APP_NAME" >/dev/null 2>&1 || true
swift build --scratch-path "$BUILD_DIR"
if [[ ! -f assets/build/catalog/Assets.car ]] || [[ -n "$(find assets/DiscPorter.icon -type f -newer assets/build/catalog/Assets.car -print -quit)" ]]; then
  ./script/build_icon.sh
fi
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"
cp "$(swift build --scratch-path "$BUILD_DIR" --show-bin-path)/DiscArchive" "$CONTENTS/MacOS/$APP_NAME"
chmod +x "$CONTENTS/MacOS/$APP_NAME"
cp assets/build/catalog/Assets.car "$CONTENTS/Resources/Assets.car"
cp assets/build/catalog/DiscPorter.icns "$CONTENTS/Resources/DiscPorter.icns"
if [[ -d engine ]]; then
  mkdir -p "$CONTENTS/Resources/engine"
  /usr/bin/rsync -a --exclude '__pycache__' --exclude '*.pyc' engine/ "$CONTENTS/Resources/engine/"
fi
python3 - "$CONTENTS/Info.plist" "$ROOT_DIR" <<'PY'
import plistlib, sys
with open(sys.argv[1], 'wb') as f:
    plistlib.dump({
        'CFBundleExecutable':'DiscPorter', 'CFBundleIdentifier':'dev.discporter.app',
        'CFBundleName':'Disc Porter', 'CFBundleDisplayName':'Disc Porter',
        'CFBundlePackageType':'APPL', 'CFBundleShortVersionString':'0.1.0',
        'CFBundleVersion':'1', 'LSMinimumSystemVersion':'14.0',
        'NSPrincipalClass':'NSApplication', 'NSHighResolutionCapable':True,
        'DiscPorterSourceRoot':sys.argv[2],
        'CFBundleIconName':'DiscPorter', 'CFBundleIconFile':'DiscPorter',
    }, f)
PY
# Strip build-only Finder metadata that cloud-synced source directories can add.
# Source artwork and user files are never modified by this step.
/usr/bin/xattr -cr "$APP_BUNDLE"
/usr/bin/codesign --force --sign - "$APP_BUNDLE"
open_app() {
  if [[ -n "${DISC_PORTER_STATE_DIR:-}" ]]; then
    /usr/bin/open -n --env "DISC_PORTER_STATE_DIR=$DISC_PORTER_STATE_DIR" "$APP_BUNDLE"
  else
    /usr/bin/open -n "$APP_BUNDLE"
  fi
}
case "$MODE" in
  run) open_app ;;
  --build-only) ;;
  --debug|debug) lldb -- "$CONTENTS/MacOS/$APP_NAME" ;;
  --logs|logs) open_app; /usr/bin/log stream --info --style compact --predicate 'process == "DiscPorter"' ;;
  --telemetry|telemetry) open_app; /usr/bin/log stream --info --style compact --predicate 'subsystem == "dev.discporter.app"' ;;
  --verify|verify) open_app; sleep 1; pgrep -x "$APP_NAME" >/dev/null ;;
  *) echo "Usage: $0 [run|--build-only|--verify|--debug|--logs|--telemetry]" >&2; exit 2 ;;
esac
