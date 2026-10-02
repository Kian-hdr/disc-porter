"""Start only a disposable frozen engine and exercise version/status/disconnect gates."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

p=argparse.ArgumentParser();p.add_argument('--helper',type=Path,required=True);p.add_argument('--architecture',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
with tempfile.TemporaryDirectory(prefix='disc-porter-frozen-engine-') as temp:
    state=Path(temp)/'state';state.mkdir()
    log=Path(temp)/'engine.log'
    with log.open('wb') as handle:
        env={'PATH':'/usr/bin:/bin','HOME':os.environ['HOME'],'DISC_PORTER_STATE_DIR':str(state),'PYTHONNOUSERSITE':'1'}
        child=subprocess.Popen([str(a.helper.resolve()),'serve','--state-dir',str(state)],env=env,stdout=handle,stderr=handle)
        def request(path,payload=None):
            endpoint=json.loads((state/'endpoint.json').read_text())
            req=urllib.request.Request(endpoint['url']+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Authorization':'Bearer '+endpoint['token'],'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=15) as reply:return json.load(reply)
        try:
            deadline=time.monotonic()+25
            while not (state/'endpoint.json').exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.1)
            if not (state/'endpoint.json').exists():raise RuntimeError('Frozen engine did not publish its endpoint: '+log.read_text()[-3000:])
            caps=request('/capabilities');status=request('/status')
            assert caps['api_version']==2 and caps['engine_version']=='0.2.0',caps
            assert status['api_version']==2 and len(status['jobs'])==0,status.get('message')
            assert status['settings']['auto_start'] is False
            assert status['settings']['cleanup_policy']=='keep'
            async def mcp_roundtrip():
                params=StdioServerParameters(command=str(a.helper.resolve()),args=['mcp'],env={**env,'DISC_ARCHIVE_ENDPOINT_FILE':str(state/'endpoint.json')})
                async with stdio_client(params) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        tools=await session.list_tools();assert len(tools.tools)==43
                        result=await session.call_tool('disc_porter_status',{})
                        assert not result.isError,result.content
                        assert result.structuredContent['api_version']==2
                        assert result.structuredContent['settings']['auto_start'] is False
            asyncio.run(mcp_roundtrip())
            fenced=request('/queue/action',{'action':'prepare_disconnect'})
            status=request('/status');assert status['safe_to_disconnect'] is True
            shutdown=request('/shutdown',{})
            assert shutdown['accepted'] is True
            child.wait(timeout=20)
            assert child.returncode==0,child.returncode
            record={'architecture':a.architecture,'api_version':2,'engine_version':'0.2.0','checks':{'frozen_engine_start':True,'actual_engine_frozen_mcp_43_tool_status':True,'empty_queue':True,'automation_disabled':True,'cleanup_keep_default':True,'disconnect_fence_safe':True,'owned_clean_shutdown':True},'environment':'minimal PATH; disposable state; no imported media or acquisition; no GUI launch'}
            a.output.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
        finally:
            if child.poll() is None:
                try:request('/shutdown',{});child.wait(timeout=20)
                except Exception:
                    # Only this freshly spawned disposable engine, never the user's owner.
                    child.terminate();child.wait(timeout=10)
