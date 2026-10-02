# Native workspace refinement, 2026-10-02

Local app version 0.2.0 build 4 retains the approved Icon Composer artwork and the existing engine/MCP API.

## Changes

The old Profiles and empty Queue splits collapsed toward the bottom of the main window. Explicit full-height sizing now makes these surfaces use the available workspace.

Profiles uses a native source list, automatic initial selection, searchable names, a focused detail header and segmented recipe categories. Built-in presets show readable values; duplication uses an attached name-entry sheet and selects the resulting editable preset. Custom presets have Revert/Save actions. Saved-disc mapping actions remain visible in a pinned footer. Successful saves reload their own revision instead of presenting a false external-edit conflict. External revision conflicts still require explicit reload. Profile selection persists within the scene.

Queue uses a native four-column table above a vertically resizable job detail area. Search, All/In progress/Finished filters, checkpoint progress, state symbols and bounded reorder actions make jobs easier to scan. An empty queue has one centered explanation and a Go to Discs action. Existing checkpoint, report and processing controls retain their engine policies.

The shared status strip is compact and pinned to the bottom. Settings and Library also explicitly fill their available workspace. Recipe fields use readable codec/container capitalization and named numeric accessibility labels without duplicate visible labels.

## Evidence

- Swift build and all 14 existing Swift tests passed after the final source edits.
- The assembled arm64 app passed 655-file bundle verification and strict deep signature verification with a macOS 14 deployment floor.
- Native screenshots confirmed the corrected Profiles and empty Queue layout in the installed app.
- An isolated test state confirmed preset duplication, automatic selection, editable controls, successful name save and cleared dirty/revision state. Profiles was inspected in Light and Dark appearances; saved-disc content was inspected in Light. Test state never used user media or user job records; its backend had no processing worker.
- Inspection of a populated Queue repeatedly crashed the Computer Use inspection service with an assertion in Array.remove(at:). Disc Porter continued running without an app crash report. Populated Queue visual/accessibility traversal, resizing and keyboard-only walkthrough therefore remain unverified. No fallback screenshot/control tool bypass was used.
- The final pinned saved-disc footer compiles; its final native visual walkthrough remains pending.

Physical disc, playback, storage interruption and release validation retain their existing gates in VALIDATION_0_2.md. This change is private local UI work, not a public release.
