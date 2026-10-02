from copy import deepcopy
import errno
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from engine.core import Engine as OldEngine,ArchiveError,digest
from engine.service import Engine,Conflict
from engine.transfers import StaleTransfer

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.out=self.root/'out';self.out.mkdir();self.source=self.root/'source.mkv';subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=10:duration=0.1','-c:v','libx264',str(self.source)],check=True)
        self.e=Engine(self.root/'state',tools=dict(ffmpeg='/opt/homebrew/bin/ffmpeg',ffprobe='/opt/homebrew/bin/ffprobe',makemkv=None),start_worker=False)
        s=self.e.settings();self.e.settings(dict(output_root=str(self.out),reserve_bytes=0,on_battery='run',expected_revision=s['revision']))
    def tearDown(self):
        for j in self.e.jobs():
            if j['state']in('running','queued'):j['state']='paused';self.e._job_save(j)
        for t in self.e.runtime_threads:t.join(timeout=10)
        self.e.close();self.tmp.cleanup()
    def request(self):return dict(source_path=str(self.source),collection='Test',kind='film',titles=[dict(id=0,name='Title')],stop_after='complete',expected_settings_revision=self.e.settings()['revision'])
    def test_settings_precedence_and_invalid_combinations(self):
        s=self.e.settings();s=self.e.settings(dict(quality=22,expected_revision=s['revision']))
        j=self.e.create_job(dict(self.request(),overrides=dict(quality=25),titles=[dict(id=0,name='Title',overrides=dict(quality=27))]))
        self.assertEqual(j['settings']['quality'],25);self.assertEqual(j['effective_settings']['0']['quality'],27)
        with self.assertRaises(ArchiveError):self.e.settings(dict(encoder='hardware',bitrate_kbps=0,expected_revision=s['revision']))
        with self.assertRaises(ArchiveError):self.e.settings(dict(audio_codec='copy',audio_channels='stereo',expected_revision=s['revision']))
        self.out.rename(self.root/'absent');s=self.e.settings(dict(auto_start=False,expected_revision=s['revision']));self.assertFalse(s['auto_start'])
    def test_stale_worker_preserves_recorded_acceptance_and_revision(self):
        j=self.e.create_job(self.request());stale=deepcopy(j);stale['state']='running'
        accepted=self.e.acceptance(j['id'],dict(expected_revision=j['revision'],playback='accepted',perceptual='rejected'))
        self.e._job_save(stale);current=self.e.job(j['id'])
        self.assertEqual(current['acceptance'],accepted['acceptance']);self.assertEqual(current['revision'],accepted['revision'])
    def test_preview_fingerprint_rejects_changed_preset_before_or_during_source_read(self):
        custom=self.e.create_preset(dict(name='Snapshot',base_id='balanced'))
        request=dict(self.request(),preset_id=custom['id'])
        preview=self.e.preview_start(request)
        request['expected_plan_fingerprint']=preview['plan_fingerprint']
        self.e.edit_preset(custom['id'],dict(expected_revision=custom['revision'],settings=dict(quality=21)))
        with self.assertRaises(Conflict):self.e.create_job(request)
        self.assertFalse(self.e.jobs())
        request.pop('expected_plan_fingerprint');preview=self.e.preview_start(request);request['expected_plan_fingerprint']=preview['plan_fingerprint']
        actual=__import__('engine.service',fromlist=['identity']).identity;changed=False
        def edit_during_hash(path,content=False):
            nonlocal changed
            if content and not changed:
                changed=True;p=self.e.preset(custom['id']);self.e.edit_preset(p['id'],dict(expected_revision=p['revision'],settings=dict(quality=22)))
            return actual(path,content)
        with patch('engine.service.identity',side_effect=edit_during_hash):
            with self.assertRaises(Conflict):self.e.create_job(request)
        self.assertFalse(self.e.jobs())
    def test_heavy_source_reader_not_under_mutex_and_disconnect_not_safe(self):
        entered=threading.Event();release=threading.Event();actual=__import__('engine.service',fromlist=['identity']).identity
        def slow(path,content=False):
            if content:entered.set();release.wait(5)
            return actual(path,content)
        errors=[]
        with patch('engine.service.identity',side_effect=slow):
            t=threading.Thread(target=lambda:self._capture_exception(lambda:self.e.create_job(self.request()),errors));t.start();self.assertTrue(entered.wait(3))
            status=self.e.status();self.assertFalse(status['safe_to_disconnect']);self.assertEqual(status['jobs'],[])
            self.e.queue_action(dict(action='prepare_disconnect'));self.assertFalse(self.e.status()['safe_to_disconnect']);release.set();t.join(10)
        self.assertTrue(errors);self.assertFalse(self.e.jobs());self.assertTrue(self.e.status()['safe_to_disconnect'])
    def _capture_exception(self,call,errors):
        try:call()
        except Exception as e:errors.append(e)
    def test_stop_now_drains_owned_tool_and_manual_pause_survives_queue_resume(self):
        j=self.e.create_job(self.request());ready=threading.Event();errors=[]
        def fake_acquire(job):
            ready.set();self.e._run([sys.executable,'-c','import time;time.sleep(60)'],self.root/'owned.log',job=job,title='Title')
        with patch.object(self.e,'probe',return_value=dict(streams=[dict(codec_type='video')])) ,patch.object(self.e,'_acquire',side_effect=fake_acquire):
            t=threading.Thread(target=self.e.run_job,args=(j['id'],));t.start();self.assertTrue(ready.wait(5))
            deadline=time.monotonic()+5
            while not self.e.processes and time.monotonic()<deadline:time.sleep(.05)
            j=self.e.job(j['id']);stopped=self.e.action(j['id'],dict(action='stop_now',expected_revision=j['revision']));t.join(10)
        self.assertEqual(stopped['state'],'paused');self.assertFalse(self.e.processes);self.assertTrue(self.e.status()['safe_to_disconnect'])
        self.e.queue_action(dict(action='prepare_disconnect'));self.e.queue_action(dict(action='resume_archiving'));self.assertEqual(self.e.job(j['id'])['state'],'paused')
    def test_capture_timeout_stops_child_and_crash_preserves_owner_lock(self):
        child=self.root/'child.pid'
        with self.assertRaises(subprocess.TimeoutExpired):self.e._capture([sys.executable,'-c','import signal,time,os;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('+repr(str(child))+').write_text(str(os.getpid()));time.sleep(60)'],timeout=.3)
        pid=int(child.read_text());r=subprocess.run(['/bin/ps','-p',str(pid),'-o','stat='],capture_output=True,text=True);self.assertTrue(not r.stdout.strip()or r.stdout.strip().startswith('Z'));self.assertFalse(self.e.processes)
    def test_cross_volume_publication_copy_fallback_and_no_overwrite(self):
        j=self.e.create_job(self.request());candidate=self.out/'candidate.mkv';candidate.write_bytes(b'SYNTHETIC OUTPUT');final=self.out/'final.mkv';real=os.link
        def cross(src,dst,*args,**kwargs):
            if Path(src)==candidate:raise OSError(errno.EXDEV,'Synthetic volume boundary')
            return real(src,dst,*args,**kwargs)
        with patch('engine.service.os.link',side_effect=cross):self.e._publish(j,candidate,final,digest(candidate))
        self.assertEqual(digest(final),digest(candidate));self.assertFalse(os.path.samefile(final,candidate))
        self.e._publish(j,candidate,final,digest(candidate))
        collision=self.out/'collision.mkv';collision.write_bytes(b'USER CONTENT')
        with self.assertRaises(ArchiveError):self.e._publish(j,candidate,collision,digest(candidate))
        self.assertEqual(collision.read_bytes(),b'USER CONTENT')
    def _eligible(self):
        j=self.e.create_job(self.request());original=self.out/'original.mkv';original.write_bytes(b'SYNTHETIC ORIGINAL');alias=self.out/'source-candidate.mkv';os.link(original,alias);final=self.out/'final.mp4';final.write_bytes(b'SYNTHETIC FINAL');st=original.stat()
        a=dict(title_id=0,name='Title',original=str(original),original_sha256=digest(original),original_status='retained',acquisition_committed=True,technical_verified=True,final=str(final),candidate=str(final),candidate_sha256=digest(final),source_probe=dict(streams=[]),sidecars=[])
        j.update(state='completed',checkpoint='complete',settings=dict(j['settings'],cleanup_policy='delete_verified'),effective_settings={'0':dict(j['settings'],cleanup_policy='delete_verified')},artifacts=[a],ledger=[dict(id='owned',title_id=0,role='temporary_original',aliases=[str(original),str(alias)],sha256=digest(original),bytes=st.st_size,dev=st.st_dev,ino=st.st_ino,lifecycle='retained',app_created=True,cleanup_eligible=True)],title_checkpoints={'0':'complete'});self.e._job_save(j);return j
    def test_cleanup_blocks_reference_unknown_alias_legacy_and_recovers(self):
        j=self._eligible();child=self.e.reprocess(j['id'],dict(expected_revision=j['revision']));self.assertFalse(self.e.cleanup_preview(j['id'])['eligible'])
        child['generations']=[dict(artifacts=deepcopy(child['artifacts']))];child['artifacts']=[];self.e._job_save(child);self.assertFalse(self.e.cleanup_preview(j['id'])['eligible'])
        child['generations']=[];self.e._job_save(child);self.assertTrue(self.e.cleanup_preview(j['id'])['eligible'])
        extra=self.root/'untracked.mkv';os.link(j['artifacts'][0]['original'],extra);self.assertFalse(self.e.cleanup_preview(j['id'])['eligible']);extra.unlink()
        preview=self.e.cleanup_preview(j['id']);j=self.e.job(j['id']);j.update(cleanup_status='deleting',cleanup_journal=dict(state='prepared',paths=preview['artifacts'],removed=[]));self.e._job_save(j)
        first=Path(preview['artifacts'][0]['path']);first.unlink() # Simulated crash after unlink and before journal progress.
        self.e._finish_cleanup(j);self.assertEqual(self.e.job(j['id'])['cleanup_status'],'deleted');self.assertTrue(self.source.exists())
    def test_changed_export_blocked_and_transfer_epoch_preserves_resume(self):
        j=self._eligible();Path(j['artifacts'][0]['final']).write_bytes(b'CHANGED FINAL');dest=self.root/'export';dest.mkdir()
        with self.assertRaises(ArchiveError):self.e.create_export(dict(job_id=j['id'],destination=str(dest)))
        t=dict(id='test-transfer',state='paused',files=[],revision=1,worker_epoch=0,pause_requested=True,stop_requested=False,created_at='',updated_at='');self.e._save('export',t['id'],t);stale=deepcopy(t)
        with patch.object(self.e,'_start_export'):self.e.export_action(t['id'],dict(action='resume'))
        with self.assertRaises(StaleTransfer):self.e._save_transfer(stale)
        current=self.e.export(t['id']);self.assertEqual(current['state'],'queued');self.assertFalse(current['pause_requested']);self.assertEqual(current['revision'],2)
        current['state']='completed';self.e._save('export',current['id'],current)
    def test_keychain_is_mocked_and_credentials_never_in_status(self):
        secret='SYNTHETIC-ONLY-NOT-A-REAL-TOKEN'
        with patch('engine.service.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'',b''))as mock:
            self.assertTrue(self.e.metadata_credential(dict(token=secret))['configured']);self.assertIn(secret,mock.call_args.args[0])
        self.assertNotIn(secret,json.dumps(self.e.status()));self.assertNotIn(secret,json.dumps(self.e.events()))

class MigrationTests(unittest.TestCase):
    def test_migration_failure_rolls_back_and_releases_owner_lock(self):
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp);out=root/'out';out.mkdir();source=root/'source.dat';source.write_bytes(b'SYNTHETIC')
            old=OldEngine(root/'state',start_worker=False);old.settings(dict(output_root=str(out)))
            for collection in('First','Second'):
                job=old.create_job(dict(source_path=str(source),collection=collection,kind='film',titles=[dict(id=0,name=collection)],stop_after='scan'));job['state']='paused';old._job_save(job)
            old.close();real=Engine._job_save
            def fail_second(instance,job,*args,**kwargs):
                if job['collection']=='Second':raise RuntimeError('Synthetic migration interruption')
                return real(instance,job,*args,**kwargs)
            with patch.object(Engine,'_job_save',new=fail_second):
                with self.assertRaises(RuntimeError):Engine(root/'state',start_worker=False)
            with sqlite3.connect(root/'state'/'archive.sqlite3')as db:
                settings=json.loads(db.execute("SELECT body FROM records WHERE kind='settings'").fetchone()[0]);self.assertNotIn('schema_version',settings)
                records=[json.loads(r[0])for r in db.execute("SELECT body FROM records WHERE kind='job'")];self.assertTrue(all('revision'not in r for r in records))
            e=Engine(root/'state',start_worker=False);self.assertEqual(e.settings()['schema_version'],2);self.assertTrue(all(j['revision']==1 for j in e.jobs()));e.close()
    def test_v1_database_backup_legacy_paths_and_cleanup_ineligible(self):
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp);out=root/'out';out.mkdir();source=root/'source.dat';source.write_bytes(b'SYNTHETIC')
            old=OldEngine(root/'state',start_worker=False);old.settings(dict(output_root=str(out),quality=23,video_codec='h264'))
            j=old.create_job(dict(source_path=str(source),collection='Legacy',kind='film',titles=[dict(id=0,name='Existing_Name')],stop_after='scan'));j['state']='paused';old._job_save(j);old.close()
            e=Engine(root/'state',start_worker=False)
            self.assertEqual(e.settings()['preset_id'],'legacy');self.assertEqual(e.settings()['quality'],23);self.assertEqual(e.job(j['id'])['output_path'],j['output_path']);self.assertEqual(e.job(j['id'])['cleanup_status'],'ineligible_legacy');self.assertTrue(list((root/'state').glob('migration-v1-*.sqlite3')));e.close()

if __name__=='__main__':unittest.main()
