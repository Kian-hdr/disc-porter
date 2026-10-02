"""Ad-hoc sign owned helper native code inside out; no distribution identity implied."""
from pathlib import Path
import subprocess
import sys
root = Path(sys.argv[1])
magic = {b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'}
for p in root.rglob('*'):
    if p.is_file() and not p.is_symlink():
        with p.open('rb') as f: header=f.read(4)
        if header in magic and p.name != 'Python':
            subprocess.run(['codesign','--force','--sign','-',str(p)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
for p in sorted(root.rglob('*.framework'), key=lambda p:len(p.parts), reverse=True):
    subprocess.run(['codesign','--force','--sign','-',str(p)],check=True)
subprocess.run(['codesign','--verify','--strict',str(root/'disc-porter-helper')],check=True)
