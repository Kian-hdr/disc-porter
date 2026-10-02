#!/usr/bin/env python3
"""Disc Porter MCP control plane. No acquisition, encoding or model calls here."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import re
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
Revision = Annotated[int, Field(ge=1)]

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)

class Empty(Input):
    pass

class JobID(Input):
    job_id: Identifier = Field(description='Job ID returned by the engine.')

class ControlJob(JobID):
    expected_revision: Revision | None = None

class RecipePatch(Input):
    preset_id: Identifier | None = None
    output_root: str | None = None
    work_root: str | None = None
    original_root: str | None = None
    folder_layout: Literal['organized', 'flat'] | None = None
    file_template: str | None = None
    reserve_bytes: Annotated[int, Field(ge=0)] | None = None
    mode: Literal['transcode', 'original'] | None = None
    output_container: Literal['mp4', 'mkv'] | None = None
    video_codec: Literal['hevc', 'h264'] | None = None
    encoder: Literal['software', 'hardware'] | None = None
    quality: Annotated[int, Field(ge=0, le=51)] | None = None
    speed: str | None = None
    bitrate_kbps: Annotated[int, Field(ge=0)] | None = None
    bit_depth: Literal['source', '8', '10'] | None = None
    resolution: Literal['source', '480p', '720p', '1080p', '2160p'] | None = None
    frame_rate: Literal['source', '24', '25', '30', '50', '60'] | None = None
    deinterlace: Literal['auto', 'off', 'frame', 'field'] | None = None
    aspect: Literal['preserve', 'square'] | None = None
    languages: list[Annotated[str, Field(pattern=r'^[a-z]{3}$')]] | None = None
    audio_policy: Literal['main_per_language', 'all', 'selected'] | None = None
    audio_codec: Literal['aac', 'ac3', 'copy'] | None = None
    audio_bitrate_kbps: Annotated[int, Field(ge=32, le=1536)] | None = None
    audio_channels: Literal['source', 'stereo'] | None = None
    include_commentary: bool | None = None
    default_audio_language: str | None = None
    preserve_original_audio: bool | None = None
    subtitle_policy: Literal['text', 'copy', 'burn', 'none'] | None = None
    subtitle_languages: list[Annotated[str, Field(pattern=r'^[a-z]{3}$')]] | None = None
    default_subtitle_language: str | None = None
    preserve_bitmap_subtitles: bool | None = None
    auto_start: bool | None = None
    default_checkpoint: Phase | None = None
    on_battery: Literal['pause', 'run'] | None = None
    auto_resume: bool | None = None
    retry_count: Annotated[int, Field(ge=0, le=10)] | None = None
    max_encoders: Annotated[int, Field(ge=1)] | None = None
    cpu_threads: Annotated[int, Field(ge=0)] | None = None
    cleanup_policy: Literal['keep', 'delete_verified'] | None = None
    notifications: bool | None = None
    online_lookup: bool | None = None
    appearance: Literal['system', 'light', 'dark'] | None = None
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
    makemkv_path: str | None = None

class Title(Input):
    id: Annotated[int, Field(ge=0)]
    name: Name
    audio_streams: list[Annotated[int, Field(ge=0)]] | None = None
    subtitle_streams: list[Annotated[int, Field(ge=0)]] | None = None
    overrides: RecipePatch | None = None
    season: Annotated[int, Field(ge=0, le=999)] | None = None
    episode: Annotated[int, Field(ge=0, le=9999)] | None = None
    year: Annotated[int, Field(ge=1800, le=2200)] | None = None
    default_audio_stream: Annotated[int, Field(ge=0)] | None = None
    default_subtitle_stream: Annotated[int, Field(ge=0)] | None = None
    forced_subtitle_streams: list[Annotated[int, Field(ge=0)]] | None = None

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
    preset_id: Identifier | None = None
    overrides: RecipePatch | None = None
    expected_settings_revision: Revision | None = None
    expected_plan_fingerprint: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')] | None = None
    idempotency_key: Identifier | None = Field(default=None, description='Reuse the same key after an ambiguous timeout; use a new key for a different job.')
    remember_profile: bool = False
    confirm_transforms: bool = False

class Profile(Selection):
    disc_id: Annotated[str, Field(min_length=1, max_length=256)]
    overrides: RecipePatch | None = None
    preset_id: Identifier | None = None

class Resume(ControlJob):
    stop_after: Phase | None = None

class Settings(Input):
    output_root: Annotated[str, Field(max_length=4096)]
    auto_start: bool
    video_codec: Literal['hevc', 'h264']
    quality: Annotated[int, Field(ge=0, le=51)]
    languages: Annotated[list[Annotated[str, Field(pattern=r'^[a-z]{3}$')]], Field(max_length=20)]

class StatusInput(Input):
    detailed: bool = False
    limit: Annotated[int, Field(ge=1, le=100)] = 20

class DetailedJob(JobID):
    detailed: bool = False

class SettingsPatch(RecipePatch):
    expected_revision: Revision

class PresetID(Input):
    preset_id: Identifier

class DuplicatePreset(Input):
    name: Name
    base_id: Identifier

class UpdatePreset(PresetID):
    expected_revision: Revision
    name: Name | None = None
    settings: RecipePatch | None = None

class DeletePreset(PresetID):
    expected_revision: Revision

class ProfileUpdate(Profile):
    expected_revision: Revision

class ProfileDelete(Input):
    disc_id: Annotated[str, Field(min_length=1, max_length=256, pattern=r'^[A-Za-z0-9_-]+$')]
    expected_revision: Revision

class JobEdit(JobID):
    expected_revision: Revision
    overrides: RecipePatch
    titles: list[Title] | None = None
    confirm_transforms: bool = False

class JobRevision(JobID):
    expected_revision: Revision

class QueueAction(Input):
    action: Literal['prepare_disconnect', 'resume_archiving', 'reorder']
    job_ids: list[Identifier] | None = None

class Acceptance(JobID):
    expected_revision: Revision
    playback: Literal['accepted', 'pending', 'rejected']
    perceptual: Literal['accepted', 'pending', 'rejected']

class ScanID(Input):
    scan_id: Identifier

class Identify(Input):
    provider: Literal['local', 'tmdb'] = 'local'
    query: Annotated[str, Field(max_length=256)] | None = None
    disc_id: Annotated[str, Field(max_length=256)] | None = None
    source_path: Annotated[str, Field(max_length=4096)] | None = None

class Credential(Input):
    token: Annotated[str, Field(min_length=1, max_length=2048, repr=False)]

class ExportJob(JobID):
    destination: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_revision: Revision | None = None

class ExportID(Input):
    export_id: Identifier

class ExportAction(ExportID):
    action: Literal['pause', 'resume', 'stop_now']

class Events(Input):
    after: Annotated[int, Field(ge=0)] = 0
    limit: Annotated[int, Field(ge=1, le=100)] = 20

# method, route, input, read-only, description, fixed action
SPECS = {
    'disc_porter_status': ('GET', '/status', StatusInput, True, 'Read compact engine/job/drive/disconnect state. Set detailed for full settings and artifacts.', None),
    'disc_porter_scan': ('POST', '/scan', Empty, False, 'Scan local sources. May update identification state; never starts extraction by itself.', None),
    'disc_porter_start_job': ('POST', '/jobs', StartJob, False, 'Create a local archive job from an exact identified disc or media file. Default stops after scan. Acquisition requires user-confirmed physical disc identity.', None),
    'disc_porter_get_job': ('GET', '/jobs/{job_id}', DetailedJob, True, 'Read one job, effective recipe and last committed checkpoint; detailed includes internal artifacts.', None),
    'disc_porter_get_report': ('GET', '/report/{job_id}', DetailedJob, True, 'Read verification/retention report; detailed includes artifact inventories. Technical checks do not prove playback or perceptual acceptance.', None),
    'disc_porter_list_profiles': ('GET', '/profiles', Empty, True, 'Read saved exact-disc identification profiles.', None),
    'disc_porter_save_profile': ('POST', '/profiles', Profile, False, 'Save or replace an exact structural disc identification profile. With auto_start enabled, a known disc may start automatically.', None),
    'disc_porter_pause_after_checkpoint': ('POST', '/jobs/{job_id}/action', ControlJob, False, 'Request pause after the current durable phase finishes. This is not immediate interruption.', 'pause_after_checkpoint'),
    'disc_porter_next_checkpoint': ('POST', '/jobs/{job_id}/action', ControlJob, False, 'Advance a paused job to the next durable checkpoint.', 'next_checkpoint'),
    'disc_porter_resume': ('POST', '/jobs/{job_id}/action', Resume, False, 'Resume an eligible job, optionally choosing a stopping checkpoint. Interrupted phases restart with a new candidate.', 'resume'),
    'disc_porter_cancel': ('POST', '/jobs/{job_id}/action', ControlJob, False, 'Cancel after the active phase finishes. Preserves originals, candidates and previous outputs.', 'cancel'),
    'disc_porter_get_settings': ('GET', '/settings', Empty, True, 'Read local archive settings.', None),
    'disc_porter_save_settings': ('POST', '/settings', Settings, False, 'Replace settings. Enabling auto_start permits saved known-disc profiles to start acquisition automatically.', None),
}

SPECS.update({
    'disc_porter_preview_start_job': ('POST', '/jobs/preview', StartJob, True, 'Preview effective recipe, destinations, collisions and source transformations before creating a job. No acquisition or output writes.', None),
    'disc_porter_capabilities': ('GET', '/capabilities', Empty, True, 'Discover engine/API versions, supported settings, encoders, tools and feature limits.', None),
    'disc_porter_update_settings': ('PATCH', '/settings', SettingsPatch, False, 'Apply a settings patch against the current revision. Stale edits fail without overwriting newer changes.', None),
    'disc_porter_list_presets': ('GET', '/presets', Empty, True, 'List builtin and custom presets with their revisions and effective recipes.', None),
    'disc_porter_duplicate_preset': ('POST', '/presets', DuplicatePreset, False, 'Duplicate a preset into a named editable custom preset.', None),
    'disc_porter_update_preset': ('PATCH', '/presets/{preset_id}', UpdatePreset, False, 'Edit a custom preset at its expected revision. Builtins are immutable.', None),
    'disc_porter_delete_preset': ('DELETE', '/presets/{preset_id}', DeletePreset, False, 'Remove a custom preset definition; never changes existing job snapshots or media.', None),
    'disc_porter_update_profile': ('PATCH', '/profiles/{disc_id}', ProfileUpdate, False, 'Edit an exact disc mapping/profile at its expected revision.', None),
    'disc_porter_delete_profile': ('DELETE', '/profiles/{disc_id}', ProfileDelete, False, 'Remove an exact disc automation mapping. Does not remove media.', None),
    'disc_porter_preview_job_edit': ('POST', '/jobs/{job_id}/plan-preview', JobEdit, True, 'Preview effective settings, destinations, collisions and which downstream work must restart. Does not apply edits.', None),
    'disc_porter_edit_job': ('PATCH', '/jobs/{job_id}', JobEdit, False, 'Apply a previewed checkpoint edit. Retains previous artifact generations; rejects a running or stale job.', None),
    'disc_porter_stop_now': ('POST', '/jobs/{job_id}/action', ControlJob, False, 'Stop only this job’s owned processes/readers. Preserve committed title operations; unfinished work restarts in a new candidate.', 'stop_now'),
    'disc_porter_retry': ('POST', '/jobs/{job_id}/action', ControlJob, False, 'Retry eligible failed/waiting work from durable checkpoints after its cause is corrected.', 'retry'),
    'disc_porter_reprocess': ('POST', '/jobs/{job_id}/action', ControlJob, False, 'Create a fresh generation from an available original; report reacquisition if original cleanup removed it.', 'reprocess'),
    'disc_porter_queue_action': ('POST', '/queue/action', QueueAction, False, 'Atomically prepare to disconnect, resume archiving, or reorder eligible queued jobs. Manual pauses remain respected.', None),
    'disc_porter_record_acceptance': ('POST', '/jobs/{job_id}/acceptance', Acceptance, False, 'Record supplied playback/perceptual acceptance or rejection. Do not invent observations.', None),
    'disc_porter_start_scan': ('POST', '/scans', Empty, False, 'Start asynchronous discovery and return a scan ID. Does not authorize acquisition.', None),
    'disc_porter_get_scan': ('GET', '/scans/{scan_id}', ScanID, True, 'Read discovery results and actual scan state.', None),
    'disc_porter_identify': ('POST', '/identify', Identify, False, 'Get provenance-labelled local or opt-in TMDb suggestions. Always requires confirmation; never proves episode/cut mapping.', None),
    'disc_porter_metadata_credential_status': ('GET', '/metadata/credential', Empty, True, 'Read whether the TMDb Keychain credential is configured; never returns its value.', None),
    'disc_porter_set_metadata_credential': ('POST', '/metadata/credential', Credential, False, 'Store the supplied TMDb API token in macOS Keychain. Never echo the token.', None),
    'disc_porter_remove_metadata_credential': ('DELETE', '/metadata/credential', Empty, False, 'Remove the TMDb API token from Keychain.', None),
    'disc_porter_cleanup_preview': ('POST', '/jobs/{job_id}/cleanup-preview', JobID, True, 'Inspect technical gates, ownership, protected artifacts and all aliases before cleanup. Does not delete files.', None),
    'disc_porter_cleanup': ('POST', '/jobs/{job_id}/cleanup', JobRevision, False, 'Permanently remove eligible journaled temporary originals under enabled delete_verified policy. Imported/unowned/final original deliverables remain protected.', None),
    'disc_porter_start_export': ('POST', '/exports', ExportJob, False, 'Create a durable verified no-overwrite copy to the selected destination.', None),
    'disc_porter_list_exports': ('GET', '/exports', Empty, True, 'List durable export transfer states.', None),
    'disc_porter_get_export': ('GET', '/exports/{export_id}', ExportID, True, 'Read per-file export progress and verification.', None),
    'disc_porter_export_action': ('POST', '/exports/{export_id}/action', ExportAction, False, 'Pause, resume or stop an export’s owned transfer without touching unrelated files.', None),
    'disc_porter_library': ('GET', '/library', StatusInput, True, 'Read completed outputs and retention/acceptance status. Default limits compact entries; detailed includes all metadata.', None),
    'disc_porter_events': ('GET', '/events', Events, True, 'Read bounded local operation audit after a sequence. Labels are attribution, not authenticated identity proof.', None),
})

LEGACY_TOOLS = {'disc_porter_' + suffix for suffix in (
    'status','scan','start_job','get_job','get_report','list_profiles','save_profile',
    'pause_after_checkpoint','next_checkpoint','resume','cancel','get_settings','save_settings')}

def needs_v2(name: str, arguments: dict[str, Any]) -> bool:
    if name not in LEGACY_TOOLS:
        return SPECS[name][0] != 'GET'
    if SPECS[name][0] != 'GET' and 'expected_revision' in arguments:
        return True
    if name == 'disc_porter_start_job':
        if any(key in arguments for key in ('preset_id','overrides','expected_settings_revision','expected_plan_fingerprint','idempotency_key')) or arguments.get('remember_profile') or arguments.get('confirm_transforms'):
            return True
        return any(set(title) - {'id','name'} for title in arguments.get('titles', []))
    if name == 'disc_porter_save_profile':
        return 'preset_id' in arguments or 'overrides' in arguments or any(set(title)-{'id','name'} for title in arguments.get('titles', []))
    return False

class BridgeError(Exception):
    pass

def endpoint_path() -> Path:
    default_dir = Path(os.environ.get('DISC_PORTER_STATE_DIR', str(Path.home() / 'Library/Application Support/DiscPorter')))
    return Path(os.environ.get('DISC_ARCHIVE_ENDPOINT_FILE', str(default_dir / 'endpoint.json')))

def endpoint() -> tuple[str, str]:
    path = endpoint_path()
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
        raise BridgeError('Engine endpoint missing or invalid. Open Disc Porter or use the bundled MCP launcher to start its engine.') from None

async def ensure_engine() -> None:
    """Start the bundled owner without GUI. Explicit test endpoints never auto-start."""
    if 'DISC_ARCHIVE_ENDPOINT_FILE' in os.environ:
        raise BridgeError('Engine is unreachable or its endpoint is stale. Open Disc Porter and retry.')
    state = endpoint_path().parent
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if getattr(sys, 'frozen', False):
        command = [sys.executable, 'serve', '--state-dir', str(state)]
    else:
        source = Path(__file__).resolve().parents[1] / 'engine/server.py'
        if not source.is_file():
            raise BridgeError('Bundled processing engine is missing. Reinstall Disc Porter.')
        command = [sys.executable, str(source), '--state-dir', str(state)]
    fd = os.open(state / 'mcp-engine.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(fd, 'ab') as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True, close_fds=True)
    except OSError as error:
        raise BridgeError('Could not start the local processing engine: ' + str(error)) from None
    for _ in range(80):
        await asyncio.sleep(.2)
        try:
            url, token = endpoint()
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                response = await client.get(url + '/status', headers={'Authorization': 'Bearer ' + token})
            if response.is_success:
                return
        except (BridgeError, httpx.HTTPError):
            pass
        # Another owner can retain the lock during a brief supervisor teardown.
        # Do not spin-launch additional processes or kill that owner.
        if process.poll() is not None and not endpoint_path().exists():
            break
    raise BridgeError('Local engine startup did not complete. Existing work may still own its state; reopen the app after its checkpoint.')

async def request(method: str, route: str, payload: dict | None) -> dict[str, Any]:
    try:
        url, token = endpoint()
    except BridgeError:
        if endpoint_path().exists() or 'DISC_ARCHIVE_ENDPOINT_FILE' in os.environ:
            raise  # Fail closed on insecure/invalid existing endpoints.
        await ensure_engine()
        url, token = endpoint()
    secret = payload.get('token', '') if payload else ''
    def safe_message(value: Any) -> str:
        text = str(value).replace(token, '[redacted]')
        return text.replace(secret, '[redacted]') if secret else text
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            options = {'params': payload} if method == 'GET' else {'json': payload}
            try:
                reply = await client.request(method, url + route,
                    headers={'Authorization': 'Bearer ' + token, 'X-Disc-Porter-Actor': 'mcp'}, **options)
            except httpx.ConnectError:
                if 'DISC_ARCHIVE_ENDPOINT_FILE' in os.environ:
                    raise
                # ConnectError happened before delivery; retries after a read timeout
                # remain forbidden because a mutation may already be committed.
                await ensure_engine()
                url, token = endpoint()
                reply = await client.request(method, url + route,
                    headers={'Authorization': 'Bearer ' + token, 'X-Disc-Porter-Actor': 'mcp'}, **options)
        if reply.status_code in (401, 403):
            raise BridgeError('Engine rejected authentication. Restart Disc Porter to refresh its private endpoint and retry.')
        if not reply.is_success:
            try:
                message = reply.json().get('error', 'Request rejected.')
            except (ValueError, AttributeError):
                message = 'Request rejected.'
            # Never allow an engine error to echo the bearer credential.
            raise BridgeError(f'Engine HTTP {reply.status_code}: {safe_message(message)[:1000]}')
        data = reply.json()
        if not isinstance(data, dict):
            raise BridgeError('Engine returned an invalid response object. Check the app version.')
        data = redact(data, token)
        return redact(data, secret) if secret else data
    except httpx.TimeoutException:
        raise BridgeError('Engine timed out. Check job status before retrying a mutation; the request may have been accepted.') from None
    except httpx.HTTPError:
        raise BridgeError('Engine is unreachable or its endpoint is stale. Open Disc Porter and retry. Check status before repeating a mutation.') from None
    except ValueError:
        raise BridgeError('Engine returned invalid JSON. Check the app version.') from None

def redact(value: Any, token: str) -> Any:
    if isinstance(value, dict):
        return {k: redact(v, token) for k, v in value.items() if k.lower() not in ('token', 'authorization', 'api_key', 'password')}
    if isinstance(value, list):
        return [redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, '[redacted]') if token else value
    return value

server = Server('disc_porter_mcp')

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(name=name, description=desc, inputSchema=model.model_json_schema(),
                 outputSchema={'type': 'object', 'additionalProperties': True},
                 annotations=ToolAnnotations(readOnlyHint=read, destructiveHint=not read,
                     idempotentHint=read, openWorldHint=name == 'disc_porter_identify'))
            for name, (_, _, model, read, desc, _) in SPECS.items()]

@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    try:
        if name not in SPECS:
            raise BridgeError('Unknown tool. List available Disc Porter tools and retry.')
        method, route, model, _, _, action = SPECS[name]
        params = model.model_validate(arguments)
        payload = params.model_dump(exclude_none=True)
        detailed = payload.pop('detailed', False)
        limit = payload.pop('limit', 20) if isinstance(params, StatusInput) else None
        for key in re.findall(r'{([a-z_]+)}', route):
            route = route.replace('{' + key + '}', str(payload.pop(key)))
        if action:
            payload['action'] = action
        if needs_v2(name, arguments):
            try:
                capability = await request('GET', '/capabilities', None)
            except BridgeError as error:
                raise BridgeError('This operation needs the Disc Porter 0.2 engine. Existing processing is preserved; finish or pause it before upgrading. ' + str(error)) from None
            if capability.get('api_version') != 2 or capability.get('engine_version') != '0.2.0':
                raise BridgeError('Engine/API version mismatch. Upgrade the app after a safe checkpoint; requested v2 settings were not applied.')
        data = await request(method, route, payload or None)
        if not detailed and data.get('api_version') == 2 and name == 'disc_porter_status':
            jobs = data.get('jobs', [])
            keep = ('id', 'collection', 'state', 'phase', 'checkpoint', 'progress', 'phase_progress',
                    'current_title', 'pause_requested', 'safe_to_disconnect', 'message', 'revision', 'next_checkpoint')
            data['total_jobs'] = len(jobs)
            data['jobs'] = [{key: job[key] for key in keep if key in job} for job in jobs[:limit]]
            settings = data.get('settings', {})
            data['settings'] = {key: settings[key] for key in ('revision','preset_id','output_root','auto_start','cleanup_policy') if key in settings}
            data.pop('presets', None)
        if not detailed and name in ('disc_porter_get_job', 'disc_porter_get_report'):
            for artifact in data.get('artifacts', []):
                for key in ('source_probe', 'disc_streams', 'probe'):
                    artifact.pop(key, None)
            data.pop('disc_streams', None)
        if name == 'disc_porter_library' and limit:
            items = data.get('items', [])
            data.update(total=data.get('total', len(items)), items=items[:limit], has_more=len(items) > limit)
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
