# Disc Porter third-party release evidence

Original Disc Porter source remains under the repository's MIT license, copyright Kian Konrad Tajbakhsh. Third-party components retain their own licenses. This document describes the inspected 0.2.0 installed ARM bundle and its dependency source packet; it does not certify legal completeness or independent reproduction of upstream binaries.

## Generate and distribute the packet

Use Python 3.11 or later, `otool`, and network access:

```bash
python3.13 packaging/release_sources.py --app "$HOME/Applications/Disc Porter.app" --output "$HOME/Library/Caches/DiscPorter/Release"
```

The script checks pinned codec source hashes, checks CPython against the exact upstream release archive, captures the CPython installer dependency inputs, downloads exact Python source distributions using PyPI SHA-256 records, and captures native Rust dependencies using Cargo.lock checksums. It preserves installed notices, build recipes, configuration evidence, native file hashes/load commands, and FFmpeg configuration. Its packet copies replace local source/home paths and record both original and transformed hashes. It changes neither the app nor its signatures.

Publish the versioned `Disc_Porter_0.2.0_Third_Party_Sources.zip` beside the matching application binary on the same release page, with its `.sha256` file. Give binary recipients a direct link to this packet in the release description. Keep the packet available for the binary's distribution lifetime. Verify the downloaded public packet and binary hashes against the reviewed local artifacts. A public source repository alone does not supply the pinned third-party archives.

## Inspected component matrix

| Component | Shipped form and evidence | License/duty | Packet and remaining evidence limit |
|---|---|---|---|
| FFmpeg 9.0.1 | Separate `Contents/Tools/ffmpeg` and `ffprobe`; observed `--enable-gpl --enable-version3`, static libraries, no `--enable-nonfree` | GPL-3.0-or-later selected build, rather than FFmpeg's optional LGPL-only configuration | Exact FFmpeg source, selected static-library inputs, build scripts, config logs/header and hashes. Displayed source-path metadata transformation is recorded in `build_codecs.sh`. |
| x264 r3222 / x265 4.2 | Statically incorporated in FFmpeg; x264 exact commit in lock | GPL-2.0-or-later, selected together under compatible GPLv3 terms | Exact archives, notices, x264 log and x265 8/10-bit CMake evidence. x264 archive hash is pinned observed evidence, not an independently published upstream checksum. |
| libass 0.17.5 / HarfBuzz 14.5.0 / FreeType 2.14.3 | Statically incorporated in FFmpeg | ISC / permissive notices / dual FreeType or GPLv2 license; retain source copyright and selected applicable terms | Exact source archives and installed subtitle notices/configuration. Full source preserves the dual-license texts. |
| FriBidi 1.0.17 | Statically incorporated in GPLv3 FFmpeg | LGPL-2.1-or-later; compatible GPLv3 redistribution route uses its full corresponding source with combined codec build material | Full FriBidi source and LGPL notices, exact static build recipe. Do not apply the FFmpeg LGPL-only dynamic-link checklist to this GPL codec binary. |
| CPython 3.13.15 | PSF installer interpreter and extension modules; load paths relocated by bundling | PSF combined license plus constituent licenses; preserve notices and modification evidence | Exact CPython source, installer builder, installer manifest, relocation recipes and notices. PSF installer binary reproduction was not run. |
| OpenSSL 3.0.21 / ncurses 6.5 / SQLite 3.50.4 / mpdecimal 4.0.1 / XZ 5.2.3 | CPython installer dependency inputs; libssl/libcrypto/libncurses are observed runtime dylibs, `_lzma` is statically linked | Apache-2.0 / permissive ncurses / public-domain SQLite with included ancillary terms / mpdecimal BSD / XZ mixed source tree terms; inspect exact files, not one archive-wide label | Exact archives match checksums in the matching PSF installer recipe, including its historical MD5 XZ checksum plus packet SHA-256. XZ 5.2.3 COPYING identifies liblzma as public domain; other source tree programs/build scripts have LGPL/GPL notices preserved in the archive. Installer and license records remain in packet. System zlib/bzip2/libffi/framework references are not copied libraries. |
| pydantic_core 2.46.5 / rpds-py 2026.6.3 | Actual native `.so` extensions | MIT top-level; Rust dependency notices include MIT, Apache-2.0/LLVM exception, BSD, Zlib, and Unicode terms | Exact sdists, exact Cargo.lock registry crates, standalone transitive notice copies in `rust-notices/`. Captured crates include conservative build/test/platform dependencies, not a claim every crate is linked. Publisher wheels were not rebuilt. |
| Remaining Python dependencies and MCP SDK | Conservatively captured installed build environment and license files; actual frozen native membership separately inventoried | Preserve individual permissive notices. certifi includes MPL-2.0-covered trust data; provide its source and access notice | Every inventoried exact-version sdist is included. Cryptography and cffi are build-environment records; their native extension binaries were absent from the inspected ARM runtime. No blanket assertion of frozen pure-Python membership. |
| PyInstaller 6.22.3 | Frozen helper bootloader | GPL exception permits generated application bundles under their dependency-compatible licenses; upstream says app license inclusion/acknowledgment is not required | Captured license and sdist included conservatively. No observed PyInstaller source modifications. |
| MakeMKV | Separately installed external dependency | Not redistributed | No MakeMKV binary or source included. |

