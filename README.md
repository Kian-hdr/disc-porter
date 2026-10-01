# Disc Porter

A native macOS app for local DVD and Blu-ray archiving, durable checkpoints and optional MCP control. The processing engine runs without AI models or token consumption. An AI client using MCP still uses its own model tokens.

**Private development build.** Real optical acquisition, target-player acceptance and release packaging require validation before public publication. This repository is the canonical technical documentation; private runtime records stay outside it.

## Workflow

1. Choose an existing archive folder on your SSD in Settings.
2. Insert a disc. Scan its structure and title list.
3. For an unfamiliar disc, confirm the collection, selected title IDs and file names. Disc labels and durations alone cannot reliably identify official episodes or cuts.
4. Save its fingerprint profile. Enable automatic starts in Settings for subsequent known discs.
5. Start the archive, or choose the checkpoint to reach before stopping.
6. Use **Prepare to disconnect**. Wait until no archive writes are in progress, then eject the SSD in Finder before unplugging it.

Originals remain available in `Original_MKV/`. Each successful job produces verified MP4s. Alternate mixes and bitmap subtitles remain in the originals. English and German primary audio are selected when present; source channel count is checked. Unsupported HDR, interlaced/anamorphic video and ambiguous audio pause for review rather than silently converting features.

## Checkpoints

| Checkpoint | Durable result |
| --- | --- |
| Disc identified | Exact selection, source identity and destination recorded |
| Originals saved | Complete title MKVs extracted or local video remuxed and decoded |
| MP4s encoded | New MP4 candidates created without replacing existing files |
| Files checked | Source/output metadata, audio mapping, duration and full decode checked |
| All automatic steps | Verified candidates promoted without overwriting; originals retained |

**Stop after the next checkpoint** finishes the current phase. **Work to next checkpoint** advances one phase. An interrupted extraction or encoding restarts the unfinished phase in a new candidate; completed phases remain saved. This is phase-level recovery, not arbitrary-frame continuation.

Global disconnect status includes engine jobs and active scanning. Other applications may still be using a drive: use normal macOS eject. Physical playback, correct cut/episode content, perceptual quality and subtitle selectability are separate acceptance checks visible as pending in reports.

## Development setup

Requires macOS 14+, Xcode 27/Swift 6 for development and native icon compilation, Python 3.10+, FFmpeg/FFprobe and a separately installed MakeMKV for optical extraction. Development is currently tested on Apple Silicon. Third-party tools are not redistributed or relicensed by this project. Archive destinations currently require hardlink support, such as APFS; ExFAT export is a separate future feature.

```bash
brew install python@3.12 ffmpeg
./mcp/setup.sh
./script/build_and_run.sh --verify
```

Get MakeMKV from its [official download page](https://www.makemkv.com/download/). Its own license and capable optical hardware remain required. Encoding uses FFmpeg software encoders; a local engine supervises external tools and owns job state independently of the GUI.

The generated app is `dist/Disc Porter.app`. The Codex Run action uses the same build/run script. `--build-only`, `--logs`, `--debug` and `--telemetry` are available. These bundles are development builds, without distribution signing or notarization.

## MCP

[MCP setup, tools and client configuration](mcp/README.md). The bridge exposes compact job operations over stdio to the same authenticated local engine. Connect a client once; no cloud service or model is required by the pipeline. MCP cannot automatically register itself in every AI service.

## Tests and evidence

```bash
./script/test.sh
./script/build_and_run.sh --verify
```

Synthetic fixtures exercise recovery and encoding. They do not establish physical disc compatibility. [Validation record](docs/VALIDATION.md), [architecture](docs/ARCHITECTURE.md), [API contract](docs/API.md).

The editable [Icon Composer source and six appearance previews](docs/ICON.md) are included. SwiftPM build/test caches stay in the user's Library/Caches folder, avoiding cloud-file metadata in signed test bundles.

## Attribution

The workflow is informed by Kian's [DVD Digitize & Archive](https://github.com/Kian-hdr/dvd-digitize-archive) skill. This application implements a persistent engine and native UI; it does not bundle private media or collection records. MCP uses the [official Python SDK](https://github.com/modelcontextprotocol/python-sdk).
