# Disc Porter local engine

Python 3.10+; Python 3.12 is used for validation. Standard library only. Start with:

```bash
/opt/homebrew/bin/python3.12 engine/server.py --state-dir "$HOME/Library/Application Support/DiscPorter"
```

The server binds an ephemeral `127.0.0.1` port and writes `endpoint.json` (mode 0600) in a private state directory. Every API request requires its bearer token and the exact loopback Host. Browser Origin requests are rejected. Keep state, tokens, logs and media out of Git.

SQLite WAL with FULL synchronous mode holds settings, exact structural profiles and jobs. A filesystem flock permits one engine owner per state directory. Tool supervisors inherit that ownership descriptor: after a parent crash they terminate owned tools, and the state lock remains held until they exit. On restart incomplete jobs are paused, keeping the last committed checkpoint and all prior candidates. Resume reruns the unfinished phase into a new candidate directory, rather than attempting arbitrary-byte recovery. Original acquisition has per-title intent/commit records; final hardlink promotion is idempotent and never replaces an existing different file.

`scan` is read-only. Independent mount polling can start a saved exact profile only when `auto_start` is enabled; it defaults off. Optical jobs require a current, unambiguous structural fingerprint, exact selected title IDs, and user-supplied content names. Labels, duration and playlist order do not establish official title or episode identity. A structural fingerprint is not a physical pressing serial. MakeMKV drive device nodes resolve to mount paths using diskutil; fresh drive assignment checks precede extraction.

Chosen destination must already exist. Volume UUID/mount and chosen directory identity are checked before every phase, and before output mutation. The UUID permits a normal remount even if the device number changes; a changed directory inode still blocks work for review. Missing removable destinations are never recreated. Every output component is checked for symlink escape. Source identity/content is required through acquisition; committed watchable originals allow encoding after the disc/source is removed.

Acquisition retains all source tracks via an explicit direct-copy MakeMKV profile and compares the acquired stream inventory to the scan. Local media is stream-copy remuxed into MKV. Complete decoded originals appear in `Original_MKV`; no source/original cleanup action exists. Selected English/German primary audio exports as separate AAC tracks at the source channel counts, with English first/default. Every original bitstream and subtitle remains in the MKV. Unknown audio tags block encoding. Supported text subtitles also export as mov_text; bitmap subtitles remain in the original and require reviewed OCR for an MP4 text version.

Video export accepts progressive square-pixel SDR 4:2:0 8/10-bit source. HEVC uses hvc1 and preserves bit depth; H.264 accepts only 8-bit. HDR, special video side data, multiple video streams, interlacing and anamorphic sources block for a reviewed feature-preserving plan. No automatic tone mapping, deinterlacing, joins or episode splitting occurs. These require separately verified content and feature instructions.

Verification compares duration, geometry, frame rate, pixel format, signalled color, audio language/channel/default mappings and subtitle stream count. Full video/audio decode must succeed without warnings. File/ancestor directory fsync precedes committed archive mutations. Original and verified candidate hashes protect resume/promotion. Final MP4 creation uses an atomic same-volume no-clobber hardlink. A retained candidate plus final name refers to the same bytes.

Technical completion preserves `perceptual_acceptance=pending` and `tv_acceptance=pending`. It does not claim observed content identity, subtitle cue/selectability acceptance, QuickTime or TV playback, or perceptually lossless output. Unknown source color tags are reported; originals remain available for that review.

Overall `progress` is the fraction of committed checkpoints (`progress_basis=completed checkpoints`), not an estimated work/byte weighting. `phase_progress` is current tool time fraction (FFmpeg out_time_us/source duration) or MakeMKV PRGV ratio, and is null until measured. It resets for each tool operation. `completed_items/total_items` counts phase title completions. Actual FFmpeg output `total_size` supplies processed bytes and measured output throughput; expected compressed output bytes remain unknown. ETA from elapsed/media-time progress is an estimate. `last_progress_at` advances only on measured time/bytes/PRGV or a committed checkpoint. `heartbeat_at` is separate liveness. After 120 seconds without measured advancement a responsive worker reports a stall reason. None of these physical metrics alone establish successful archive verification.

Safe disconnect means no queued/running job and no active scanner. Request pause after a checkpoint, wait for this state, then use Finder eject. API pause does not eject disks. Shutdown is rejected until safe. Closing the GUI does not shut down this server.

Validation:

```bash
/opt/homebrew/bin/python3.12 -m unittest discover -s tests/engine -v
```

Tests use disposable generated media and fake extraction tools only. They cover real H.264 and Main10 HEVC, audio/subtitles, full decode and corrupt outputs, identity/volume/path guards, pause/resume/recovery, no-overwrite candidates/originals, process-owner crash clearance, measured progress and bearer/Origin/Host controls. Physical disc reads, optical drive interoperability, TV/perceptual acceptance and sudden physical power loss remain untested.

Workflow design was informed by the installed `dvd-digitize-archive` skill and its processing/Blu-ray references and helper scripts. This engine is independently implemented; no copied third-party source or private configuration is included.