## Exact publication gates and limitations

1. Attach this matching dependency packet and its checksum to the same release as the binaries, and verify remote downloaded bytes. GPL corresponding source is a distribution requirement, not satisfied by this local generation alone. Preserve all constituent licenses and recipients' rights.
2. Include `rust-notices/` from the packet among the application's accompanying release materials, or copy it into `ThirdPartyNotices` before signing. Top-level pydantic/rpds MIT notices alone do not represent their transitive Rust/Unicode license texts. Keep the source packet linked for certifi's MPL source access.
3. Sanitize local paths in the release clone's configuration logs before final signing. `PUBLIC_PATH_TRANSFORMATIONS.json` records exact packet-copy paths affected. The generator does not alter the installed app. Keep original local evidence private.
4. Validate a newly produced release artifact against packet `MANIFEST.json`. Re-signing changes native binary hashes; regenerate or update reviewed release evidence from the final app, then publish the resulting packet hash. The packet does not establish signing, notarization, Gatekeeper, clean-install, macOS 14, or physical Intel verification.
5. Native wheel/PSF binary correspondence rests on exact version/source-lock/build-recipe evidence, with no independent upstream-wheel/installer reproduction. The two captured crates without standalone license files, `r-efi` and `wit-bindgen-rt`, are excluded from the macOS target by the captured `getrandom`/`wasi` Cargo.toml target chains. Their conservative source inclusion does not establish runtime membership.

The GUI invokes separate tools instead of linking the FFmpeg libraries. Keeping the GUI's MIT license is consistent with that observed separation; whether a specific combined distribution creates further legal obligations depends on the actual integration and applicable law. Codec patents, trademarks and jurisdiction-specific distribution questions are not resolved by source-license checks.

## Primary sources checked 02-OCT-2026

- [FFmpeg licensing and legal page](https://ffmpeg.org/legal.html), read alongside captured FFmpeg GPLv3 and library license files.
- [PyInstaller license and bootloader exception](https://pyinstaller.org/en/stable/license.html).
- [Mozilla Public License 2.0](https://www.mozilla.org/en-US/MPL/2.0/), especially source access for executable distribution.
- [pydantic-core 2.46.5 distributed artifacts](https://pypi.org/project/pydantic_core/2.46.5/) and [rpds-py 2026.6.3 artifacts](https://pypi.org/project/rpds-py/2026.6.3/); every downloaded source/crate URL and checksum is preserved in packet `MANIFEST.json`.
- The exact CPython `Mac/BuildScript/build-installer.py` and all captured component license texts are preserved unabridged inside source archives and notices. These source artifacts take precedence over registry labels or this matrix.
