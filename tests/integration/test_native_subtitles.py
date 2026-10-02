"""Actual Mac AVPlayer selectability after explicit MP4 subtitle-default edit."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from engine.mp4 import set_subtitle_defaults

@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc') and shutil.which('ffmpeg'), 'Mac Swift/FFmpeg required')
class NativeSubtitleTests(unittest.TestCase):
    def test_patched_track_remains_selectable_and_delivers_cue(self):
        with tempfile.TemporaryDirectory(prefix='disc-porter-avkit-') as folder:
            root = Path(folder)
            srt = root / 'fixture.srt'
            cue = 'DISC_PORTER_SYNTHETIC_CUE'
            srt.write_text('1\n00:00:00,100 --> 00:00:01,900\n' + cue + '\n')
            original = root / 'original.mp4'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=blue:size=160x96:rate=24:duration=3',
                '-i',str(srt),'-map','0:v','-map','1:s','-c:v','libx264','-c:s','mov_text',
                '-metadata:s:s:0','language=eng','-movflags','+faststart',str(original)],check=True)
            patched = root / 'patched.mp4'
            shutil.copyfile(original, patched)
            set_subtitle_defaults(patched,[False])
            binary = root / 'inspect'
            source = Path(__file__).with_name('SubtitleSelectionProbe.swift')
            subprocess.run(['swiftc','-parse-as-library',str(source),'-o',str(binary)],check=True)
            for clip in (original,patched):
                result = subprocess.run([str(binary),str(clip)],capture_output=True,text=True,check=True,timeout=15)
                data = json.loads(result.stdout)
                self.assertTrue(data['ready'],data)
                self.assertEqual(data['error'],'')
                self.assertGreaterEqual(data['options'],1)
                self.assertIn(cue,data['cues'])
                extract = subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(clip),'-map','0:s:0','-f','srt','-'],capture_output=True,text=True,check=True)
                self.assertIn(cue,extract.stdout)

if __name__ == '__main__': unittest.main()
