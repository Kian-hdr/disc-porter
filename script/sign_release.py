#!/usr/bin/env python3
"""Sign a fresh release clone inside out using an existing Developer ID identity."""
import argparse
import plistlib
import subprocess
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('app',type=Path)
parser.add_argument('--identity',required=True)
args=parser.parse_args()
app=args.app.resolve()
info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
assert info['CFBundleIdentifier']=='dev.discporter.app'
assert info['CFBundleVersion']=='5'
assert app!=Path.home()/'Applications/Disc Porter.app', 'Sign a separate release clone'
magic={b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca',b'\xce\xfa\xed\xfe'}
def sign(path):
 subprocess.run(['codesign','--force','--sign',args.identity,'--options','runtime','--timestamp',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
subprocess.run(['xattr','-cr',str(app)],check=True)
count=0
for p in app.rglob('*'):
 if p.is_symlink()or not p.is_file():continue
 with p.open('rb')as f:header=f.read(4)
 if header in magic:sign(p);count+=1
for p in sorted(app.rglob('*.framework'),key=lambda p:len(p.parts),reverse=True):sign(p)
sign(app)
subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
print(f'Developer ID signed {count} native files and the app; notarization is separate.')
