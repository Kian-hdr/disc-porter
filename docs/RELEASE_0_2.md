# Disc Porter 0.2.0 preview

Created by **Kian Konrad Tajbakhsh**. Original application source is MIT licensed. Bundled third-party components retain their licenses.

## Install on macOS

Disc Porter 0.2.0 build 5 requires **Apple Silicon and macOS 14 or later**. Install [MakeMKV](https://www.makemkv.com/download/) separately to read discs. Before replacing an existing copy, pause or complete active archiving and quit Disc Porter normally.

- [Download the signed DMG](https://github.com/Kian-hdr/disc-porter/releases/download/v0.2.0/Disc_Porter_0.2.0_arm64.dmg), open it, and drag Disc Porter to Applications.
- With Homebrew, use `brew install --cask kian-hdr/tap/disc-porter`. If Homebrew requires tap trust, run `brew tap kian-hdr/tap` and `brew trust --cask kian-hdr/tap/disc-porter` before retrying the install.

The [preview release](https://github.com/Kian-hdr/disc-porter/releases/tag/v0.2.0) includes SHA-256 files for the DMG and the [matching third-party source packet](https://github.com/Kian-hdr/disc-porter/releases/download/v0.2.0/Disc_Porter_0.2.0_Third_Party_Sources.zip). Keep that packet available alongside the binary. See [third-party release evidence](THIRD_PARTY_RELEASE.md) for component licenses and source correspondence.

## Verification and limits

- The Apple Silicon executable was built from source commit `c78b228`; fourteen release-mode Swift tests passed. The public release contains the original Developer ID signed app, with Hardened Runtime and a secure timestamp.
- Apple accepted app notarization `6747ae86-1a04-4416-9df1-e25090ac6777` and DMG notarization `8ad074b8-db6f-42cd-82a2-e98429296241`. Both stapled tickets validated, and Gatekeeper accepted the DMG and copied app.
- All 66 native file hashes in the third-party source manifest matched the published app. The DMG and source archive were downloaded from the public release and matched their SHA-256 files.
- An isolated launch confirmed API 2 and engine 0.2.0. The test engine shut down after the disconnect fence. Homebrew style, strict audit, checksum-required install into a temporary Applications folder, Gatekeeper, and uninstall passed.
- This is an early preview. Physical optical-disc, SSD interruption, target-player, and macOS 14 runtime pilots remain pending. No Intel artifact is published.
