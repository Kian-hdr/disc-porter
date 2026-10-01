"""Real SDK stdio handshake/calls against disposable authenticated HTTP fixtures."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jsonschema import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
TOKEN = 'synthetic-secret-not-real'
SETTINGS = {'output_root': '/synthetic/archive', 'auto_start': False, 'video_codec': 'hevc', 'quality': 18, 'languages': ['eng', 'deu']}
JOB = {'id': 'fixture_job', 'state': 'paused', 'phase': 'encode', 'checkpoint': 'acquire', 'stop_after': 'verify', 'safe_to_disconnect': True, 'collection': 'Synthetic', 'kind': 'film', 'progress': 0.5}
PROFILE = {'disc_id': 'synthetic_disc', 'collection': 'Synthetic', 'kind': 'film', 'titles': [{'id': 0, 'name': 'Synthetic Film'}]}
REPORT = {'job_id': 'fixture_job', 'verified': True, 'physical_tv_acceptance': 'pending', 'originals_retained': True}

class Handler(BaseHTTPRequestHandler):
    calls = []
    reject = False
    malformed = False
    def log_message(self, *args):
        pass
    def do_GET(self):
        self.respond()
    def do_POST(self):
        self.respond()
    def respond(self):
        if self.headers.get('Authorization') != 'Bearer ' + TOKEN or self.reject:
            self.send_response(401); self.end_headers(); return
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        self.calls.append((self.command, self.path, body))
        code = 200
        if self.path == '/status':
            data = {'settings': SETTINGS, 'jobs': [JOB], 'discs': [], 'tools': {'makemkv': None, 'ffmpeg': '/synthetic/ffmpeg', 'ffprobe': '/synthetic/ffprobe'}, 'safe_to_disconnect': True, 'message': 'Synthetic fixture', 'token': TOKEN}
        elif self.path == '/settings': data = body if self.command == 'POST' else SETTINGS
        elif self.path == '/profiles': data = body if self.command == 'POST' else {'profiles': [PROFILE]}
        elif self.path == '/scan': data = {'discs': []}
        elif self.path == '/jobs': data = {**JOB, **body}
        elif self.path == '/jobs/fixture_job': data = JOB
        elif self.path == '/jobs/fixture_job/action': data = {**JOB, 'message': body['action']}
        elif self.path == '/report/fixture_job': data = REPORT
        else: code, data = 404, {'error': 'Unknown job; check job_id. ' + TOKEN}
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.end_headers()
        self.wfile.write(b'not-json' if self.malformed else json.dumps(data).encode())

class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Handler.calls = []; Handler.reject = False; Handler.malformed = False
        self.temp = tempfile.TemporaryDirectory()
        self.endpoint = Path(self.temp.name) / 'endpoint.json'
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.write_endpoint()
    def write_endpoint(self, **overrides):
        self.endpoint.write_text(json.dumps({'url': f'http://127.0.0.1:{self.http.server_port}', 'token': TOKEN, **overrides}))
        self.endpoint.chmod(0o600)
    async def asyncTearDown(self):
        await asyncio.to_thread(self.http.shutdown)
        self.http.server_close(); self.temp.cleanup()
    async def call(self, name, args=None):
        return await self.session.call_tool('disc_porter_' + name, args or {})
    async def test_handshake_list_schemas_annotations(self):
        self.assertEqual(self.init.serverInfo.name, 'disc_porter_mcp')
        tools = (await self.session.list_tools()).tools
        self.assertEqual(len(tools), 13)
        for tool in tools:
            self.assertFalse(tool.inputSchema['additionalProperties'])
            self.assertIsNotNone(tool.outputSchema)
            self.assertFalse(tool.annotations.openWorldHint)
            self.assertEqual(tool.annotations.readOnlyHint, tool.name in {'disc_porter_status', 'disc_porter_get_job', 'disc_porter_get_report', 'disc_porter_list_profiles', 'disc_porter_get_settings'})
    async def test_all_routes_structured_results(self):
        cases = [('status', {}), ('scan', {}), ('get_job', {'job_id': 'fixture_job'}), ('get_report', {'job_id': 'fixture_job'}), ('list_profiles', {}), ('save_profile', PROFILE), ('start_job', {**PROFILE, 'source_path': '/synthetic/file.mkv', 'stop_after': 'verify'}), ('get_settings', {}), ('save_settings', SETTINGS)]
        for action in ['pause_after_checkpoint', 'next_checkpoint', 'resume', 'cancel']:
            cases.append((action, {'job_id': 'fixture_job'}))
        schemas = {t.name: t.outputSchema for t in (await self.session.list_tools()).tools}
        for name, args in cases:
            with self.subTest(tool=name):
                result = await self.call(name, args)
                self.assertFalse(result.isError, result.content)
                validate(result.structuredContent, schemas['disc_porter_' + name])
                self.assertEqual(json.loads(result.content[0].text), result.structuredContent)
                self.assertNotIn(TOKEN, result.model_dump_json())
        self.assertEqual(Handler.calls[-1][2], {'action': 'cancel'})
    async def test_strict_inputs_no_http_side_effect(self):
        bad = [('status', {'extra': 1}), ('get_job', {'job_id': '../outside'}), ('save_settings', {**SETTINGS, 'quality': '18'}), ('save_settings', {**SETTINGS, 'auto_start': 1}), ('save_settings', {**SETTINGS, 'quality': 99}), ('save_settings', {**SETTINGS, 'languages': ['english']}), ('start_job', {**PROFILE, 'source_path': '/synthetic/f', 'titles': [{'id': 0, 'name': 'one'}, {'id': 0, 'name': 'two'}]})]
        for name, args in bad:
            self.assertTrue((await self.call(name, args)).isError)
        self.assertEqual(Handler.calls, [])
    async def test_authentication_failure(self):
        Handler.reject = True
        result = await self.call('status')
        self.assertTrue(result.isError); self.assertIn('authentication', result.content[0].text)
        self.assertNotIn(TOKEN, result.model_dump_json())
    async def test_engine_error_truthful_redacted(self):
        result = await self.call('get_job', {'job_id': 'missing'})
        self.assertTrue(result.isError); self.assertIn('404', result.content[0].text)
        self.assertNotIn(TOKEN, result.model_dump_json())
    async def test_missing_invalid_permissions_and_remote_endpoint(self):
        self.endpoint.unlink()
        self.assertTrue((await self.call('status')).isError)
        self.write_endpoint(url='https://example.com')
        self.assertTrue((await self.call('status')).isError)
        self.write_endpoint(); self.endpoint.chmod(0o644)
        self.assertTrue((await self.call('status')).isError)
        self.assertEqual(Handler.calls, [])
    async def test_stale_endpoint_and_refresh(self):
        self.write_endpoint(url='http://127.0.0.1:1')
        result = await self.call('status')
        self.assertTrue(result.isError); self.assertIn('stale', result.content[0].text)
        self.write_endpoint()
        self.assertFalse((await self.call('status')).isError)
    async def test_invalid_engine_json(self):
        Handler.malformed = True
        result = await self.call('status')
        self.assertTrue(result.isError); self.assertIn('invalid JSON', result.content[0].text)
    async def test_stable_readonly_evaluation_fixture(self):
        status = (await self.call('status')).structuredContent
        job = (await self.call('get_job', {'job_id': 'fixture_job'})).structuredContent
        report = (await self.call('get_report', {'job_id': 'fixture_job'})).structuredContent
        settings = (await self.call('get_settings')).structuredContent
        profiles = (await self.call('list_profiles')).structuredContent
        answers = [job['checkpoint'], job['phase'], str(status['safe_to_disconnect']).lower(), report['physical_tv_acceptance'], str(report['originals_retained']).lower(), settings['video_codec'], ','.join(settings['languages']), profiles['profiles'][0]['disc_id'], str(settings['auto_start']).lower(), str(status['tools']['makemkv'])]
        import xml.etree.ElementTree as ET
        expected = [q.findtext('answer') for q in ET.parse(ROOT / 'mcp/evaluation.xml').findall('qa_pair')]
        self.assertEqual(answers, expected)
        self.assertTrue(all(method == 'GET' for method, _, _ in Handler.calls))

def session_test(fn):
    async def wrapped(self):
        transport = StdioServerParameters(command=str(ROOT / 'mcp/run.sh'), args=[], env={**os.environ, 'DISC_ARCHIVE_ENDPOINT_FILE': str(self.endpoint)})
        async with stdio_client(transport) as streams:
            async with ClientSession(*streams) as session:
                self.session = session
                self.init = await session.initialize()
                await fn(self)
    return wrapped

for name in list(vars(BridgeTests)):
    if name.startswith('test_'):
        setattr(BridgeTests, name, session_test(getattr(BridgeTests, name)))

if __name__ == '__main__': unittest.main()
