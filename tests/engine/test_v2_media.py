import unittest
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).parent))
from test_v2 import V2Tests,FFMPEG
from engine.core import ArchiveError
from engine.media import build,select_streams

class MediaTests(V2Tests):
    # Reuse only fixture helpers; inherited tests are suppressed to avoid duplicating the suite.
    test_async_scan_and_local_identification=None
    test_disconnect_waiting_and_preflight=None
    test_original_mode_and_plan_edit=None
    test_pipeline_surround_subtitles_sidecars_export_cleanup=None
    test_schema_presets_conflicts_idempotency=None
    test_single_title_next_each_phase=None
    test_multi_title_next_checkpoint_preserves_full_plan=None
    def test_sdr_resize_frame_deinterlace_and_stereo_transforms(self):
        j=self.e.create_job(self.request(overrides=dict(resolution='480p',frame_rate='30',deinterlace='frame',aspect='square',audio_channels='stereo',audio_codec='ac3')));j=self.execute(j)
        self.assertEqual(j['state'],'completed',j['message']);a=j['artifacts'][0];probe=self.e.probe(a['final'])
        v=next(s for s in probe['streams']if s['codec_type']=='video');self.assertEqual(v['height'],480);self.assertEqual(v['r_frame_rate'],'30/1')
        self.assertEqual([s['channels']for s in probe['streams']if s['codec_type']=='audio'],[1,2]);self.assertIn('deinterlace',{t['kind']for t in a['transforms']});self.assertIn('audio_channels',{t['kind']for t in a['transforms']})
    def test_selected_copy_audio_and_forced_default_subtitles_mkv(self):
        title=dict(id=0,name='Selected',audio_streams=[1,2],subtitle_streams=[3],default_audio_stream=2,default_subtitle_stream=3,forced_subtitle_streams=[3])
        request=self.request(overrides=dict(output_container='mkv',audio_codec='copy',audio_policy='selected',subtitle_policy='copy'));request['titles']=[title]
        j=self.execute(self.e.create_job(request));self.assertEqual(j['state'],'completed',j['message'])
        probe=self.e.probe(j['artifacts'][0]['final']);audio=[s for s in probe['streams']if s['codec_type']=='audio'];sub=next(s for s in probe['streams']if s['codec_type']=='subtitle')
        self.assertEqual(audio[0]['tags']['language'],'deu');self.assertEqual(audio[0]['codec_name'],'flac');self.assertEqual(sub['disposition']['forced'],1);self.assertEqual(sub['disposition']['default'],1)
    def test_forced_default_text_subtitles_mp4(self):
        request=self.request();request['titles'][0].update(default_subtitle_stream=3,forced_subtitle_streams=[3])
        j=self.execute(self.e.create_job(request));self.assertEqual(j['state'],'completed',j['message']);sub=next(s for s in self.e.probe(j['artifacts'][0]['final'])['streams']if s['codec_type']=='subtitle')
        self.assertEqual(sub['disposition']['forced'],1);self.assertEqual(sub['disposition']['default'],1)
    def test_depth_downconversion_requires_preview_confirmation(self):
        ten=self.root/'ten.mkv';subprocess.run([FFMPEG,'-v','error','-i',str(self.source),'-map','0','-c:v','libx265','-x265-params','pools=2:log-level=error','-pix_fmt','yuv420p10le','-c:a','copy','-c:s','copy',str(ten)],check=True);self.source=ten
        request=self.request(preset_id='compatibility');preview=self.e.preview_start(request);self.assertTrue(preview['requires_confirmation'])
        with self.assertRaises(ArchiveError):self.e.create_job(request)
        request.update(confirm_transforms=True,expected_plan_fingerprint=preview['plan_fingerprint'])
        j=self.execute(self.e.create_job(request));self.assertEqual(j['state'],'completed',j['message']);self.assertEqual(j['artifacts'][0]['expected_video']['pix_fmt'],'yuv420p')
    def test_cpu_threads_auto_and_explicit_pools(self):
        probe=self.e.probe(self.source);recipe=dict(self.e.settings(),video_codec='hevc')
        auto,_=build(probe,recipe,{},str(self.source),str(self.out/'auto.mp4'),FFMPEG)
        self.assertEqual(auto[auto.index('-x265-params')+1],'log-level=error')
        explicit,_=build(probe,dict(recipe,cpu_threads=1),{},str(self.source),str(self.out/'limited.mp4'),FFMPEG)
        self.assertEqual(explicit[explicit.index('-threads')+1],'1');self.assertEqual(explicit[explicit.index('-x265-params')+1],'pools=1:log-level=error')
    def test_unknown_language_preserves_independent_tracks_no_hidden_english_default(self):
        probe=self.e.probe(self.source);recipe=self.e.settings()
        for s in probe['streams']:
            if s['codec_type']=='audio':s['tags']['language']='und';s['disposition']['default']=s['index']==2
        selected,_,_=select_streams(probe,recipe,{})
        self.assertEqual([s['index']for s in selected],[2,1])
        hdr=deepcopy(probe);v=next(s for s in hdr['streams']if s['codec_type']=='video');v['color_transfer']='smpte2084'
        with self.assertRaises(ArchiveError):build(hdr,recipe,{},str(self.source),str(self.out/'HDR.mp4'),FFMPEG)
        with self.assertRaises(ArchiveError):self.e.settings(dict(cleanup_policy='delete_verified',preserve_original_audio=False,expected_revision=recipe['revision']))

del V2Tests
if __name__=='__main__':unittest.main()
