# Disc Porter 0.2 local bundle

The app carries its own CPython engine, MCP SDK and FFmpeg/ffprobe. MakeMKV remains a separately installed external application. User settings and jobs live outside the app in Application Support. The bundle has no developer-source-root key and requires no user Python installation or Homebrew installation at runtime.

## Build and assembly

Builds require Xcode command-line tools, CMake, curl, tar, make and an internet connection for pinned build dependencies. The Python Software Foundation macOS installer is downloaded, signature-checked and **privately extracted**. No installer/postinstall scripts, system Python installation, shell-profile changes or user account changes run. A private virtual environment and PyInstaller 6.22.3 produce a one-folder helper. All package versions are pinned in `packaging/requirements-build.txt`; cryptography 46.0.5 is the SDK-compatible universal2 wheel pin used for both CPU architectures.

```bash
python3 packaging/prepare_python.py
./script/build_helper.sh
python3 packaging/fetch_sources.py
./packaging/build_codecs.sh
./script/build_icon.sh
./script/package_app.sh /path/to/NEW/Disc\ Porter.app /path/to/SwiftExecutable
```

Assembly refuses an existing destination. Use a local, non-file-provider output directory such as the app's private build cache. On the tested provider-backed Documents checkout, the provider automatically attached FinderInfo to `.app` roots and invalidated signatures; a source checkout can retain ZIP/checksum artifacts while signing and live app execution use a local path. Build/run wrappers must verify that no active engine or owned tool is executing from the bundle before replacing it. Close the GUI only after the engine's explicit checkpoint pause or disconnect fence is safe; never kill an engine to make a build convenient. Use a fresh staging path and atomic replacement after that check.

An Intel build uses a separate private environment, target and output directory:

```bash
DISC_PORTER_ARCH=x86_64 ./script/build_helper.sh "$PWD/packaging/dist-x86"
DISC_PORTER_ARCH=x86_64 DISC_PORTER_TOOLS_OUTPUT="$PWD/packaging/dist-x86/Tools" ./packaging/build_codecs.sh
```

The packaging script supports `DISC_PORTER_ARCH=arm64` (default) and `DISC_PORTER_ARCH=x86_64`, selects matching helper/tools, and rejects a mismatched Swift executable or native dependency before assembly. CPU variants are separate artifacts. The Intel app was assembled from the cross-built x86_64 Swift executable and verified independently under Rosetta; it is not an asserted universal app. Intel codec builds disable optional assembler optimizations to avoid requiring a separately installed NASM build tool. Intel runtime checks under Rosetta establish translated execution on this Mac; they do not establish physical Intel hardware or macOS 14 runtime coverage.

## Runtime layout and dispatch

```text
Disc Porter.app/Contents/
  MacOS/DiscPorter
  Helpers/DiscPorterHelper/disc-porter-helper
  Helpers/DiscPorterHelper/_internal -> ../../Resources/DiscPorterRuntime
  Resources/DiscPorterRuntime/...
  Tools/ffmpeg
  Tools/ffprobe
  Resources/Assets.car
  Resources/DiscPorter.icns
  Resources/ThirdPartyNotices/...
```

The helper dispatches `serve --state-dir PATH`, `supervise PARENT_PID -- TOOL ARGS`, or `mcp`. A frozen executable launches its supervisor role directly; it does not pass `runner.py` to `sys.executable`. The supervisor holds inherited ownership descriptors until its owned tool/process group drains. Bundled startup sets `DISC_PORTER_BUNDLE_TOOLS` and `DISC_PORTER_TOOLS_DIR` to `Contents/Tools`. Valid explicit tool overrides take priority, then bundled tools, then development discovery. The GUI and stdio launcher share the authenticated state owner and queue policy.

Python data and interpreter internals live in Resources, with a relative `_internal` symlink beside the helper. This preserves PyInstaller lookup while respecting Apple's reserved nested-code directory rules. The helper executable retains the required `Contents/Helpers/DiscPorterHelper/disc-porter-helper` path.

