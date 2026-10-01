#!/usr/bin/env python3
"""Disc Porter MCP control plane. No acquisition, encoding or model calls here."""
from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Phase = Literal['scan', 'acquire', 'encode', 'verify', 'complete']
Kind = Literal['film', 'series', 'extras']
Name = Annotated[str, Field(min_length=1, max_length=240)]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)

class Empty(Input):
    pass

class JobID(Input):
    job_id: Identifier = Field(description='Job ID returned by the engine.')

class Title(Input):
    id: Annotated[int, Field(ge=0)]
    name: Name

class Selection(Input):
    collection: Name
    kind: Kind
    titles: Annotated[list[Title], Field(min_length=1, max_length=100)]

    @model_validator(mode='after')
    def unique_titles(self):
        if len({t.id for t in self.titles}) != len(self.titles):
            raise ValueError('Select each title ID only once.')
        return self

class StartJob(Selection):
    source_path: Annotated[str, Field(min_length=1, max_length=4096)]
    disc_id: str | None = Field(default=None, min_length=1, max_length=256)
    stop_after: Phase = 'scan'

class Profile(Selection):
    disc_id: Annotated[str, Field(min_length=1, max_length=256)]

class Resume(JobID):
    stop_after: Phase | None = None

class Settings(Input):
    output_root: Annotated[str, Field(max_length=4096)]
    auto_start: bool
    video_codec: Literal['hevc', 'h264']
    quality: Annotated[int, Field(ge=0, le=51)]
    languages: Annotated[list[Annotated[str, Field(pattern=r'^[a-z]{3}$')]], Field(min_length=1, max_length=20)]

# method, route, input, read-only, description, fixed action
SPECS = {
    'disc_porter_status': ('GET', '/status', Empty, True, 'Read engine settings, jobs, discs, tool availability and safe disconnect state.', None),
    'disc_porter_scan': ('POST', '/scan', Empty, False, 'Scan local sources. May update identification state; never starts extraction by itself.', None),
    'disc_porter_start_job': ('POST', '/jobs', StartJob, False, 'Create a local archive job from an exact identified disc or media file. Default stops after scan. Acquisition requires user-confirmed physical disc identity.', None),
    'disc_porter_get_job': ('GET', '/jobs/{job_id}', JobID, True, 'Read one job and its last committed checkpoint.', None),
    'disc_porter_get_report': ('GET', '/report/{job_id}', JobID, True, 'Read verification report. Completed checks do not establish physical or perceptual TV acceptance.', None),
    'disc_porter_list_profiles': ('GET', '/profiles', Empty, True, 'Read saved exact-disc identification profiles.', None),
    'disc_porter_save_profile': ('POST', '/profiles', Profile, False, 'Save or replace an exact structural disc identification profile. With auto_start enabled, a known disc may start automatically.', None),
    'disc_porter_pause_after_checkpoint': ('POST', '/jobs/{job_id}/action', JobID, False, 'Request pause after the current durable phase finishes. This is not immediate interruption.', 'pause_after_checkpoint'),
    'disc_porter_next_checkpoint': ('POST', '/jobs/{job_id}/action', JobID, False, 'Advance a paused job to the next durable checkpoint.', 'next_checkpoint'),
    'disc_porter_resume': ('POST', '/jobs/{job_id}/action', Resume, False, 'Resume an eligible job, optionally choosing a stopping checkpoint. Interrupted phases restart with a new candidate.', 'resume'),
    'disc_porter_cancel': ('POST', '/jobs/{job_id}/action', JobID, False, 'Cancel after the active phase finishes. Preserves originals, candidates and previous outputs.', 'cancel'),
    'disc_porter_get_settings': ('GET', '/settings', Empty, True, 'Read local archive settings.', None),
    'disc_porter_save_settings': ('POST', '/settings', Settings, False, 'Replace settings. Enabling auto_start permits saved known-disc profiles to start acquisition automatically.', None),
}

class BridgeError(Exception):
    pass

