import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
from engine.service import Engine,Conflict
from engine.core import ArchiveError,digest
from engine.schema import DEFAULTS

FFMPEG='/opt/homebrew/bin/ffmpeg';FFPROBE='/opt/homebrew/bin/ffprobe'

class V2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.out=self.root/'out';self.out.mkdir()
        self.e=Engine(self.root/'state',tools=dict(ffmpeg=FFMPEG,ffprobe=FFPROBE,makemkv=None),start_worker=False)
        s=self.e.settings();self.e.settings(dict(output_root=str(self.out),reserve_bytes=0,video_codec='h264',on_battery='run',expected_revision=s['revision']))
        self.source=self.root/'source.mkv';self.sub=self.root/'text.srt';self.sub.write_text('1\n00:00:00,100 --> 00:00:00,900\nSynthetic cue\n')
        subprocess.run([FFMPEG,'-v','error','-f','lavfi','-i','testsrc2=size=160x96:rate=24:duration=1','-f','lavfi','-i','sine=duration=1','-f','lavfi','-i','anullsrc=channel_layout=5.1:sample_rate=48000','-i',str(self.sub),'-map','0:v','-map','1:a','-map','2:a','-map','3:s','-t','1','-c:v','libx264','-c:a','flac','-c:s','srt','-metadata:s:a:0','language=eng','-metadata:s:a:1','language=deu','-metadata:s:s:0','language=eng','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709',str(self.source)],check=True)
    def tearDown(self):
        for j in self.e.jobs():
            if j['state']in('running','queued'):j['state']='paused';self.e._job_save(j)
        for thread in self.e.transfer_threads.values():thread.join(timeout=10)
        self.e.close();self.temp.cleanup()
    def request(self,**extra):return dict(source_path=str(self.source),collection='Synthetic',kind='film',titles=[dict(id=0,name='Sample')],stop_after='complete',expected_settings_revision=self.e.settings()['revision'],**extra)
    def run(self,result=None):
        # unittest.TestCase uses run; retain framework method.
        return super().run(result)
    def execute(self,job):self.e.run_job(job['id']);return self.e.job(job['id'])
    def test_schema_presets_conflicts_idempotency(self):
        s=self.e.settings();self.assertEqual(s['schema_version'],2);self.assertEqual(s['languages'],[])
        with self.assertRaises(Conflict):self.e.settings(dict(quality=30,expected_revision=s['revision']-1))
        p=self.e.create_preset(dict(name='Custom',base_id='balanced'));p=self.e.edit_preset(p['id'],dict(expected_revision=1,settings=dict(quality=22)))
        self.assertEqual(p['revision'],2)
        with self.assertRaises(ArchiveError):self.e.edit_preset('balanced',dict(expected_revision=1,settings=dict(quality=1)))
        r=self.request(idempotency_key='test');j=self.e.create_job(r);self.assertEqual(self.e.create_job(r)['id'],j['id'])
        r['collection']='Different'
        with self.assertRaises(ArchiveError):self.e.create_job(r)
    def test_pipeline_surround_subtitles_sidecars_export_cleanup(self):
        j=self.e.create_job(self.request(overrides=dict(cleanup_policy='delete_verified')));j=self.execute(j)
        self.assertEqual(j['state'],'completed',j['message']);self.assertEqual(j['cleanup_status'],'deleted',j['message'])
        a=j['artifacts'][0];self.assertTrue(self.source.exists());self.assertFalse(Path(a['original']).exists());self.assertFalse(self.e.report(j['id'])['originals_retained'])
        probe=self.e.probe(a['final']);audio=[s for s in probe['streams']if s['codec_type']=='audio'];self.assertEqual([s['channels']for s in audio],[1,6]);self.assertEqual(len(a['sidecars']),3)
        destination=self.root/'export';destination.mkdir();t=self.e.create_export(dict(job_id=j['id'],destination=str(destination),expected_revision=j['revision']))
        self.e.transfer_threads[t['id']].join(timeout=15);t=self.e.export(t['id']);self.assertEqual(t['state'],'completed',t['message'])
        self.assertTrue(all(digest(f['destination'])==f['sha256']for f in t['files']));self.assertEqual(self.e.library()['total'],1)
        with self.assertRaises(ArchiveError):self.e.create_export(dict(job_id=j['id'],destination=str(destination)))
    def test_original_mode_and_plan_edit(self):
        j=self.e.create_job(self.request(preset_id='original'));j=self.execute(j);self.assertEqual(j['state'],'completed',j['message'])
        self.assertEqual(digest(j['artifacts'][0]['final']),j['artifacts'][0]['original_sha256']);self.assertFalse(self.e.cleanup_preview(j['id'])['eligible'])
        edited=self.e.edit_plan(j['id'],dict(expected_revision=j['revision'],overrides=dict(mode='transcode',video_codec='h264',audio_codec='aac',subtitle_policy='text',output_container='mp4')))
        self.assertEqual(edited['generation'],2);self.assertTrue(edited['generations'][0]['artifacts'][0]['final'])
        edited=self.e.action(edited['id'],dict(action='resume',expected_revision=edited['revision']));edited=self.execute(edited)
        self.assertEqual(edited['state'],'completed',edited['message']);self.assertTrue(edited['artifacts'][0]['final'].endswith('_g2.mp4'))
    def test_disconnect_waiting_and_preflight(self):
        request=self.request();preview=self.e.preview_start(request);self.assertTrue(preview['can_apply'])
        j=self.e.create_job(request);status=self.e.queue_action(dict(action='prepare_disconnect'));self.assertTrue(status['disconnect_fenced']);self.assertEqual(self.e.job(j['id'])['state'],'paused')
        with self.assertRaises(ArchiveError):self.e.create_job(request)
        self.e.queue_action(dict(action='resume_archiving'));self.assertEqual(self.e.job(j['id'])['state'],'queued')
        self.out.rename(self.root/'absent');j=self.execute(j);self.assertEqual(j['state'],'waiting_destination',j['message'])
    def test_async_scan_and_local_identification(self):
        s=self.e.start_scan();self.assertEqual(s['state'],'queued')
        for t in self.e.runtime_threads:t.join(timeout=5)
        self.assertEqual(self.e.scan_record(s['id'])['state'],'completed')
        info=self.e.identify(dict(provider='local',source_path=str(self.source)));self.assertTrue(info['requires_confirmation']);self.assertEqual(len(info['technical_inventory']),4)


    def test_multi_title_next_checkpoint_preserves_full_plan(self):
        from engine.core import snapshot
        disc=self.root/'fake-disc';(disc/'BDMV').mkdir(parents=True);(disc/'BDMV'/'index.bdmv').write_bytes(b'SYNTHETIC CONTROL')
        fake=self.root/'fake-makemkv'
        drv='DRV:0,2,999,0,"Synthetic","Synthetic","'+str(disc)+'"'
        script="""#!/usr/bin/env python3
import sys,shutil
from pathlib import Path
a=sys.argv
if "mkv"in a:shutil.copyfile(%r,Path(a[-1])/"title.mkv")
else:
 print(%r)
 for t in (0,1):
  print(f'TINFO:{t},9,0,"0:00:01"')
  for s,typ,lang in [(0,"Video",""),(1,"Audio","eng"),(2,"Audio","deu"),(3,"Subtitles","eng")]:
   print(f'SINFO:{t},{s},1,0,"{typ}"')
   if lang:print(f'SINFO:{t},{s},3,0,"{lang}"')
"""%(str(self.source),drv)
        fake.write_text(script);fake.chmod(0o700);self.e.tools['makemkv']=str(fake);self.e.scan()
        fp,_=snapshot(disc)
        req=dict(source_path=str(disc),disc_id=fp,collection='Two Titles',kind='extras',titles=[dict(id=0,name='Alpha'),dict(id=1,name='Beta')],expected_settings_revision=self.e.settings()['revision'])
        j=self.e.create_job(req);self.e.action(j['id'],dict(action='pause_after_checkpoint',expected_revision=j['revision']))
        for phase in ['scan','acquire']:
            for title_id in (0,1):
                j=self.e.job(j['id']);j=self.e.action(j['id'],dict(action='next_checkpoint',expected_revision=j['revision']));j=self.execute(j)
                self.assertEqual(j['checkpoint_detail'],dict(phase=phase,title_id=title_id),j['message']);self.assertEqual(len(j['titles']),2)
                self.assertEqual(j['checkpoint'],phase if title_id==1 else ''if phase=='scan'else'scan')
        self.assertEqual(len(j['artifacts']),2);self.assertEqual(len(j['ledger']),2)
    def test_single_title_next_each_phase(self):
        j=self.e.create_job(self.request());j=self.e.action(j['id'],dict(action='pause_after_checkpoint',expected_revision=j['revision']))
        for phase in ['scan','acquire','encode','verify','complete']:
            j=self.e.action(j['id'],dict(action='next_checkpoint',expected_revision=j['revision']));j=self.execute(j)
            self.assertEqual(j['checkpoint'],phase,j['message']);self.assertEqual(j['checkpoint_detail']['phase'],phase)
            self.assertEqual(j['state'],'completed'if phase=='complete'else'paused')

if __name__=='__main__':unittest.main()
