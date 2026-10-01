# Disc Archive

Personal macOS disc archive app. Keep repository private until Kian authorizes publication after validation. Do not acquire from physical discs during development without confirming disc identity with Kian. Do not change existing media collections. Never delete originals automatically. Keep real disc labels, titles, logs, local paths and credentials out of committed fixtures.

Use Build macOS Apps plugin for native UI/build work and mcp-builder for MCP. One owner per file. Tests use disposable synthetic media and temporary state. Checkpoints mean completed durable phases; an interrupted extraction/encode restarts that phase to a new candidate, not arbitrary-byte resume. Preserve previous outputs. Use exact disc identity and destination volume checks, fail closed on ambiguous content. No cloud AI dependencies in runtime.

Primary owns Swift sources, Package.swift, run script and root documentation. Engine agent owns engine/ and tests/engine/. MCP agent owns mcp/ and tests/mcp/.
