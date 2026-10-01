#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ICON="$ROOT/assets/DiscPorter.icon"
OUT=${1:-"$ROOT/assets/build"}
ICTOOL="$(dirname "$(xcode-select -p)")/Applications/Icon Composer.app/Contents/Executables/ictool"
[ -x "$ICTOOL" ] || { echo 'Xcode 27 Icon Composer required' >&2; exit 1; }
mkdir -p "$OUT/previews" "$OUT/DiscPorter.iconset" "$OUT/catalog"
for rendition in Default Dark TintedLight TintedDark ClearLight ClearDark; do
  "$ICTOOL" "$ICON" --export-image --output-file "$OUT/previews/$rendition.png" --platform macOS --rendition "$rendition" --width 1024 --height 1024 --scale 1 --design-generation 27
 done
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$OUT/previews/Default.png" --out "$OUT/DiscPorter.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$OUT/previews/Default.png" --out "$OUT/DiscPorter.iconset/icon_${size}x${size}@2x.png" >/dev/null
 done
iconutil -c icns "$OUT/DiscPorter.iconset" -o "$OUT/DiscPorter.icns"
xcrun actool "$ICON" --compile "$OUT/catalog" --platform macosx --minimum-deployment-target 14.0 --app-icon DiscPorter --output-partial-info-plist "$OUT/icon-info.plist" --output-format human-readable-text
