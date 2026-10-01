# Validation record

Date: 02-OCT-2026. Version: 0.1.0 development build. Repository remains private.

## Completed

| Check | Result |
| --- | --- |
| Swift 6 macOS build | Passed on Apple Silicon, macOS deployment target 14 |
| Swift API compatibility | 2 tests passed |
| Engine regression suite | 19 tests passed |
| Official SDK MCP bridge | 9 tests passed |
| Actual engine + MCP + synthetic HEVC pipeline | 1 integration test passed |
| Native app launch | Passed for staged and installed bundles |
| Native UI checkpoint interaction | Synthetic originals checkpoint, next encode checkpoint and resume through completion observed in accessibility state |
| Distinct progress bars | Overall checkpoint count and current subtask measured fraction observed in native UI |
| Local signing/plist | Ad hoc signature strict verification and Info.plist lint passed after removing generated-bundle cloud metadata |
| Installed engine MCP connection | SDK handshake, 13 tools and authenticated status passed; ready state has zero jobs and auto-start off |
| Nested external archive-folder identity | Read-only mounted APFS subdirectory UUID guard passed without reading or changing media |
| Icon Composer | Schema/assets, six native renders, small-size inspection and native catalog compilation passed |
| Codex registration | Active profile reports enabled local stdio server; semantic comparison preserved all unrelated configuration |
| Independent review | Five safety/correctness issues found, fixed and independently retested; no remaining P1/P2 identified in reviewed scope |

The repeatable test command is `./script/test.sh`: **31 automated tests**, all passed after moving to the final repository directory. There are also native UI and icon checks, which are not counted as automated tests.

Engine coverage includes H.264 dual-language audio/text subtitles, HEVC Main10 depth/hvc1, full decode, candidate corruption, original retention, extraction-intent recovery, checkpoint pause/next/resume, concurrent accepted requests, no overwrites, dot/symlink path confinement, source/volume replacement, missing SSD configuration, nested mount lookup, subprocess teardown before owner-lock release, measured progress versus heartbeat, and Host/Origin/bearer authentication. Optical extraction uses a fake tool fixture, not a physical disc.

Integration generates a synthetic film, uses actual MCP calls to stop after each phase, removes the initial input after acquisition, encodes HEVC from the committed original, verifies/promotes the MP4 and reopens durable job state. It demonstrates phase recovery, not arbitrary-byte or frame continuation.

## Pending before public release

- Physical DVD/Blu-ray acquisition and MakeMKV all-track profile interoperability. A read-only hardware scan currently found no usable optical drive.
- Real SSD disconnect/reconnect, sleep/power interruption and filesystem crash durability. Synthetic owner/process/path checks do not establish physical power-loss behavior.
- Correct official episode/cut identity, subtitle cue/selectability, perceptual quality, English/German switching and target-TV playback acceptance.
- Supported plans for ordinary interlaced/anamorphic DVDs, HDR/special video and verified joins/splits. Current engine preserves originals and blocks these exports for review.
- Copy fallback for non-hardlink filesystems and ExFAT export. Current archive workspace requires hardlinks, such as APFS.
- Universal first-time disc identification. Current autonomy is exact saved-profile matching; unknown/ambiguous discs require explicit selection and naming.
- Signed/notarized distribution, bundled-runtime strategy, dependency/license review and release installer. Current bundle uses locally installed Python/FFmpeg/MakeMKV and ad hoc signing.
- Intel and older supported macOS validation; actual system appearance switching for installed icons beyond the six native rendered previews.
- AI-client effectiveness/token savings measurements. Connection/protocol tests are complete; no token-savings percentage is claimed.

Do not make the repository public until the agreed release review. The repository contains generic code/tests/artwork; media, disc labels, tokens, private paths and runtime logs stay outside Git.
