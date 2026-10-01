import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from engine.core import Engine, ArchiveError, snapshot, digest

FFMPEG = '/opt/homebrew/bin/ffmpeg'
FFPROBE = '/opt/homebrew/bin/ffprobe'

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out = self.root / 'output'; self.out.mkdir()
        self.engine = Engine(self.root / 'state', tools=dict(ffmpeg=FFMPEG, ffprobe=FFPROBE, makemkv=None), start_worker=False)
        self.engine.settings(dict(output_root=str(self.out), video_codec='h264'))
        self.source = self.root / 'source.mkv'
        sub = self.root / 'sub.srt'; sub.write_text('1\n00:00:00,100 --> 00:00:00,900\nSynthetic subtitle\n')
        subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=24:duration=1', '-f', 'lavfi', '-i', 'sine=frequency=400:duration=1', '-f', 'lavfi', '-i', 'sine=frequency=600:duration=1', '-i', str(sub), '-map', '0:v', '-map', '1:a', '-map', '2:a', '-map', '3:s', '-c:v', 'libx264', '-c:a', 'flac', '-c:s', 'srt', '-metadata:s:a:0', 'language=eng', '-metadata:s:a:1', 'language=deu', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', str(self.source)], check=True)
    def tearDown(self):
        for j in self.engine.jobs():
            if j['state'] in ('running', 'queued'):
                j['state'] = 'paused'; self.engine._job_save(j)
        self.engine.close(); self.temp.cleanup()
    def new(self, stop='complete'):
        return self.engine.create_job(dict(source_path=str(self.source), collection='Synthetic Collection', kind='film', titles=[dict(id=0, name='Synthetic Film')], stop_after=stop))
    def run_job(self, job):
        self.engine.run_job(job['id']); return self.engine.job(job['id'])
    def test_real_encode_all_checkpoints_and_streams(self):
        j = self.run_job(self.new())
        self.assertEqual(j['state'], 'completed', j['message'])
        a = j['artifacts'][0]; probe = self.engine.probe(a['final'])
        self.assertEqual([s['tags']['language'] for s in probe['streams'] if s['codec_type']=='audio'], ['eng', 'deu'])
        self.assertEqual(sum(s['codec_type']=='subtitle' for s in probe['streams']), 1)
        self.assertEqual(digest(a['original']), a['original_sha256'])
        self.assertTrue(Path(a['original']).is_file())
        self.assertEqual(self.engine.report(j['id'])['tv_acceptance'], 'pending')
    def test_pause_next_resume_and_recovery(self):
        j = self.run_job(self.new('scan')); self.assertEqual(j['checkpoint'], 'scan')
        j = self.run_job(self.engine.action(j['id'], dict(action='next_checkpoint')))
        self.assertEqual(j['checkpoint'], 'acquire'); self.assertEqual(j['state'], 'paused')
        j['state']='running'; self.engine._job_save(j)
        self.engine.db.close(); self.engine.lockfile.close()
        self.engine = Engine(self.root/'state', tools=dict(ffmpeg=FFMPEG, ffprobe=FFPROBE, makemkv=None), start_worker=False)
        self.assertEqual(self.engine.job(j['id'])['state'], 'paused')
        self.source.unlink() # Once acquired, original disc/source is no longer required.
        j = self.run_job(self.engine.action(j['id'], dict(action='resume', stop_after='complete')))
        self.assertEqual(j['state'], 'completed', j['message'])
    def test_no_overwrite(self):
        j = self.run_job(self.new('verify')); self.assertEqual(j['checkpoint'], 'verify', j['message'])
        final = Path(j['output_path'])/'Synthetic_Film.mp4'; final.write_bytes(b'USER FILE')
        j = self.run_job(self.engine.action(j['id'], dict(action='next_checkpoint')))
        self.assertEqual(j['state'], 'blocked'); self.assertEqual(final.read_bytes(), b'USER FILE')
    def test_missing_source_and_destination(self):
        j=self.new(); self.source.rename(self.root/'moved.mkv')
        j=self.run_job(j); self.assertEqual(j['state'],'blocked')
        self.assertFalse(Path(j['output_path']).exists())
        (self.root/'moved.mkv').rename(self.source)
        self.engine.action(j['id'],dict(action='resume'))
        self.out.rename(self.root/'moved-output')
        j=self.run_job(j); self.assertEqual(j['state'],'blocked'); self.assertFalse(self.out.exists())
    def test_wrong_source(self):
        j=self.new(); self.source.write_bytes(b'changed source')
        j=self.run_job(j); self.assertEqual(j['state'],'blocked')
    def test_owner_lock(self):
        with self.assertRaises(ArchiveError): Engine(self.root/'state',start_worker=False)
    def test_unknown_ambiguous_mapping(self):
        disc = self.root/'disc'; (disc/'VIDEO_TS').mkdir(parents=True); (disc/'VIDEO_TS'/'VTS_01_0.IFO').write_bytes(b'SYNTHETIC')
        fp,_=snapshot(disc)
        with self.assertRaises(ArchiveError): self.engine.create_job(dict(source_path=str(disc), disc_id=fp, collection='Test', kind='film', titles=[dict(id=0,name='Test')]))
        (disc/'BDMV').mkdir()
        with self.assertRaises(ArchiveError): snapshot(disc)
        with self.assertRaises(ArchiveError): self.new_bad_titles()
    def new_bad_titles(self):
        return self.engine.create_job(dict(source_path=str(self.source),collection='C',kind='film',titles=[dict(id=0,name='X'),dict(id=0,name='Y')]))
    def test_concurrency_and_pause_request(self):
        j=self.new(); self.engine.action(j['id'],dict(action='pause_after_checkpoint'))
        with self.assertRaises(ArchiveError): self.new()
        j=self.run_job(j); self.assertEqual(j['checkpoint'],'scan'); self.assertEqual(j['state'],'paused')
    def test_acquisition_intent_recovery_and_no_original_overwrite(self):
        j=self.new('acquire')
        real=self.engine._commit_original
        def interruption(job,artifact): raise ArchiveError('Synthetic crash between intent and link')
        self.engine._commit_original=interruption
        j=self.run_job(j); self.assertEqual(j['state'],'blocked'); self.assertFalse(j['artifacts'][0]['acquisition_committed'])
        self.engine._commit_original=real
        j=self.run_job(self.engine.action(j['id'],dict(action='resume')))
        self.assertEqual(j['checkpoint'],'acquire',j['message']); self.assertTrue(j['artifacts'][0]['acquisition_committed'])
        # A separate job cannot replace an earlier watchable original.
        original=Path(j['artifacts'][0]['original']); previous=digest(original)
        other=self.run_job(self.new('acquire'))
        self.assertEqual(other['state'],'blocked'); self.assertEqual(digest(original),previous)
    def test_full_decode_failure_retains_original_and_candidate(self):
        j=self.run_job(self.new('encode')); self.assertEqual(j['checkpoint'],'encode',j['message'])
        a=j['artifacts'][0]; Path(a['candidate']).write_bytes(b'CORRUPTED SYNTHETIC CANDIDATE')
        j=self.run_job(self.engine.action(j['id'],dict(action='resume',stop_after='complete')))
        self.assertEqual(j['state'],'blocked'); self.assertTrue(Path(a['original']).exists()); self.assertTrue(Path(a['candidate']).exists())
    def test_hevc_real_main10_keeps_depth(self):
        # Synthetic 10-bit source exercises Main10 rather than reducing bit depth.
        ten=self.root/'tenbit.mkv'
        subprocess.run([FFMPEG,'-v','error','-i',str(self.source),'-map','0','-c:v','libx265','-x265-params','pools=2:log-level=error','-pix_fmt','yuv420p10le','-c:a','copy','-c:s','copy',str(ten)],check=True)
        self.source=ten
        self.engine.settings(dict(video_codec='hevc'))
        j=self.run_job(self.new())
        self.assertEqual(j['state'],'completed',j['message'])
        streams=self.engine.probe(j['artifacts'][0]['final'])['streams']
        video=next(s for s in streams if s['codec_type']=='video')
        self.assertEqual(video['pix_fmt'],'yuv420p10le'); self.assertEqual(video['codec_tag_string'],'hvc1')
    def test_fake_extraction(self):
        disc=self.root/'disc'; (disc/'BDMV').mkdir(parents=True); (disc/'BDMV'/'index.bdmv').write_bytes(b'SYNTHETIC CONTROLS')
        fp,_=snapshot(disc)
        fake=self.root/'fake-makemkv'
        fake.write_text('#!/usr/bin/env python3\nimport sys,shutil\nfrom pathlib import Path\na=sys.argv\nif "mkv" in a:\n shutil.copyfile('+repr(str(self.source))+',Path(a[-1])/"title.mkv")\nelse:\n print('+repr('DRV:0,2,999,0,"Synthetic drive","Synthetic disc","'+str(disc)+'"')+')\n print(\'TINFO:0,9,0,"0:00:01"\')\n print(\'SINFO:0,0,1,0,"Video"\')\n print(\'SINFO:0,1,1,0,"Audio"\')\n print(\'SINFO:0,1,3,0,"eng"\')\n print(\'SINFO:0,2,1,0,"Audio"\')\n print(\'SINFO:0,2,3,0,"deu"\')\n print(\'SINFO:0,3,1,0,"Subtitles"\')\n')
        fake.chmod(0o700); self.engine.tools['makemkv']=str(fake)
        self.engine.scan()
        p=self.engine.profile(dict(disc_id=fp,collection='Synthetic Disc',kind='film',titles=[dict(id=0,name='Known Synthetic Film')]))
        j=self.engine.create_job(dict(p,source_path=str(disc),stop_after='acquire'))
        j=self.run_job(j); self.assertEqual(j['checkpoint'],'acquire',j['message'])
        self.assertTrue(Path(j['artifacts'][0]['original']).exists())
        self.assertEqual(len([s for s in self.engine.probe(j['artifacts'][0]['original'])['streams'] if s['codec_type']=='audio']),2)

if __name__=='__main__': unittest.main()
