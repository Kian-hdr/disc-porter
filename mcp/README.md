# Disc Porter MCP 0.2

The official-SDK local stdio bridge exposes 43 typed tools to the same authenticated engine used by the UI. The installed app contains its runtime and bridge; no Python, Homebrew or repository checkout is required. It can start/reconnect its processing engine without the GUI. Processing makes no model calls; an AI client's calls separately consume its own model tokens.

## Connect the installed app

Codex configuration (use the actual installed app path):

```toml
[mcp_servers.disc_porter]
command = "/Applications/Disc Porter.app/Contents/Helpers/DiscPorterHelper/disc-porter-helper"
args = ["mcp"]
```

JSON clients:

```json
{"mcpServers":{"disc_porter":{"command":"/Applications/Disc Porter.app/Contents/Helpers/DiscPorterHelper/disc-porter-helper","args":["mcp"]}}}
```

The GUI exports the correct path for its own installation. Reopen the client/new chat after registration. API keys and the private bearer endpoint never belong in client configuration. The development `mcp/run.sh` prefers an installed helper; `DISC_PORTER_DEV_MCP=1` selects source mode.

## Development and tests

```bash
./mcp/setup.sh
./script/test.sh
DISC_PORTER_DEV_MCP=1 ./mcp/run.sh
```

The source SDK environment is in the user's local Library/Caches folder; source bytecode also stays there to avoid provider-backed import stalls. `DISC_PORTER_MCP_ENV` can select another development environment. Test endpoints use `DISC_ARCHIVE_ENDPOINT_FILE` and never auto-start production state. Runtime stderr is diagnostic; stdout is MCP only.

## Operations

Legacy status/scan/start/job/report/profile/checkpoint/settings tool names remain. Added capabilities, immutable/custom presets, revision-checked settings/profile/job edits, accepted-plan preview, atomic queue controls, stop/retry/reprocess, acceptance, asynchronous scans, local/opt-in metadata, Keychain credential status/configuration, cleanup preview/execution, library, verified exports and bounded audit.

Recipes expose video/container/encoder/quality, CPU limits, audio selection/defaults, subtitle selection/default/forced flags, folders/templates, reserve space, automation and retention. Capability schemas declare actual supported values and limits. V2 mutations check engine/API version before delivery; an old engine cannot silently ignore an original-mode or custom-recipe request.

Create jobs with a stable `idempotency_key`; reuse it after ambiguous timeouts. Preview first and pass `expected_plan_fingerprint` with `expected_settings_revision` to preserve the accepted recipe across independent preset/profile edits. Resource patches require `expected_revision`. Conflicts return actionable errors. Requests are not automatically retried after read timeouts.

Cleanup is permanent only under enabled delete_verified policy and validated ownership/technical gates. Imported sources, final original deliverables and foreign-job original references remain protected. Reports separate technical validation, retention and manually supplied playback/quality acceptance. Never fabricate acceptance observations.

## Local boundary and evidence

Transport is stdio plus loopback bearer HTTP. Endpoint must be owned by this user, mode0600 and not a symlink. Only 127.0.0.1 HTTP is accepted; proxies/redirects/remote endpoints are rejected. Browser Origin is rejected by the engine. Tokens and metadata credentials are redacted from outputs. Audit labels are attribution, not authenticated human identity proof.

13 bridge tests exercise the actual SDK transport, all 43 routes/schema categories, strict input rejection, credentials/redaction, version gates and errors. Frozen ARM/Intel helpers ran the same tests; real backend/MCP roundtrips and media integration are recorded in [0.2 validation](../docs/VALIDATION_0_2.md). Tests use generated fixtures and never write production Keychain credentials.

[API contract](../docs/API_V2.md) · [official SDK](https://github.com/modelcontextprotocol/python-sdk) · [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
