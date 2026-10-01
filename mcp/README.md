# Disc Porter MCP

Local stdio control plane built on the official MCP Python SDK. It talks only to the running Disc Porter engine's authenticated HTTP endpoint. Open the app before invoking tools. The bridge does not start or stop the engine; jobs are processed by the engine without model calls or model tokens. An agent calling this MCP server may separately consume its client's model tokens.

## Setup and tests

Python 3.10+ is required. The Mac's system Python 3.9 is insufficient; setup looks for Homebrew Python 3.13/3.12 when needed. Use `DISC_ARCHIVE_PYTHON` to select another supported interpreter. Dependencies, including transitive dependencies, are pinned in `requirements.txt` (SDK 1.30.0). Installation requires network access; runtime requires no cloud service.

```bash
./mcp/setup.sh
./mcp/.venv/bin/python -m unittest discover -s tests/mcp -v
./mcp/run.sh
```

`run.sh` does not install packages during an MCP handshake and writes diagnostics only to stderr. It resolves paths relative to itself, so the repository can be moved; recreate the virtual environment after moving if its Python launcher fails.

## Connect a client

Copy the absolute launcher path into the client's MCP server configuration. For a Codex TOML configuration, use:

```toml
[mcp_servers.disc_porter]
command = "/ABSOLUTE/PATH/disc-porter/mcp/run.sh"
```

For clients using `mcpServers` JSON:

```json
{"mcpServers":{"disc_porter":{"command":"/ABSOLUTE/PATH/disc-porter/mcp/run.sh"}}}
```

These are templates. No client configuration is edited by setup or this repository. The GUI can show the local absolute launcher path. Avoid putting the endpoint token in client configuration.

The endpoint is `~/Library/Application Support/DiscPorter/endpoint.json`, owned by the signed-in user and mode 0600. Each tool call reloads it so an engine restart is handled without restarting MCP. `DISC_ARCHIVE_ENDPOINT_FILE` overrides its location for isolated tests. Only `http://127.0.0.1:PORT` is accepted, without credentials, extra path, query, redirects or proxy settings. Missing, stale, insecure or unauthenticated endpoints produce actionable MCP tool errors. No requests are automatically retried, because a timed-out mutation might already have been accepted. Check status before repeating it.

## Tools and inputs

Every tool name starts with `disc_porter_`. Inputs are flat JSON objects; extra fields, coercions, invalid enums and duplicate title selections are rejected. Results include compact JSON text and the same structured object. Engine errors use `isError: true`; tokens are redacted from responses. Output schemas are intentionally object-shaped because engine job/report fields evolve; the engine owns detailed verification truth.

| Tool suffix | Inputs | Engine route |
|---|---|---|
| status | none | GET /status |
| scan | none | POST /scan |
| start_job | source_path, collection, kind, titles; optional disc_id, stop_after (default scan) | POST /jobs |
| get_job | job_id | GET /jobs/ID |
| get_report | job_id | GET /report/ID |
| list_profiles | none | GET /profiles |
| save_profile | disc_id, collection, kind, titles | POST /profiles |
| pause_after_checkpoint | job_id | POST /jobs/ID/action |
| next_checkpoint | job_id | POST /jobs/ID/action |
| resume | job_id; optional stop_after | POST /jobs/ID/action |
| cancel | job_id | POST /jobs/ID/action |
| get_settings | none | GET /settings |
| save_settings | output_root, auto_start, video_codec, quality, languages | POST /settings |

Kinds: `film`, `series`, `extras`. Checkpoints: `scan`, `acquire`, `encode`, `verify`, `complete`. Titles: `[{"id":0,"name":"Chosen title"}]`. Settings codecs: `hevc`, `h264`; quality is an integer 0..51; languages use three-letter lowercase codes. Saving settings replaces the settings object. Auto-start can enable acquisition for known saved exact-disc profiles. Confirm the physical disc identity with the user before acquisition. Checkpoints commit complete phases; interrupted extraction/encoding restarts the phase, preserving originals and previous outputs. Pause is deferred to a checkpoint, not immediate. Reports do not establish physical or perceptual TV acceptance.

Read-only annotations apply only to status, job, report, profile list and settings reads. Scan updates discovery state, so it is a mutation. Mutations conservatively declare `destructiveHint=true`, `idempotentHint=false`. All tools are a closed local world. Annotations inform clients; they are not authorization enforcement. No shutdown tool is exposed.

## Verification and references

Tests perform actual official-SDK stdio initialization, tools/list, schema and annotation checks, all 13 HTTP routes, input rejection before any HTTP action, credential rejection/redaction, missing/insecure/remote/stale endpoint cases, JSON errors and endpoint refresh. All data are disposable synthetic fixtures; no real discs or archives are used. `evaluation.xml` contains ten stable read-only fixture questions; the test verifies expected answers deterministically. No language-model evaluation or effectiveness score is claimed.

Implementation references: [official Python SDK](https://github.com/modelcontextprotocol/python-sdk), [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports). Local HTTP routes follow `docs/API.md`.
