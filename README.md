# Disc Porter

A native macOS app for local DVD/Blu-ray archiving with configurable recipes, durable title checkpoints and complete local MCP control. Processing uses no AI model or model tokens. An AI client using MCP separately consumes its client's tokens.

Created by **Kian Konrad Tajbakhsh**.

Version 0.2.0 is an early release. Code, tests, setup and validation live here. Media, credentials and private runtime logs stay outside Git. Real-disc, disconnect/reconnect and target-player pilots remain pending; see the validation evidence before relying on unattended processing.

## Installation status

The source repository is public. The 0.2.0 build 5 download is prepared as a draft; Apple notarization and Homebrew cask publication are pending credential setup. See [release status and the one-time Apple setup](docs/RELEASE_0_2.md). A Homebrew installation command will be added after its actual install path is verified.

## One window, five destinations

- **Discs:** discover media, confirm identification, select titles/streams, preview the effective recipe and destination.
- **Queue:** measured progress, title checkpoints, pause/next/resume/stop-now, retry and ordering.
- **Library:** verified outputs, retained/removed originals, review records, previews, exports and cleanup eligibility.
- **Profiles:** immutable builtins, editable duplicates and exact-disc mappings.
- **Settings:** searchable storage/video/audio/subtitle/automation/AI/tool controls. Toolbar, app menu and Command-comma open the same window.

Unknown discs receive suggestions and require confirmed mapping. Labels, durations and playlists alone do not prove official episode or cut identity. Optional TMDb lookup is off by default and keeps credentials in Keychain.

## Presets and checkpoints

Balanced uses HEVC CRF20/medium; Compatibility uses H.264 and requires explicit approval before reducing source bit depth; Original archive preserves original MKVs; Legacy retains existing English/German CRF18 settings. New-user recipes support all source languages, exact track/default/forced choices and SDR deinterlacing/aspect transforms. HDR/Dolby Vision transcode and automatic OCR are outside this version; original mode preserves those sources.

Each completed title operation is committed. Pause stops at a title boundary; Stop now stops only owned work and restarts its unfinished operation into a fresh candidate. Checkpoint edits preview their impact and retain older generations. Accepted preview fingerprints and revision checks prevent concurrent AI/UI changes from silently replacing the approved recipe.

**Prepare to disconnect** fences new work and waits for owned writers/readers/scans/transfers to exit. Other applications may still use the drive: eject it normally in Finder. Source/volume guards reject missing or replaced destinations. APFS hardlinks are an optimization; verified-copy fallback and per-file exports support other filesystems.

Originals default to **Keep**. Optional **permanent** cleanup deletes only journaled app-created temporary originals after verified final publication and required original-stream sidecars. Imported sources, final original-archive deliverables and originals referenced by other jobs remain protected. Technical validation does not prove perceptual quality or target-player playback; reports keep those states separate.

## Self-contained runtime

The app bundles CPython, its MCP bridge, FFmpeg/FFprobe and required libraries. Runtime needs no Homebrew, developer Python or repository checkout. MakeMKV and a capable optical drive remain external dependencies; use its [official download](https://www.makemkv.com/download/) and its own license.

The target is macOS14+. Apple Silicon and Intel artifacts are separate; Intel/Rosetta and Mach-O deployment checks are not physical Intel/macOS14 acceptance. Native dependency notices, sources and build provenance are retained. Developer ID/notarized distribution remains separate from private ad hoc builds.

## Development

Build requires Xcode27/Swift6 plus the documented pinned native build tools. Runtimes/build caches stay outside provider-backed output where possible. A first build fetches approved source dependencies and can take longer than subsequent cached builds.

```bash
./mcp/setup.sh
./script/build_and_run.sh --build-only
./script/test.sh
```

The build/run script assembles a fresh app under the local Library/Caches folder and refuses unsafe engine replacement. The Codex Run action uses that same script. `--verify`, `--debug`, `--logs` and `--telemetry` are available.

[Packaging instructions](docs/PACKAGING.md) · [v2 API](docs/API_V2.md) · [0.2 validation](docs/VALIDATION_0_2.md) · [Icon Composer source/appearances](docs/ICON.md)

## MCP and notifications

The bundled helper exposes **43 typed tools**, including settings/presets, job preview/edit, queue fencing, track choices, acceptance, library, export and scoped cleanup. It can start/reconnect the local engine without the GUI. See [MCP client setup](mcp/README.md). V2 controls reject incompatible older engines rather than silently ignoring their parameters.

Native notifications request OS authorization only from an explicit in-app button. Closing the window keeps the app observer alive; explicit Quit leaves only engine history for the next launch.

## Attribution and publication

Workflow informed by [DVD Digitize & Archive](https://github.com/Kian-hdr/dvd-digitize-archive). The original app source license remains MIT; bundled third-party components retain their own licenses and source duties. MCP uses the [official Python SDK](https://github.com/modelcontextprotocol/python-sdk). No private media or collection records are included. Source publication is authorized. Binary distribution and Homebrew availability are recorded separately in the release documentation.
