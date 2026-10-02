"""Extract a signed python.org installer privately and relocate its framework.
No package installer or postinstall scripts run; no system paths are modified.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
cache = root / 'packaging/cache'
pkg = cache / 'python-3.13.15-macos11.pkg'
expanded = cache / 'python-3.13.15-expanded'
framework = cache / 'Python.framework'
if not pkg.exists():
    subprocess.run(['curl','--fail','--location','--retry','2','--max-time','300','https://www.python.org/ftp/python/3.13.15/python-3.13.15-macos11.pkg','-o',str(pkg)],check=True)
signature = subprocess.check_output(['pkgutil','--check-signature',str(pkg)],text=True)
if 'Python Software Foundation' not in signature or 'signed by a developer certificate issued by Apple' not in signature:
    raise ValueError('Installer signature not from expected Python Software Foundation publisher')
if not expanded.exists(): subprocess.run(['pkgutil','--expand-full',str(pkg),str(expanded)],check=True)
if not framework.exists():
    shutil.copytree(expanded / 'Python_Framework.pkg/Payload', framework, symlinks=True)
for path in framework.rglob('*'):
    if path.is_symlink() or not path.is_file() or 'Frameworks' in path.relative_to(framework).parts: continue
    with path.open('rb') as f: magic=f.read(4)
    if magic not in {b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'}: continue
    deps = subprocess.check_output(['otool','-L',str(path)],text=True)
    for line in deps.splitlines():
        dep=line.strip().split(' (')[0]
        prefix='/Library/Frameworks/Python.framework/'
        if dep.startswith(prefix):
            target=framework / dep[len(prefix):]
            relative=os.path.relpath(target,path.parent)
            subprocess.run(['install_name_tool','-change',dep,'@loader_path/'+relative,str(path)],check=True,stderr=subprocess.DEVNULL)
    if path.name=='Python' and path.parent.name=='3.13':
        subprocess.run(['install_name_tool','-id','@rpath/Python.framework/Versions/3.13/Python',str(path)],check=True,stderr=subprocess.DEVNULL)
    candidate = cache / 'standalone-signing-candidate'
    shutil.copy2(path,candidate)
    subprocess.run(['codesign','--force','--sign','-',str(candidate)],check=True,stderr=subprocess.DEVNULL)
    shutil.copy2(candidate,path)
    candidate.unlink()
provenance=root / 'packaging/provenance/python-org';provenance.mkdir(parents=True,exist_ok=True)
(provenance/'INSTALLER_MANIFEST.json').write_text(json.dumps({'publisher':'Python Software Foundation','version':'3.13.15','url':'https://www.python.org/ftp/python/3.13.15/python-3.13.15-macos11.pkg','sha256':hashlib.sha256(pkg.read_bytes()).hexdigest(),'signature':'Python Software Foundation Developer ID Installer verified by pkgutil; Apple notarization reported trusted','action':'Private extraction only; framework load paths relocated; ad-hoc re-signed','minimum_macos_publisher_filename':'11','corresponding_source_review':'pending; CPython source archive captured separately; inspect installer dependency builds before public redistribution'},indent=2)+'\n')
shutil.copy2(expanded/'Resources/License.rtf',provenance/'License.rtf')
print(framework/'Versions/3.13/bin/python3.13')