def endpoint() -> tuple[str, str]:
    path = Path(os.environ.get('DISC_ARCHIVE_ENDPOINT_FILE', str(Path.home() / 'Library/Application Support/DiscPorter/endpoint.json')))
    try:
        # Refuse symlinks, wrong owners and permissions that expose the bearer token.
        with path.open('r') as handle:
            info = os.fstat(handle.fileno())
            if path.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise BridgeError('Engine endpoint must be owned by this user, mode 0600, and not a symlink. Restart Disc Porter.')
            raw = json.load(handle)
        url, token = raw['url'], raw['token']
        parts = urlsplit(url)
        if parts.scheme != 'http' or parts.hostname != '127.0.0.1' or not parts.port or parts.username or parts.password or parts.path not in ('', '/') or parts.query or parts.fragment:
            raise ValueError('invalid local endpoint')
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ValueError('invalid token')
        return url.rstrip('/'), token
    except BridgeError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise BridgeError('Engine endpoint missing or invalid. Open Disc Porter and retry; the MCP bridge does not launch the engine.') from None

async def request(method: str, route: str, payload: dict | None) -> dict[str, Any]:
    url, token = endpoint()  # Re-read each time so engine restarts need no MCP restart.
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            reply = await client.request(method, url + route, headers={'Authorization': 'Bearer ' + token}, json=payload)
        if reply.status_code in (401, 403):
            raise BridgeError('Engine rejected authentication. Restart Disc Porter to refresh its private endpoint and retry.')
        if not reply.is_success:
            try:
                message = reply.json().get('error', 'Request rejected.')
            except (ValueError, AttributeError):
                message = 'Request rejected.'
            # Never allow an engine error to echo the bearer credential.
            raise BridgeError(f'Engine HTTP {reply.status_code}: {str(message).replace(token, "[redacted]")[:1000]}')
        data = reply.json()
        if not isinstance(data, dict):
            raise BridgeError('Engine returned an invalid response object. Check the app version.')
        return redact(data, token)
    except httpx.TimeoutException:
        raise BridgeError('Engine timed out. Check job status before retrying a mutation; the request may have been accepted.') from None
    except httpx.HTTPError:
        raise BridgeError('Engine is unreachable or its endpoint is stale. Open Disc Porter and retry. Check status before repeating a mutation.') from None
    except ValueError:
        raise BridgeError('Engine returned invalid JSON. Check the app version.') from None

def redact(value: Any, token: str) -> Any:
    if isinstance(value, dict):
        return {k: redact(v, token) for k, v in value.items() if k.lower() not in ('token', 'authorization')}
    if isinstance(value, list):
        return [redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, '[redacted]')
    return value

server = Server('disc_porter_mcp')

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(name=name, description=desc, inputSchema=model.model_json_schema(),
                 outputSchema={'type': 'object', 'additionalProperties': True},
                 annotations=ToolAnnotations(readOnlyHint=read, destructiveHint=not read,
                     idempotentHint=read, openWorldHint=False))
            for name, (_, _, model, read, desc, _) in SPECS.items()]

@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    try:
        if name not in SPECS:
            raise BridgeError('Unknown tool. List available Disc Porter tools and retry.')
        method, route, model, _, _, action = SPECS[name]
        params = model.model_validate(arguments)
        payload = params.model_dump(exclude_none=True)
        if '{job_id}' in route:
            route = route.format(job_id=payload.pop('job_id'))
        if action:
            payload['action'] = action
        data = await request(method, route, payload if method == 'POST' else None)
        return CallToolResult(content=[TextContent(type='text', text=json.dumps(data, separators=(',', ':')))], structuredContent=data)
    except ValidationError as exc:
        # omit supplied values so accidental secret inputs are not echoed
        errors = '; '.join('.'.join(map(str, e['loc'])) + ': ' + e['msg'] for e in exc.errors(include_input=False))
        return CallToolResult(content=[TextContent(type='text', text='Invalid arguments: ' + errors)], isError=True)
    except BridgeError as exc:
        return CallToolResult(content=[TextContent(type='text', text=str(exc))], isError=True)

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == '__main__':
    asyncio.run(main())
