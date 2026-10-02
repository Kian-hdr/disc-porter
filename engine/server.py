#!/usr/bin/env python3
"""Authenticated loopback-only versioned archive API."""
import argparse
import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from engine.service import Engine,Conflict
from engine.core import ArchiveError


def serve(state_dir):
    engine=Engine(state_dir);token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,status,value):
            data=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        def handle_request(self):
            if self.headers.get('Origin')or self.headers.get('Host')!='127.0.0.1:'+str(server.server_port)or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):return self.respond(403,{'error':'Loopback bearer authentication required; browser origins rejected'})
            try:
                data={}
                if self.command in('POST','PATCH','DELETE'):
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<=size<=262144:raise ArchiveError('Request exceeds body limit')
                    data=json.loads(self.rfile.read(size)or b'{}')
                    if not isinstance(data,dict):raise ArchiveError('Body must be a JSON object')
                split=urlsplit(self.path);path=split.path.strip('/').split('/');query=parse_qs(split.query)
                method=self.command;result=None
                if method=='GET':
                    if path==['status']:result=engine.status()
                    elif path==['settings']:result=engine.settings()
                    elif path==['capabilities']:result=engine.capabilities()
                    elif path==['presets']:result={'presets':engine.presets()}
                    elif path==['profiles']:result={'profiles':engine.profiles()}
                    elif path==['library']:result=engine.library()
                    elif path==['exports']:result=engine.exports()
                    elif path==['events']:result=engine.events(query.get('after',[0])[0],query.get('limit',[100])[0])
                    elif path==['metadata','credential']:result=engine.metadata_credential()
                    elif len(path)==2 and path[0]=='jobs':result=engine.job(path[1])
                    elif len(path)==2 and path[0]=='report':result=engine.report(path[1])
                    elif len(path)==2 and path[0]=='scans':result=engine.scan_record(path[1])
                    elif len(path)==2 and path[0]=='exports':result=engine.export(path[1])
                elif method=='POST':
                    if path==['scan']:result={'discs':engine.scan(auto_start=False)}
                    elif path==['scans']:result=engine.start_scan()
                    elif path==['settings']:result=engine.settings(data,legacy=True)
                    elif path==['presets']:result=engine.create_preset(data)
                    elif path==['jobs','preview']:result=engine.preview_start(data)
                    elif path==['jobs']:result=engine.create_job(data)
                    elif path==['profiles']:result=engine.profile(data)
                    elif path==['exports']:result=engine.create_export(data)
                    elif path==['identify']:result=engine.identify(data)
                    elif path==['metadata','credential']:result=engine.metadata_credential(data)
                    elif path==['queue','action']:result=engine.queue_action(data)
                    elif len(path)==3 and path[0]=='jobs':
                        if path[2]=='action':result=engine.action(path[1],data)
                        elif path[2]=='plan-preview':result=engine.plan_preview(path[1],data)
                        elif path[2]=='acceptance':result=engine.acceptance(path[1],data)
                        elif path[2]=='cleanup-preview':result=engine.cleanup_preview(path[1])
                        elif path[2]=='cleanup':result=engine.cleanup(path[1],data)
                    elif len(path)==3 and path[0]=='exports'and path[2]=='action':result=engine.export_action(path[1],data)
                    elif path==['shutdown']:
                        engine.close();result={'accepted':True};threading.Thread(target=server.shutdown,daemon=True).start()
                elif method=='PATCH':
                    if path==['settings']:result=engine.settings(data)
                    elif len(path)==2 and path[0]=='presets':result=engine.edit_preset(path[1],data)
                    elif len(path)==2 and path[0]=='profiles':result=engine.edit_profile(path[1],data)
                    elif len(path)==2 and path[0]=='jobs':result=engine.edit_plan(path[1],data)
                elif method=='DELETE':
                    if path==['metadata','credential']:result=engine.metadata_credential(delete=True)
                    elif len(path)==2 and path[0]=='presets':result=engine.edit_preset(path[1],data,delete=True)
                    elif len(path)==2 and path[0]=='profiles':result=engine.edit_profile(path[1],data,delete=True)
                if result is None:return self.respond(404,{'error':'Route not found'})
                return self.respond(200,result)
            except Conflict as e:return self.respond(409,dict(error=str(e),code=e.code,current_revision=e.current_revision))
            except(ArchiveError,OSError,ValueError,KeyError,TypeError)as e:return self.respond(409 if isinstance(e,ArchiveError)else 400,{'error':str(e)})
            except Exception:return self.respond(500,{'error':'Internal engine error; durable state retained'})
        do_GET=handle_request;do_POST=handle_request;do_PATCH=handle_request;do_DELETE=handle_request
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);endpoint=Path(state_dir)/'endpoint.json';temp=endpoint.with_suffix('.tmp');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w')as f:json.dump(dict(url='http://127.0.0.1:'+str(server.server_port),token=token),f);f.flush();os.fsync(f.fileno())
    os.chmod(temp,0o600);os.replace(temp,endpoint);server.serve_forever();server.server_close();endpoint.unlink(missing_ok=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--state-dir',required=True);args=parser.parse_args();serve(args.state_dir)
