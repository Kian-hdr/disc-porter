import json
import os
import plistlib
from unittest.mock import patch
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from engine.core import Engine, ArchiveError, safe_name

PYTHON=sys.executable
ROOT=Path(__file__).resolve().parents[2]

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name).resolve(); self.out=self.root/'out'; self.out.mkdir()
        self.e=Engine(self.root/'state',start_worker=False)
        self.e.settings(dict(output_root=str(self.out)))
    def tearDown(self):
        for j in self.e.jobs():
            if j['state'] in ('running','queued'): j['state']='paused'; self.e._job_save(j)
        self.e.close(); self.tmp.cleanup()
    def create(self):
        source=self.root/'test.dat'; source.write_bytes(b'SYNTHETIC')
        return self.e.create_job(dict(source_path=str(source),collection='C',kind='film',titles=[dict(id=0,name='X')],stop_after='scan'))
    def test_names_symlinks_wrong_destination(self):
        for name in [' .. ',' . ','../x','a/b','a\\b']:
            with self.assertRaises(ArchiveError): safe_name(name)
        (self.out/'C').symlink_to(self.root)
        with self.assertRaises(ArchiveError): self.create()
        (self.out/'C').unlink()
        j=self.create(); self.out.rename(self.root/'old'); self.out.mkdir()
        self.e.run_job(j['id']); self.assertEqual(self.e.job(j['id'])['state'],'blocked')
    def test_nested_volume_identity_uses_mount_root_and_stable_uuid(self):
        from engine.core import identity, check_identity
        nested=self.out/'deep'/'collection'; nested.mkdir(parents=True)
        result=subprocess.CompletedProcess([],0,plistlib.dumps(dict(VolumeUUID='SYNTHETIC-UUID',MountPoint='/synthetic-mount')),b'')
        with patch('engine.core.subprocess.run',return_value=result) as mock:
            saved=identity(nested)
            target=Path(mock.call_args.args[0][-1])
            self.assertNotEqual(target,nested); self.assertTrue(nested.is_relative_to(target))
            self.assertNotIn('dev',saved); check_identity(saved)
        wrong=subprocess.CompletedProcess([],0,plistlib.dumps(dict(VolumeUUID='DIFFERENT',MountPoint='/synthetic-mount')),b'')
        with patch('engine.core.subprocess.run',return_value=wrong):
            with self.assertRaises(ArchiveError): check_identity(saved)
    def test_disable_auto_start_with_missing_destination_preserves_binding(self):
        original=self.e.settings()['_identity']
        self.e.settings(dict(auto_start=True))
        self.out.rename(self.root/'disconnected')
        changed=self.e.settings(dict(auto_start=False))
        self.assertFalse(changed['auto_start']); self.assertEqual(changed['_identity'],original)
        # Even a hostile stale full-settings roundtrip cannot silently rebind UUID.
        changed=self.e.settings(dict(changed,_identity={'path':'wrong'}))
        self.assertEqual(changed['_identity'],original)
    def test_preserve_accepted_requests(self):
        j=self.create(); stale=dict(j); stale['state']='running'
        self.e.action(j['id'],dict(action='pause_after_checkpoint'))
        self.e._job_save(stale)
        self.assertTrue(self.e.job(j['id'])['pause_requested'])
    def test_real_progress_and_heartbeat(self):
        j=self.create(); j['state']='running'; self.e._job_save(j)
        command=[PYTHON,'-c','import time; print("out_time_us=1000000",flush=True); print("total_size=1000",flush=True); time.sleep(.6); print("out_time_us=2000000",flush=True); print("total_size=2000",flush=True)']
        self.e._run(command,self.root/'progress.log',job=j,duration=4,title='X')
        got=self.e.job(j['id']); self.assertEqual(got['phase_progress'],.5); self.assertEqual(got['progress'],0)
        self.assertEqual(got['processed_bytes'],2000); self.assertIsNotNone(got['last_progress_at']); self.assertGreater(got['throughput_bps'],0)
        stamp=got['last_progress_at']
        self.e._run([PYTHON,'-c','import time; time.sleep(.6)'],self.root/'quiet.log',job=got,title='X')
        quiet=self.e.job(j['id']); self.assertIsNone(quiet['phase_progress']); self.assertIsNone(quiet['processed_bytes']); self.assertEqual(quiet['last_progress_at'],stamp); self.assertNotEqual(quiet['heartbeat_at'],got['created_at'])
    def test_runner_owns_lock_after_parent_crash(self):
        # Disposable parent owns a separate state; no physical media or real tools.
        state=self.root/'crash-state'; ready=self.root/'ready'
        script='from engine.core import Engine; from pathlib import Path; import sys; e=Engine(sys.argv[1],start_worker=False); e._run([sys.executable,"-c","import signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path("+repr(sys.argv[2])+").write_text(str(__import__(\\\"os\\\").getpid())); time.sleep(60)"],Path(sys.argv[1])/"test.log")'
        parent=subprocess.Popen([PYTHON,'-c',script,str(state),str(ready)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        deadline=time.monotonic()+8
        while not ready.exists() and time.monotonic()<deadline and parent.poll() is None: time.sleep(.05)
        if not ready.exists(): self.fail('Synthetic child did not start: '+parent.stderr.read())
        child=int(ready.read_text()); parent.kill(); parent.wait()
        with self.assertRaises(ArchiveError): Engine(state,start_worker=False)
        deadline=time.monotonic()+10
        reopened=None
        while time.monotonic()<deadline:
            try: reopened=Engine(state,start_worker=False); break
            except ArchiveError: time.sleep(.1)
        self.assertIsNotNone(reopened)
        # Tool process has exited before lock can be reacquired. Zombies count as exited.
        p=subprocess.run(['/bin/ps','-p',str(child),'-o','stat='],capture_output=True,text=True)
        self.assertTrue(not p.stdout.strip() or p.stdout.strip().startswith('Z'), p.stdout)
        reopened.close(); parent.stderr.close()

class HTTPTests(unittest.TestCase):
    def test_auth_host_origin_private_endpoint_and_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state'
            p=subprocess.Popen([PYTHON,str(ROOT/'engine/server.py'),'--state-dir',str(state)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+8
                while not (state/'endpoint.json').exists() and time.monotonic()<deadline: time.sleep(.05)
                endpoint=json.loads((state/'endpoint.json').read_text())
                self.assertEqual((state/'endpoint.json').stat().st_mode & 0o777,0o600)
                def request(path,headers=None,data=None):
                    return urllib.request.urlopen(urllib.request.Request(endpoint['url']+path,headers=headers or {},data=data),timeout=10)
                with self.assertRaises(urllib.error.HTTPError) as x: request('/status')
                self.assertEqual(x.exception.code,403)
                headers={'Authorization':'Bearer '+endpoint['token']}
                for extra in [{'Origin':'https://example.invalid'},{'Host':'evil.invalid'}]:
                    with self.assertRaises(urllib.error.HTTPError): request('/status',dict(headers,**extra))
                status=json.loads(request('/status',headers).read()); self.assertTrue(status['safe_to_disconnect']); self.assertNotIn(endpoint['token'],json.dumps(status))
                self.assertTrue(json.loads(request('/shutdown',headers,b'{}').read())['accepted']); self.assertEqual(p.wait(timeout=10),0)
            finally:
                if p.poll() is None: p.terminate(); p.wait(timeout=5)
                p.stderr.close()

if __name__=='__main__':unittest.main()
