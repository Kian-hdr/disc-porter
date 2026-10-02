"""Preserve installed dependency license files and exact metadata, without assuming compliance."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import sysconfig

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
rows = []
for dist in importlib.metadata.distributions():
    name = dist.metadata['Name']; version = dist.version
    if name.lower() in {'pip'}:
        # Other installed build-environment packages are included conservatively; module inventory establishes shipping scope.
        continue
    dest = out / (name + '-' + version); dest.mkdir(exist_ok=True)
    licenses = []
    for f in dist.files or []:
        if any('license' in p.lower() or 'copying' in p.lower() or 'notice' in p.lower() for p in Path(str(f)).parts):
            source = Path(dist.locate_file(f))
            if source.is_file():
                target = dest / str(f).replace('/', '__'); shutil.copy2(source, target)
                licenses.append({'file': target.name, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    (dest / 'METADATA').write_text(dist.read_text('METADATA') or '')
    rows.append({'name': name, 'version': version, 'license_files': licenses, 'license_expression': dist.metadata.get('License-Expression'), 'declared_license': dist.metadata.get('License'), 'evidence_limit': 'Installed build environment inventory; complete frozen module membership and transitive native source duties require release review.'})
# CPython contains a combined license text for the interpreter and included third-party code.
python_license = Path(sysconfig.get_config_var('LIBPL') or '') / 'LICENSE'
candidates = [Path(__file__).resolve().parent / 'provenance/python-org/CPYTHON_LICENSE', python_license, Path(sys.base_prefix) / 'LICENSE.txt', Path('/opt/homebrew/Cellar/python@3.13') / sys.version.split()[0] / 'LICENSE']
found = next((p for p in candidates if p.is_file()), None)
if found:
    shutil.copy2(found, out / 'CPYTHON_LICENSE')
rows.append({'name': 'CPython', 'version': sys.version.split()[0], 'license_file_captured': bool(found), 'evidence_limit': 'Interpreter build is Homebrew CPython; build recipe and linked library provenance require release review.'})
(out / 'PYTHON_DEPENDENCIES.json').write_text(json.dumps(rows, indent=2) + '\n')