The packaging-safe `disc_porter_control` Python package avoids confusing the project's bridge files with the official `mcp` package. The PyInstaller spec explicitly includes the SDK's dynamic modules and excludes its optional CLI. Runtime processing contains no model calls or model token consumption.

## FFmpeg builds and provenance

The selected bundled source builds are FFmpeg 9.0.1, x264 r3222 at recorded commit `b35605ace3ddf7c1a5d67a2eb553f034aef41d55`, and x265 4.2 with 8- and 10-bit support. Required software encoders `libx264`/`libx265` and hardware encoders `h264_videotoolbox`/`hevc_videotoolbox` are checked after building. Built-in FFmpeg codecs, demuxers, muxers and filters remain enabled. Networking and automatic third-party library discovery are disabled; separate Homebrew codec libraries and OpenSSL are not linked. Static libass 0.17.5 supplies text burn-in with CoreText, Freetype 2.14.3, HarfBuzz 14.5.0 and FriBidi 1.0.17; Fontconfig is not required.

Each native build sets a macOS 14 deployment target. The earlier inspected Homebrew FFmpeg closure required macOS 26/27 and is **not the selected bundled runtime**. Source-build outputs link only macOS system libraries and frameworks. Tool manifests record architecture, measured Mach-O minimum, input/output hashes and dependency names. The builder can also relocate a Homebrew dependency closure for investigation, but that route is not the accepted macOS 14 build.

`packaging/SOURCES.json` locks the exact selected codec archives; `fetch_sources.py` rejects mismatching downloads. FFmpeg and x265 hashes were matched to inspected installed recipes. The x264 official exact-commit archive and build-only pkgconf archive are pinned by observed SHA-256; those two archive hashes were not independently compared to a published upstream checksum. Sources are kept in the ignored `packaging/sources/` directory for a separate corresponding-source packet. Source archives are not embedded into the app by default. Build recipes are in `packaging/build_codecs.sh`; generated compiler configuration evidence is in `packaging/provenance/source-built-codecs-*`. FFmpeg's displayed build configuration replaces the private source root with a literal placeholder. This changes displayed metadata only; the exact compiler flags and corresponding header transformation are recorded in the build recipe.

## Licensing and release status

This is a private development artifact, with ad-hoc local signatures. It is not a notarized public release or an App Store submission packet. The app's governing source license is unchanged.

| Component | Evidence and distribution duty |
|---|---|
| FFmpeg with GPL/version3 flags | GPL-3.0-or-later build; preserve GPL notices and provide complete matching corresponding source/build material through a valid distribution mechanism. |
| x264 and x265 | Inspected GPL-2.0-or-later source notices; copied static code is included in the GPL-enabled FFmpeg binary. |
| Subtitle rendering libraries | Captured libass ISC, HarfBuzz permissive, Freetype license/dual-license notices and FriBidi LGPL source notices; preserve applicable static-link redistribution/relinking/source obligations within the matching GPL-enabled codec packet. |
| CPython 3.13.15 | Python Software Foundation signed macOS installer, captured combined license text and exact installer hash; interpreter and bundled native dependency source/build provenance needs final review. |
| MCP SDK and Python dependencies | Installed license texts and exact metadata captured in helper `THIRD_PARTY_NOTICES`; frozen binary/module inventories establish actual shipped scope. Native wheel source and notice completeness remain review items. |
| PyInstaller bootloader | Its installed license/exception must accompany the embedded bootloader; preserve captured license text. Build-only dependencies are conservatively inventoried, rather than claimed to be runtime imports. |
| Icon | Original editable SVG layers and native Icon Composer package; no external image/font assets. |
| MakeMKV | External dependency, not copied into the app or covered by this source packet. |

Local evidence does not establish every legal distribution obligation. Before public distribution, complete the actual matching-source packet for all shipped native components and Python wheels, verify notices/modification duties and the chosen distribution mechanism, and review patent or channel questions where relevant. No blanket redistribution-compliance claim is made. Records from the initial Homebrew investigation are retained as historical evidence, clearly distinct from selected source-built tools.

