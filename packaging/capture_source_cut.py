"""Record the exact source cut underlying a frozen helper, with portable paths."""
import hashlib
import json
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
files=[]
for directory in ['engine','disc_porter_control']:
    files.extend((root/directory).rglob('*.py'))
files += [root/'mcp/server.py',root/'mcp/requirements.txt',root/'packaging/requirements-build.txt',root/'packaging/disc_porter_helper.spec']
records=[{'path':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]
canonical=json.dumps(records,sort_keys=True,separators=(',',':')).encode()
result={'source_sha256':hashlib.sha256(canonical).hexdigest(),'files':records,'validation_source':{'path':'tests/mcp/test_bridge.py','sha256':hashlib.sha256((root/'tests/mcp/test_bridge.py').read_bytes()).hexdigest()},'scope':'Frozen engine/bridge source cut; excludes GUI and build-cache data; uncommitted source is allowed for this private artifact'}
Path(sys.argv[1]).write_text(json.dumps(result,indent=2)+'\n')
print(result['source_sha256'])
