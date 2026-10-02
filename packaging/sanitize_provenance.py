"""Sanitize only Homebrew receipt path strings; preserve original private evidence.

License text, version identifiers and provider/source checksum fields are untouched.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
root=Path(__file__).resolve().parent
provenance=root/'provenance';private=root/'cache/private-receipts'
record=provenance/'RECEIPT_SANITIZATION.json'
prior=json.loads(record.read_text())['receipts'] if record.exists() else []
rows={r['path']:r for r in prior}
for source in provenance.rglob('INSTALL_RECEIPT.json'):
    raw=source.read_bytes();text=raw.decode();sanitized=re.sub(r'/Users/[^/\s"\\]+','<LOCAL_HOME>',text)
    if text==sanitized:continue
    relative=source.relative_to(provenance);copy=private/relative;copy.parent.mkdir(parents=True,exist_ok=True)
    if copy.exists() and copy.read_bytes()!=raw:raise ValueError('Conflicting private receipt evidence: '+str(relative))
    if not copy.exists():shutil.copy2(source,copy)
    before=json.loads(text);after=json.loads(sanitized)
    # Replacement affects values only and must not change receipt structure.
    assert before.keys()==after.keys()
    source.write_text(sanitized)
    rows[str(relative)]={'path':str(relative),'original_sha256':hashlib.sha256(raw).hexdigest(),'sanitized_sha256':hashlib.sha256(sanitized.encode()).hexdigest(),'transformation':'Personal /Users home prefixes replaced with <LOCAL_HOME>; original preserved in ignored private build cache; checksum/version/license content unchanged'}
record.write_text(json.dumps({'scope':'Homebrew INSTALL_RECEIPT.json only; no license text modification','receipts':sorted(rows.values(),key=lambda x:x['path'])},indent=2)+'\n')
print('Sanitized receipt evidence:',len(rows),'receipts')
