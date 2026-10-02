"""Disposable frozen-runtime and codec checks. No app install, discs or user media."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOKEN='synthetic-packaging-token'
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.headers.get('Authorization')!='Bearer '+TOKEN:
            self.send_response(403);self.end_headers();return
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps({'api_version':2,'engine_version':'0.2.0','settings':{'revision':1,'auto_start':False},'jobs':[],'discs':[],'safe_to_disconnect':True,'message':'Disposable fake HTTP endpoint'}).encode())
async def test(helper,tools,arch):
    rows=[]
    with tempfile.TemporaryDirectory(prefix='disc-porter-packaging-') as temp:
        endpoint=Path(temp)/'endpoint.json'
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        endpoint.write_text(json.dumps({'url':'http://127.0.0.1:'+str(http.server_port),'token':TOKEN}));endpoint.chmod(0o600)
        params=StdioServerParameters(command=str(helper),args=['mcp'],env={'PATH':'/usr/bin:/bin','HOME':os.environ['HOME'],'PYTHONNOUSERSITE':'1','DISC_ARCHIVE_ENDPOINT_FILE':str(endpoint)})
        try:
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    init=await session.initialize();listed=await session.list_tools()
                    assert init.serverInfo.name=='disc_porter_mcp'
                    reply=await session.call_tool('disc_porter_status',{})
                    assert not reply.isError,reply.content
                    assert reply.structuredContent['safe_to_disconnect'] is True
                    rows.append({'check':'frozen_sdk_initialize_list_status','passed':True,'tool_count':len(listed.tools)})
        finally:
            await asyncio.to_thread(http.shutdown);http.server_close()
        subprocess.run([str(helper),'supervise',str(os.getpid()),'--','/usr/bin/true'],check=True)
        rows.append({'check':'frozen_supervisor_dispatch','passed':True})
        for codec,pixel in [('libx264','yuv420p'),('libx265','yuv420p'),('libx265','yuv420p10le')]:
            target=Path(temp)/(codec+'-'+pixel+'.mp4')
            cmd=[str(tools/'ffmpeg'),'-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=64x64:rate=10','-t','0.3','-an','-c:v',codec,'-pix_fmt',pixel,'-preset','ultrafast']
            if codec=='libx265':cmd+=['-x265-params','log-level=error:pools=none']
            subprocess.run(cmd+[str(target)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            result=json.loads(subprocess.check_output([str(tools/'ffprobe'),'-v','error','-show_streams','-of','json',str(target)],text=True))
            assert result['streams'][0]['codec_name']==('h264' if codec=='libx264' else 'hevc')
            assert result['streams'][0]['pix_fmt']==pixel
            rows.append({'check':'synthetic_encode_probe','encoder':codec,'pixel_format':pixel,'passed':True})
        filters=subprocess.check_output([str(tools/'ffmpeg'),'-hide_banner','-filters'],text=True,stderr=subprocess.DEVNULL)
        if ' subtitles ' in filters:
            caption=Path(temp)/'caption.srt';caption.write_text('1\n00:00:00,000 --> 00:00:01,000\nDisc Porter fixture\n')
            baseline=subprocess.check_output([str(tools/'ffmpeg'),'-nostdin','-v','error','-f','lavfi','-i','color=black:size=640x360:rate=10','-frames:v','1','-f','md5','-'],stderr=subprocess.PIPE)
            burned=subprocess.check_output([str(tools/'ffmpeg'),'-nostdin','-v','error','-f','lavfi','-i','color=black:size=640x360:rate=10','-vf',"subtitles=filename="+str(caption)+":force_style='FontName=Helvetica'",'-frames:v','1','-f','md5','-'],stderr=subprocess.PIPE)
            assert baseline!=burned,'Subtitle render must change decoded pixel bytes'
            rows.append({'check':'synthetic_subtitle_burn_coretext','passed':True})
        else:
            rows.append({'check':'synthetic_subtitle_burn_coretext','passed':False,'detail':'subtitles filter unavailable'})
        for codec in ['h264_videotoolbox','hevc_videotoolbox']:
            target=Path(temp)/(codec+'.mp4')
            cmd=[str(tools/'ffmpeg'),'-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=640x360:rate=10','-t','0.3','-an','-c:v',codec,'-b:v','600k',str(target)]
            reply=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
            rows.append({'check':'synthetic_hardware_encode','encoder':codec,'passed':reply.returncode==0,'detail':reply.stderr[-800:] if reply.returncode else ''})
    return {'architecture':arch,'execution_environment':'native_arm64' if arch=='arm64' else 'Rosetta on Apple Silicon; not physical Intel validation','checks':rows}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--helper',type=Path,required=True);p.add_argument('--tools',type=Path,required=True);p.add_argument('--architecture',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=asyncio.run(test(a.helper.resolve(),a.tools.resolve(),a.architecture));a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