Developer ID signing, Hardened Runtime/entitlement review, secure timestamps, notarization, stapling, Gatekeeper and clean-install testing are separate release gates. None is implied by an ad-hoc signature or successful local build. Package signing must proceed inside out; never use a deep-sign shortcut as a substitute for explicit nested-code signing.

## Validation

`packaging/verify_bundle.py` inventories resource hashes, validates every arm64 Mach-O load dependency against bundle/system locations, rejects non-system absolute rpaths, checks code signatures and computes the maximum native deployment target. `package_app.sh` seals final bytes, verifies the outer bundle and writes an adjacent `.app.manifest.json` inventory. Keeping the inventory outside the sealed app avoids a circular signature/hash dependency. The helper and tool tests use disposable synthetic fixtures only. Current local results and remaining platform coverage are recorded by the final integration handoff; no real disc acquisition is a packaging check.

Primary references: [PyInstaller one-folder operation](https://pyinstaller.org/en/stable/operating-mode.html), [PyInstaller spec files](https://pyinstaller.org/en/stable/spec-files.html), [FFmpeg licensing](https://ffmpeg.org/legal.html), [Python downloads](https://www.python.org/downloads/macos/), [Apple Developer ID](https://developer.apple.com/support/developer-id/).

Observed local runtime checks: ARM frozen SDK handshake, tools/list, status against authenticated fake HTTP, frozen supervisor dispatch, software H264/HEVC 8/10-bit, CoreText text burn with measured pixel change, and hardware H264/HEVC encodes passed. Intel/Rosetta passed the same checks except hardware HEVC, which was rejected by VideoToolbox in the translated environment. No physical Intel or macOS 14 machine was tested. Both codec binaries measure a macOS 14 Mach-O minimum; this establishes deployment metadata, not full OS runtime coverage. See `packaging/provenance/SMOKE_*.json` and binary manifests.

Final helper source-cut fingerprint: `81040e3da5f13b34ff7027154c7514755e9a940174364259f137c4b5b95dd762`. Both architectures passed the root 13-test MCP contract suite through the actual frozen executable with all 43 tools, including schema/input checks, manual/default/forced stream preservation and API-version rejection before mutation. Records are in `packaging/provenance/FROZEN_MCP_FINAL_*.json`; the portable per-file source hashes are in `SOURCE_CUT_FINAL.json`.

Both final helpers also started a real owned engine with disposable state, returned API 2 / engine 0.2.0 capabilities, and completed the actual engine-to-frozen-MCP 43-tool status roundtrip with a minimal PATH. Automation stayed disabled and cleanup stayed Keep; the disconnect fence became safe and the owned test engine shut down cleanly. Intel bundled execution used Rosetta without launching the GUI or installing the app. See `FROZEN_ENGINE_FINAL_arm64.json` and `FROZEN_ENGINE_BUNDLED_FINAL_x86_64.json`.

The frozen helper supplies the already-bundled certifi trust roots through `SSL_CERT_FILE` only when no explicit override exists. This repairs the privately extracted PSF interpreter's absent system-install certificate path. `selftest-ssl` checks positive loaded CA count, `CERT_REQUIRED`, hostname checking and preservation of an explicit CA-file override without a network request or credential.

The final TLS repair passed on both helper architectures: 121 CA certificates loaded, certificate and hostname verification enabled, and explicit CA-file overrides preserved. Both rebuilt helpers retained the 43-tool interface and passed the existing 13-test MCP suite plus the actual owned engine/MCP roundtrip and clean shutdown checks. No codec tests were repeated because codec bytes were unchanged. Final source and executable digests are recorded in `FINAL_HELPER_DIGESTS.json`; `TLS_FINAL_*.json` records the trust checks.

Homebrew receipt path strings in public provenance copies are sanitized to `<LOCAL_HOME>`. Original receipts remain in the ignored private build cache; `RECEIPT_SANITIZATION.json` records original/derived hashes and the precise transformation. Source checksums, package versions and license texts are preserved. Assembly runs this sanitation before copying provenance into an app.
