#!/bin/sh
# Assembly is a new immutable bundle. Root wrappers own replacement of installed artifacts.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
[ "$#" -eq 2 ] || { echo 'Usage: package_app.sh NEW_APP_PATH SWIFT_EXECUTABLE' >&2; exit 2; }
APP=$1
EXE=$2
ARCH=${DISC_PORTER_ARCH:-arm64}
case "$ARCH" in
  arm64) PACKAGE_DIST="$ROOT/packaging/dist" ;;
  x86_64) PACKAGE_DIST="$ROOT/packaging/dist-x86" ;;
  *) echo 'DISC_PORTER_ARCH must be arm64 or x86_64' >&2; exit 2 ;;
esac
[ ! -e "$APP" ] || { echo 'Refusing to replace an existing bundle; use a fresh staging path and verify no active engine before replacement.' >&2; exit 1; }
[ -x "$EXE" ] || { echo 'Swift executable missing' >&2; exit 1; }
for binary in "$EXE" "$PACKAGE_DIST/DiscPorterHelper/disc-porter-helper" "$PACKAGE_DIST/Tools/ffmpeg" "$PACKAGE_DIST/Tools/ffprobe"; do
  lipo -verify_arch "$ARCH" "$binary" >/dev/null || { echo "Wrong or missing $ARCH binary: $binary" >&2; exit 1; }
done
HELPER="$PACKAGE_DIST/DiscPorterHelper"
TOOLS="$PACKAGE_DIST/Tools"
[ -x "$HELPER/disc-porter-helper" ] || { echo 'Run script/build_helper.sh first' >&2; exit 1; }
[ -x "$TOOLS/ffmpeg" ] || { echo 'Run packaging/bundle_tools.py first' >&2; exit 1; }
[ -f "$ROOT/assets/build/catalog/Assets.car" ] || { echo 'Run script/build_icon.sh first' >&2; exit 1; }
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Helpers" "$APP/Contents/Resources/ThirdPartyNotices"
cp "$EXE" "$APP/Contents/MacOS/DiscPorter"
"$ROOT/packaging/.venv/bin/python" - "$APP/Contents/MacOS/DiscPorter" <<'PY'
import re,subprocess,sys
path=sys.argv[1]
text=subprocess.check_output(['otool','-l',path],text=True)
for rpath in re.findall(r'cmd LC_RPATH\n.*?path ([^\n]+?) \(offset',text,re.S):
 if rpath.startswith('/') and not rpath.startswith(('/usr/lib/','/System/Library/')):
  subprocess.run(['install_name_tool','-delete_rpath',rpath,path],check=True)
PY
ditto "$HELPER" "$APP/Contents/Helpers/DiscPorterHelper"
# Python source/data belong in Resources, not Apple's reserved nested-code location.
# Keep the one-folder runtime lookup intact through an in-bundle relative symlink.
mv "$APP/Contents/Helpers/DiscPorterHelper/_internal" "$APP/Contents/Resources/DiscPorterRuntime"
ln -s ../../Resources/DiscPorterRuntime "$APP/Contents/Helpers/DiscPorterHelper/_internal"
mv "$APP/Contents/Helpers/DiscPorterHelper/THIRD_PARTY_NOTICES" "$APP/Contents/Resources/ThirdPartyNotices/Python"
ditto "$TOOLS" "$APP/Contents/Tools"
cp "$ROOT/assets/build/catalog/Assets.car" "$APP/Contents/Resources/Assets.car"
cp "$ROOT/assets/build/catalog/DiscPorter.icns" "$APP/Contents/Resources/DiscPorter.icns"
if [ -d "$ROOT/packaging/provenance" ]; then
  "$ROOT/packaging/.venv/bin/python" "$ROOT/packaging/sanitize_provenance.py"
  ditto "$ROOT/packaging/provenance" "$APP/Contents/Resources/ThirdPartyNotices/NativeBuilds"
fi
cp "$ROOT/docs/PACKAGING.md" "$APP/Contents/Resources/ThirdPartyNotices/PACKAGING.md"
"$ROOT/packaging/.venv/bin/python" - "$APP/Contents/Info.plist" "$TOOLS/BINARY_MANIFEST.json" <<'PY'
import json, plistlib,sys
# The local Homebrew build's effective deployment floor is explicit, not inferred from Swift.
rows=json.load(open(sys.argv[2]))['files']
minimum=max(tuple(map(int,x['minimum_macos'].split('.'))) for x in rows if x['minimum_macos']!='unknown')
with open(sys.argv[1],'wb') as f:
 plistlib.dump({'CFBundleExecutable':'DiscPorter','CFBundleIdentifier':'dev.discporter.app','CFBundleName':'Disc Porter','CFBundleDisplayName':'Disc Porter','NSHumanReadableCopyright':'Copyright © 2026 Kian Konrad Tajbakhsh','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.2.0','CFBundleVersion':'5','LSMinimumSystemVersion':'.'.join(map(str,minimum)),'NSPrincipalClass':'NSApplication','NSHighResolutionCapable':True,'CFBundleIconName':'DiscPorter','CFBundleIconFile':'DiscPorter'},f)
PY
xattr -cr "$APP"
# Dependencies are individually signed by their build steps; sign the outer Swift app last.
codesign --force --sign - "$APP"
"$ROOT/packaging/.venv/bin/python" "$ROOT/packaging/verify_bundle.py" "$APP" --architecture "$ARCH" --output "$APP.manifest.json"
# Adjacent manifest inventories sealed bytes without introducing a signature/hash cycle.
codesign --verify --deep --strict "$APP"
echo "Private $ARCH local bundle: $APP"
