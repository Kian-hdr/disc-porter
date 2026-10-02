"""Fail closed on unbundled Mach-O dependencies and record signed resource hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

MAGIC = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}
def run(*args): return subprocess.check_output(args, text=True)
def inspect(root, architecture="arm64"):
    executable_base = root / "Contents/Helpers/DiscPorterHelper" if (root / "Contents").exists() else root
    rows = []; max_os = (0, 0)
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink(): continue
        data = path.read_bytes()
        row = {'path': str(path.relative_to(root)), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        if data[:4] in MAGIC:
            row['architectures'] = run('lipo', '-archs', str(path)).strip()
            if architecture not in row['architectures'].split(): raise ValueError('No arm64: ' + row['path'])
            deps = [s.strip().split(' (')[0] for s in run('otool', '-L', str(path)).splitlines()[1:]]
            commands = run('otool', '-l', str(path))
            rpaths = re.findall(r'cmd LC_RPATH\n.*?path ([^\n]+?) \(offset', commands, re.S)
            for rp in rpaths:
                if rp.startswith('/') and not rp.startswith(('/System/Library/', '/usr/lib/')): raise ValueError('Absolute non-system rpath: ' + row['path'])
            ids = run('otool', '-D', str(path)).splitlines()[1:]
            for dep in deps:
                if dep in ids: continue
                if dep.startswith(('/System/Library/', '/usr/lib/')): continue
                if dep.startswith('@loader_path/'):
                    found = (path.parent / dep[len('@loader_path/'):]).exists()
                elif dep.startswith('@executable_path/'):
                    # Helpers use their own adjacent runtime folder.
                    found = (executable_base / dep[len('@executable_path/'):]).exists()
                elif dep.startswith('@rpath/'):
                    found = any((Path(r.replace('@loader_path', str(path.parent)).replace('@executable_path', str(executable_base))) / dep[len('@rpath/'):]).exists() for r in rpaths)
                else: found = False
                if not found: raise ValueError('Unbundled load dependency ' + dep + ' in ' + row['path'])
            row['dependencies'] = deps
            mo = re.search(r'\bminos (\d+(?:\.\d+)*)', commands) or re.search(r'cmd LC_VERSION_MIN_MACOSX\n.*?version (\d+(?:\.\d+)*)', commands, re.S)
            row['minimum_macos'] = mo.group(1) if mo else 'unknown'
            if mo:
                version = tuple(map(int, mo.group(1).split('.')))
                max_os = max(max_os, version)
            subprocess.run(['codesign', '--verify', '--strict', str(path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rows.append(row)
    if max_os > (14, 0): raise ValueError('Native dependency exceeds macOS 14 support: ' + str(max_os))
    manifest = {'architecture': architecture, 'minimum_macos_from_macho': '.'.join(map(str, max_os)), 'signing': 'ad_hoc_local_only', 'public_distribution': 'blocked_pending_source_license_deployment_signing_notarization_review', 'files': rows}
    return manifest
if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('bundle', type=Path); p.add_argument('--architecture',default='arm64',choices=['arm64','x86_64']); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); m = inspect(a.bundle,a.architecture); a.output.write_text(json.dumps(m, indent=2)+'\n'); print('Verified', len(m['files']), 'files; effective Mach-O minimum macOS', m['minimum_macos_from_macho'])
