# Disc Porter 0.2 validation

Date: 02-OCT-2026. Private development build; no public release authorized.

## Completed checks

| Area | Evidence |
| --- | --- |
| Engine | Final whole regression: 44 tests passed. Migration rollback/backup, revisions, accepted preview fingerprints, original mode, per-title checkpoints, stop/disconnect, missing volumes, verified-copy fallback, generations, original-reference protection, cleanup recovery, exports and SDR/stream transforms included. |
| Native UI | 14 Swift tests passed; Apple Silicon build clean. Intel Swift cross-build succeeded. |
| MCP | 43 typed tools; 13 source SDK tests passed. Both frozen helpers and the Intel bundle ran the same SDK tests successfully. Actual engine/MCP status roundtrips passed with minimal PATH. |
| Integration | 2 tests passed: actual engine/SDK HEVC checkpoint pipeline with absent initial input after acquisition, and native AVPlayer subtitle selection/cue delivery before and after MP4 default-flag adjustment. |
| Packaging | Bundled CPython 3.13.15, MCP SDK and FFmpeg/FFprobe. Native dependency/load/signature audits passed for ARM and Intel/Rosetta components; maximum dependency deployment target macOS 14. |
| Codecs | Synthetic software H.264, HEVC 8/10-bit and CoreText/libass burn-in passed on ARM and Intel/Rosetta. ARM hardware H.264/HEVC passed. Intel/Rosetta hardware H.264 passed; HEVC VideoToolbox failed in translation. |
| Icons | Editable Icon Composer artwork, six native renditions and native compiled catalog/fallback produced and inspected. |
| Independent review | Shared-original cleanup, altered verified exports, crash/timeout reader teardown, transfer worker epochs and preview/preset races found and fixed; independent synthetic retests passed. |

There are **73 unique automated cases** across engine (44), Swift (14), MCP (13) and integration (2). Frozen reruns and packaging smoke tests broaden environments rather than adding unique cases. The repeatable source command is `./script/test.sh` after development MCP setup.

## Implementation boundaries

- A single encoder is supported; CPU thread limits are configurable. Capability schemas reject unsupported combinations rather than accepting inactive controls.
- HDR/Dolby Vision transcode and automatic subtitle OCR remain out of scope. Original archive mode preserves unsupported source features.
- Original retention defaults to Keep. Permanent cleanup is opt-in, limited to journaled temporary originals, and requires technical verification plus declared stream preservation. It does not establish perceptual or target-player acceptance.
- Native notifications require authorization and a running native app process. Closing the window keeps the observer alive. Explicit Quit leaves engine completion/history for the next launch.
- Metadata lookup is opt-in; no real TMDb credential or provider request was used in media tests. Keychain mutation tests use mocks.

## Remaining acceptance gates

- Native visual walkthrough, Light/Dark UI, installed icon switching and keyboard/accessibility interaction. Computer Use reported the Mac locked; manual unlock is required to continue these checks.
- Actual notification authorization/delivery, optional TMDb lookup and file selection through the installed UI.
- Physical DVD/Blu-ray drive and MakeMKV interoperability, SSD disconnect/reconnect, sleep/power interruption and target-player/perceptual acceptance.
- Physical Intel and macOS 14 runtime validation. Cross-builds, Mach-O deployment metadata and Rosetta checks are recorded separately.
- Final binary redistribution source-duty review, Developer ID signing, Hardened Runtime, notarization/stapling, Gatekeeper and clean-install release review. Source archives/notices/build provenance are retained; local ad hoc signing does not establish public distribution readiness.

Keep the repository private. Runtime credentials, actual media, disc titles and private logs remain outside Git. See [packaging evidence](PACKAGING.md) and [v2 API contract](API_V2.md).
