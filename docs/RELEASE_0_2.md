# Disc Porter 0.2.0 release status

Created by **Kian Konrad Tajbakhsh**. Original app source is MIT licensed, with third-party components retaining their governing licenses.

## Published and completed

- Public source repository: https://github.com/Kian-hdr/disc-porter
- Latest UI/icon build: 0.2.0 build 5; native Mac target macOS 14+.
- Public-source privacy audit covered eight initial commits and 285 unique blobs. No source-disclosure blocker was found. No personal media, live endpoint, credentials or runtime database is tracked.
- An optimized Apple Silicon release executable was built from source commit `c78b228`, with build-path remapping and debug stripping. Fourteen release-mode Swift tests passed.
- A separate app clone includes creator copyright, native dependency notices and Rust transitive attribution; public provenance excludes local paths and unnecessary bytecode notice caches.
- Native code was signed inside out using Developer ID Application, Hardened Runtime and secure timestamps. Strict deep signature verification passed.
- Matching third-party source inputs, build recipes, notices and content hashes are prepared. See THIRD_PARTY_RELEASE.md for scope and evidence limits.

## Pending public download and Homebrew

The notarization profile recorded for this Mac, `Exlumina-Notary`, was not available. Keychain metadata and standard local Apple API-key locations did not reveal another usable credential. Developer ID signing does not supply authentication to Apple's notarization service. The public binary and personal-tap cask remain pending, rather than providing an unverified installer.

An account owner must complete this one-time credential step locally, without sending passwords or private keys through chat:

```bash
xcrun notarytool store-credentials "DiscPorter-Notary" \
  --apple-id "YOUR_APPLE_ACCOUNT" --team-id "HZWY8HT54D"
```

The command prompts for an Apple app-specific password. Creating or changing authentication credentials is a user-owned step. An existing usable notary profile can be supplied instead.

After that step, submit the prepared ZIP with `notarytool`, wait for Accepted, staple and validate the app, and rebuild the final ZIP. Run Gatekeeper and clean-install checks. Publish the final immutable binary and matching source ZIP/checksums together. Download both published assets and verify byte identity before generating a cask:

```bash
python3 packaging/create_homebrew_cask.py \
  --app "/path/to/stapled/Disc Porter.app" \
  --artifact /path/to/Disc_Porter_0.2.0_arm64.zip \
  --output /path/to/homebrew-tap/Casks/disc-porter.rb
```

The generator requires successful ticket/Gatekeeper checks and hashes the actual public download before writing the cask. Target tap is Kian-hdr/homebrew-tap. Run Homebrew style/audit and clean install/uninstall validation before publishing its cask. Preserve Application Support state and pause processing/disconnect MCP clients before replacements.

This early release targets Apple Silicon only. Physical Intel, macOS 14, optical-disc, SSD interruption and target-player pilots remain pending. Source publication does not change those evidence limits.

## Mac cleanup

Seventeen older Disc Porter app bundles were moved to recoverable Trash. The installed 0.2.0 build 5 app, jobs, settings, media, and recovery-store backups were preserved. Latest-version source/build caches and prepared release materials remain available.
