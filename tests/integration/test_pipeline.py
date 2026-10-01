"""Actual engine HTTP + official MCP SDK + synthetic HEVC archive workflow."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import urllib.request

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
PYTHON = '/opt/homebrew/bin/python3.12'
FFMPEG = '/opt/homebrew/bin/ffmpeg'

class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_engine_mcp_checkpoint_pipeline(self):
        with tempfile.TemporaryDirectory(prefix='disc-porter-integration-') as directory:
            base = Path(directory)
            state = base / 'state'
            output = base / 'output'
            output.mkdir()
            source = base / 'source.mkv'
            subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x96:rate=24:duration=1',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-f', 'lavfi', '-i', 'sine=frequency=660:duration=1',
                '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                '-c:a', 'flac', '-metadata:s:a:0', 'language=eng', '-metadata:s:a:1', 'language=deu', str(source)], check=True)
            engine_log = (base / 'engine.log').open('w')
            engine = subprocess.Popen([PYTHON, str(ROOT / 'engine/server.py'), '--state-dir', str(state)],
                                      stdout=engine_log, stderr=engine_log)
            endpoint_file = state / 'endpoint.json'
            try:
                for _ in range(100):
                    if endpoint_file.exists(): break
                    await asyncio.sleep(.05)
                self.assertTrue(endpoint_file.exists(), 'Engine did not publish endpoint')
                endpoint = json.loads(endpoint_file.read_text())
                params = StdioServerParameters(command=str(ROOT / 'mcp/run.sh'), env=dict(os.environ,
                                               DISC_ARCHIVE_ENDPOINT_FILE=str(endpoint_file)))
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertEqual(len(tools.tools), 13)
                        async def call(name, args=None):
                            result = await session.call_tool('disc_porter_' + name, args or {})
                            self.assertFalse(result.isError, str(result.content))
                            return result.structuredContent
                        await call('save_settings', dict(output_root=str(output), auto_start=False,
                            video_codec='hevc', quality=18, languages=['eng', 'deu']))
                        started = await call('start_job', dict(source_path=str(source), collection='Synthetic Validation',
                            kind='film', titles=[dict(id=0, name='Synthetic_Film')], stop_after='scan'))
                        jid = started['id']
                        async def wait_checkpoint(checkpoint):
                            for _ in range(300):
                                value = await call('get_job', dict(job_id=jid))
                                if value['state'] in ('blocked', 'failed'):
                                    self.fail(value['message'])
                                if value['checkpoint'] == checkpoint and value['state'] in ('paused', 'completed'):
                                    return value
                                await asyncio.sleep(.05)
                            self.fail('Checkpoint timed out: ' + checkpoint)
                        scan = await wait_checkpoint('scan')
                        self.assertTrue(scan['safe_to_disconnect'])
                        await call('next_checkpoint', dict(job_id=jid))
                        acquired = await wait_checkpoint('acquire')
                        self.assertTrue(Path(acquired['artifacts'][0]['original']).is_file())
                        source.rename(base / 'disconnected-source.mkv')
                        # Future phases must use the durable original, not the now absent input.
                        for phase in ('encode', 'verify', 'complete'):
                            await call('next_checkpoint', dict(job_id=jid))
                            finished = await wait_checkpoint(phase)
                            self.assertTrue(finished['safe_to_disconnect'])
                        report = await call('get_report', dict(job_id=jid))
                        self.assertTrue(report['originals_retained'])
                        self.assertEqual(report['tv_acceptance'], 'pending')
                        self.assertEqual(report['reports'][0]['full_decode'], 'passed')
                        self.assertTrue(Path(finished['artifacts'][0]['final']).is_file())
                        self.assertTrue((await call('status'))['safe_to_disconnect'])
                request = urllib.request.Request(endpoint['url'] + '/shutdown', data=b'{}',
                    headers={'Authorization':'Bearer ' + endpoint['token'], 'Content-Type':'application/json'})
                with urllib.request.urlopen(request, timeout=10) as response:
                    self.assertEqual(response.status, 200)
                engine.wait(timeout=10)
                # Reopening after all writes must preserve the complete job and its report.
                engine = subprocess.Popen([PYTHON, str(ROOT / 'engine/server.py'), '--state-dir', str(state)],
                                          stdout=engine_log, stderr=engine_log)
                for _ in range(100):
                    if endpoint_file.exists(): break
                    await asyncio.sleep(.05)
                new = json.loads(endpoint_file.read_text())
                req = urllib.request.Request(new['url'] + '/jobs/' + jid, headers={'Authorization':'Bearer ' + new['token']})
                with urllib.request.urlopen(req, timeout=10) as response:
                    saved = json.load(response)
                self.assertEqual(saved['state'], 'completed')
            finally:
                if engine.poll() is None:
                    engine.terminate()
                    engine.wait(timeout=10)
                engine_log.close()

if __name__ == '__main__': unittest.main()
