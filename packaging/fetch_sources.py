"""Fetch locked source archives; no upstream install scripts are run."""
import hashlib
import json
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parent
out=root/'sources';out.mkdir(exist_ok=True)
for source in json.loads((root/'SOURCES.json').read_text())['components']:
    path=out/source['filename']
    if not path.exists():
        temp=path.with_suffix(path.suffix+'.download')
        subprocess.run(['curl','--fail','--location','--retry','2','--max-time','300',source['url'],'-o',str(temp)],check=True)
        if hashlib.sha256(temp.read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError('Checksum mismatch: '+source['name'])
        temp.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:
        raise ValueError('Cached source checksum mismatch: '+source['name'])
print('Verified locked codec/build-only source archives')
