# Disc Porter app icon

Original vector artwork: a silver optical disc above a blue archive tray with a forward arrow. No text, external artwork, embedded fonts or raster source assets are used. Each motif is a separate editable SVG and Icon Composer group.

## Source and generated assets

- `assets/DiscPorter.icon`: editable Icon Composer package; `icon.json` plus three SVG assets.
- `assets/previews`: six committed reference previews; `assets/build/previews` regenerates six verified 1024 px macOS appearances: Default (Light), Dark, TintedLight, TintedDark, ClearLight and ClearDark.
- `assets/build/catalog/Assets.car`: native compiled asset catalog.
- `assets/build/catalog/DiscPorter.icns`: native compiler-generated compatibility icon.
- `assets/build/DiscPorter.icns`: independently generated full-resolution fallback from the Default rendition; includes 16 through 1024 px representations.
- `assets/build/icon-info.plist`: compiler-generated icon bundle keys.

The ClearLight and ClearDark renditions implement the system Clear appearance requested as transparency mode. They are rendered by Apple's compositor; the icon does not impose a custom transparent background or change the user's system appearance. Tinted appearance colors are system-controlled; previews use Apple's default tint.

## Rebuild

Requires macOS, full Xcode 27 selected with `xcode-select`, Icon Composer and Xcode command-line tools. No package installation or account configuration is required.

```bash
./script/build_icon.sh
# Optional separate output directory:
./script/build_icon.sh /path/to/generated-icon-assets
```

The script renders all six renditions with the real `ictool`, builds the fallback with `sips` and `iconutil`, and compiles the editable `.icon` directly with `actool` for macOS 14+. It stops if any native operation fails. It can be rerun after editing the source layers. Generated output is reproducible in structure; timestamps and binary compiler metadata may vary.

Portable schema validation uses the compose-app-icon skill's bundled uv project and `validate_icon.py`. Both schema validation and native render validation are required: the installed native renderer rejected the optional `color-space-for-untagged-svg-colors: srgb` field even though the current schema allowed it. The source omits that field and uses supported fill strings, which passed both checks.

## SwiftPM app bundle integration

SwiftPM produces the executable; the bundle assembly script owns resource copying and `Info.plist` integration. Run the icon build first, then copy the native output to the app's resources:

```bash
cp assets/build/catalog/Assets.car "$APP/Contents/Resources/Assets.car"
cp assets/build/catalog/DiscPorter.icns "$APP/Contents/Resources/DiscPorter.icns"
```

Merge these generated `assets/build/icon-info.plist` values into the bundle's existing `Info.plist`, preserving its unrelated keys:

```xml
<key>CFBundleIconFile</key><string>DiscPorter</string>
<key>CFBundleIconName</key><string>DiscPorter</string>
```

If a deployment environment cannot compile the `.icon`, use the full-resolution `assets/build/DiscPorter.icns` as `Contents/Resources/DiscPorter.icns` with `CFBundleIconFile=DiscPorter`. That fallback is static Default artwork and does not include native appearance selection. Do not substitute a PNG for the asset catalog when native Clear/Tinted appearances are required.

## Validation evidence and limits

Verified with Xcode 27.0 build 27A266a and Icon Composer 27.0 build 129:

- JSON schema validation and referenced-asset checks passed.
- Real `ictool` macOS exports succeeded for all six appearances; every exported image was visually inspected.
- Default 16, 32 and 128 px outputs were visually inspected. The optical disc and tray remain recognizable; the smallest arrow is simplified by raster sampling.
- `iconutil` generated the complete fallback `.icns` successfully.
- `actool` generated `Assets.car`, native compatibility `.icns` and the two bundle icon keys successfully.
- `assetutil --info` parsed the resulting asset catalog as a macOS catalog compiled by Xcode 27.

These checks validate the source and compiled resources. Actual Finder/Dock appearance selection requires the integrated installed app bundle and is owned by the final app validation step. Appearance selection on older macOS versions is limited by that OS's available icon presentation features.
