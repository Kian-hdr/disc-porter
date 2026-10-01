# Architecture and implementation decisions

## Ownership

SwiftUI owns app-wide observed connection/job state and window-local selection. A separate Settings scene edits preferences through the engine. AppKit is limited to folder/file panels, Finder reveal, clipboard and quit choices.

Python owns the durable SQLite ledger and all media operations. One engine holds an exclusive state-owner lock. A single pipeline worker prevents competing optical reads or shared-record writes. GUI/MCP clients submit controls, never execute independent media commands. Jobs continue if the GUI closes; a safe pause is explicit.

State lives in the signed-in user's Application Support/DiscPorter folder. The endpoint bearer token is local, file mode 0600, excluded from logs and repository. HTTP binds only 127.0.0.1, checks Host and rejects browser Origin. MCP uses stdio and re-reads the endpoint after engine restarts.

## Identity and recovery

Disc control-file hashes form a structural identity. Saved mappings bind selected title IDs to collection/name/kind. This is a content-structure match, not proof of physical pressing, official title identity or perceptual correctness. Unknown or ambiguous discs need review.

Destination and source identity guards reject missing/replaced volumes. No fallback folder is silently created under an absent /Volumes path. Completed phases commit to SQLite; originals and candidates are non-overwriting. Retry creates a fresh attempt folder. Promotion verifies hashes and uses atomic no-clobber links. Ordinary processing never removes originals.

Recovery must account for supervised tool children before claiming disconnect safety. Technical checks are distinct from manual content, subtitle and player acceptance. Logs are private on-disk evidence; UI/MCP summaries remain small.

## Progress

Overall progress counts committed checkpoints, explicitly labelled; it is not an elapsed-time prediction. Current-phase progress uses measured FFmpeg or MakeMKV events when available. Unknown totals are indeterminate. Throughput/ETA require actual measurements and are estimates. Worker heartbeat and last processing advancement are separate. Pause requests and next checkpoint remain visible.

## Guidance selection

Selected installed OpenAI Build macOS Apps guidance for native scenes, Settings, panels, SwiftPM bundle staging and the Codex Run action. Its macOS scope fits this utility better than simulator-first workflows. Installed SwiftUI Expert and Swift Concurrency guidance inform state ownership and compile-time isolation. Installed MCP Builder matches its [original Anthropic source](https://github.com/anthropics/skills/tree/main/skills/mcp-builder); official SDK/specification are authoritative for transport and schemas.

Reviewed [Automatic Ripping Machine](https://github.com/automatic-ripping-machine/automatic-ripping-machine) as a workflow comparison. It is not adopted as this native app's dependency: its operating/runtime model differs from a SwiftUI Mac utility. Existing skill guidance plus official command-line documentation gives a direct path; no extra downloaded skill was required.

Primary sources: [MakeMKV automation](https://www.makemkv.com/developers/), [HandBrake CLI reference](https://handbrake.fr/docs/en/latest/cli/command-line-reference.html) as ecosystem comparison, [Apple NavigationSplitView](https://developer.apple.com/documentation/swiftui/navigationsplitview), [MCP SDK](https://github.com/modelcontextprotocol/python-sdk). Dependency packaging and physical-disc acceptance remain separate validation gates.
