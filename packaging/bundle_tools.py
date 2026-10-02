"""Relocate a verified local FFmpeg dependency closure and record every input hash."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def dependencies(path):
    return [line.strip().split(' (')[0] for line in run('otool', '-L', str(path)).splitlines()[1:]]

def rpaths(path):
    return re.findall(r'cmd LC_RPATH\n.*?path ([^\n]+?) \(offset', run('otool', '-l', str(path)), re.S)

def resolve(dep, source):
    if dep.startswith(('/System/Library/', '/usr/lib/')):
        return None
    if dep.startswith('@loader_path/'):
        candidate = source.parent / dep[len('@loader_path/'):]
    elif dep.startswith('@rpath/'):
        options = [Path(r.replace('@loader_path', str(source.parent))) / dep[len('@rpath/'):] for r in rpaths(source)]
        candidate = next((p for p in options if p.exists()), None)
        if candidate is None:
            raise ValueError('Unresolved dylib ' + dep + ' in ' + source.name)
    elif dep.startswith('/'):
        candidate = Path(dep)
    else:
        raise ValueError('Unsupported dylib reference ' + dep)
    if not candidate.is_file():
        raise ValueError('Missing dependency ' + str(candidate))
    return candidate.resolve()

def minimum_os(path):
    text = run('otool', '-l', str(path))
    value = re.search(r'\bminos (\S+)', text) or re.search(r'\bversion (\d+\.\d+(?:\.\d+)?)', text)
    return value.group(1) if value else 'unknown'

def bundle(ffmpeg, ffprobe, destination, architecture="arm64"):
    destination.mkdir(parents=True, exist_ok=True)
    queue = [ffmpeg.resolve(), ffprobe.resolve()]
    sources = {}
    edges = {}
    while queue:
        source = queue.pop()
        if source.name in sources:
            if sources[source.name] != source:
                raise ValueError('Dependency filename collision: ' + source.name)
            continue
        if architecture not in run('lipo', '-archs', str(source)).split():
            raise ValueError('Missing arm64 architecture: ' + source.name)
        sources[source.name] = source
        deps = dependencies(source)
        # Dylibs' first entry is their ID, not another dependency.
        if source.suffix == '.dylib' and deps:
            deps = deps[1:]
        edges[source.name] = [(dep, resolve(dep, source)) for dep in deps]
        queue.extend(target for _, target in edges[source.name] if target is not None)
    manifest = {'architecture': architecture, 'relocation': '@loader_path closure; ad-hoc signed', 'ffmpeg_version': run(str(ffmpeg), '-version').splitlines()[0], 'ffmpeg_configuration': run(str(ffmpeg), '-version').splitlines()[2], 'files': []}
    old_manifest = destination / 'BINARY_MANIFEST.json'
    if old_manifest.exists():
        old = json.loads(old_manifest.read_text())
        for item in old.get('files', []):
            old_name = item['name']
            if Path(old_name).name != old_name:
                raise ValueError('Invalid prior build manifest filename')
            stale = destination / old_name
            if old_name.endswith('.dylib') and old_name not in sources and stale.exists():
                if sha(stale) != item['output_sha256']:
                    raise ValueError('Modified prior build output; refusing regeneration: ' + old_name)
                stale.unlink()
    for name, source in sources.items():
        target = destination / name
        shutil.copy2(source, target)
        target.chmod(0o755)
    for name, source in sources.items():
        target = destination / name
        for dep, resolved in edges[name]:
            if resolved is not None:
                subprocess.run(['install_name_tool', '-change', dep, '@loader_path/' + resolved.name, str(target)], check=True)
        if target.suffix == '.dylib':
            subprocess.run(['install_name_tool', '-id', '@rpath/' + name, str(target)], check=True)
        for rp in rpaths(source):
            if rp.startswith('/') and not rp.startswith(('/System/Library/', '/usr/lib/')):
                subprocess.run(['install_name_tool', '-delete_rpath', rp, str(target)], check=True)
        subprocess.run(['codesign', '--force', '--sign', '-', str(target)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for dep in dependencies(target):
            if dep.startswith('/') and not dep.startswith(('/usr/lib/', '/System/Library/')):
                raise ValueError('Absolute non-system dependency left in ' + name)
            if dep.startswith('@loader_path/') and not (destination / dep[len('@loader_path/'):]).exists():
                raise ValueError('Relocated dependency missing: ' + dep)
        # Record portable installed keg identity, never developer absolute paths.
        parts = source.parts
        idx = parts.index('Cellar') if 'Cellar' in parts else None
        identity = '/'.join(parts[idx+1:idx+3]) if idx else source.name
        manifest['files'].append({'name': name, 'provider_build': identity, 'input_sha256': sha(source), 'output_sha256': sha(target), 'architectures': run('lipo', '-archs', str(target)).strip(), 'minimum_macos': minimum_os(target), 'dependencies': dependencies(target)})
    for executable in ['ffmpeg', 'ffprobe']:
        run(str(destination / executable), '-version')
    encoders = run(str(destination / 'ffmpeg'), '-hide_banner', '-encoders')
    for encoder in ['libx264', 'libx265', 'h264_videotoolbox', 'hevc_videotoolbox']:
        if encoder not in encoders:
            raise ValueError('Required encoder absent: ' + encoder)
    manifest['required_encoders'] = ['libx264', 'libx265', 'h264_videotoolbox', 'hevc_videotoolbox']
    (destination / 'BINARY_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return sources, manifest

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ffmpeg', type=Path, default=Path('/opt/homebrew/bin/ffmpeg'))
    parser.add_argument('--ffprobe', type=Path, default=Path('/opt/homebrew/bin/ffprobe'))
    parser.add_argument('--architecture', default='arm64', choices=['arm64','x86_64'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle(args.ffmpeg, args.ffprobe, args.output, args.architecture)
