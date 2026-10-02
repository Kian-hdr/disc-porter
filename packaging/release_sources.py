#!/usr/bin/env python3
"""Create a dependency source/evidence packet for an inspected installed app.

Never changes the app, license, source locks, signatures, or remote release state.
Downloads PyPI sdists and registry crates with registry-provided SHA-256 checks.
The manifest records evidence limits instead of claiming legal completeness.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()

def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)

def download(url, dest, expected):
    if not dest.exists():
        with urllib.request.urlopen(url, timeout=120) as response, dest.open('wb') as target:
            shutil.copyfileobj(response, target)
    actual = sha(dest)
    if actual != expected:
        raise ValueError(f'Checksum mismatch: {dest.name}')
    return actual

def package(args):
    app = args.app.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    stage = out / 'Third_Party_Sources'
    if stage.exists():
        if not (stage/'MANIFEST.json').is_file():
            raise ValueError('Refusing to replace an unrecognized packet staging directory')
        shutil.rmtree(stage)  # Disposable staging produced by this script only.
    stage.mkdir()
    archives = stage / 'archives'
    archives.mkdir(exist_ok=True)
    notices = app / 'Contents/Resources/ThirdPartyNotices'
    shutil.copytree(notices, stage / 'notices', dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.pyc'))
    transformations=[]
    for file in sorted((stage/'notices').rglob('*')):
        if not file.is_file():
            continue
        try:
            original=file.read_text()
        except UnicodeError:
            continue
        redacted=original.replace(str(ROOT), '${DISC_PORTER_SOURCE_ROOT}').replace(str(Path.home()),'<LOCAL_HOME>')
        if redacted!=original:
            before=sha(file)
            file.write_text(redacted)
            transformations.append({'path':str(file.relative_to(stage)),'original_sha256':before,'derived_sha256':sha(file),'change':'Replaced exact source root and local home paths; build settings and notices otherwise preserved'})
    (stage/'PUBLIC_PATH_TRANSFORMATIONS.json').write_text(json.dumps(transformations,indent=2)+'\n')
    recipes = stage / 'build-recipes'
    recipes.mkdir(exist_ok=True)
    for name in ['build_codecs.sh','build_subtitles.sh','SOURCES.json','prepare_python.py','fetch_sources.py','capture_python_sources.py','requirements-build.txt','disc_porter_helper.spec','capture_python_notices.py','sign_helper.py','sanitize_provenance.py','sanitize_build_metadata.py','bundle_tools.py']:
        shutil.copy2(ROOT / 'packaging' / name, recipes / name)
    for name in ['build_helper.sh','package_app.sh']:
        shutil.copy2(ROOT / 'script' / name, recipes / name)
    shutil.copy2(ROOT / 'LICENSE', stage / 'APP_LICENSE_MIT')
    deps = json.loads((notices / 'Python/PYTHON_DEPENDENCIES.json').read_text())
    lock = json.loads((ROOT / 'packaging/SOURCES.json').read_text())
    rows = []
    for c in lock['components']:
        src = ROOT / 'packaging/sources' / c['filename']
        if sha(src) != c['sha256']:
            raise ValueError(f'Locked codec source mismatch: {src.name}')
        shutil.copy2(src, archives / src.name)
        rows.append(dict(c, packet_archive='archives/'+src.name, evidence='locked build input'))
    native = json.loads((notices / 'NativeBuilds/python-org/NATIVE_SOURCE_MANIFEST.json').read_text())
    for c in native['components']:
        src = ROOT / 'packaging/sources' / c['archive']
        if sha(src) != c['sha256']:
            raise ValueError(f'CPython dependency mismatch: {src.name}')
        shutil.copy2(src, archives / src.name)
        rows.append(dict(c, packet_archive='archives/'+src.name))
    src = ROOT / 'packaging/sources/python_3.13-3.13.15.13.15.tgz'
    upstream=out/'Python-3.13.15-upstream.tgz'
    download('https://www.python.org/ftp/python/3.13.15/Python-3.13.15.tgz',upstream,sha(src))
    shutil.copy2(src, archives / src.name)
    rows.append({'name':'CPython','version':'3.13.15','url':'https://www.python.org/ftp/python/3.13.15/Python-3.13.15.tgz','sha256':sha(src),'packet_archive':'archives/'+src.name,'evidence':'local captured exact-release archive; upstream retrieval checksum separately verified'})
    def sdist(c):
        row = {'name':c['name'],'version':c['version'],'license_files':c.get('license_files',[])}
        try:
            url = f"https://pypi.org/pypi/{c['name']}/{c['version']}/json"
            meta = get_json(url)
            candidates = [x for x in meta['urls'] if x['packagetype']=='sdist']
            if len(candidates)!=1:
                raise ValueError('Expected exactly one source distribution')
            entry=candidates[0]
            dest=archives/entry['filename']
            actual=download(entry['url'],dest,entry['digests']['sha256'])
            row.update(url=entry['url'],registry_metadata=url,sha256=actual,packet_archive='archives/'+dest.name,status='registry_checksum_verified')
        except Exception as error:
            row.update(status='missing',error=str(error))
        return row
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        pyrows=list(pool.map(sdist,[c for c in deps if c['name']!='CPython']))
    rows.extend(pyrows)
    # Frozen native extensions are rpds and pydantic_core. Preserve exact lockfiles
    # and registry source dependencies for their Rust code, not just wheel metadata.
    crates={}
    for row in pyrows:
        if row['name'].lower().replace('_','-') not in {'pydantic-core','rpds-py'} or row['status']=='missing':
            continue
        with tarfile.open(stage / row['packet_archive']) as archive:
            for member in archive.getmembers():
                if member.name.endswith('/Cargo.lock') and member.isfile():
                    data=archive.extractfile(member).read()
                    (recipes/(row['name']+'-Cargo.lock')).write_bytes(data)
                    for crate in tomllib.loads(data.decode())['package']:
                        if crate.get('source','').startswith('registry+'):
                            crates[(crate['name'],crate['version'])]=crate
                        elif 'source' in crate:
                            rows.append({'name':crate['name'],'version':crate['version'],'status':'missing','error':'Non-registry Rust dependency requires exact source capture','source':crate['source']})
    def rust(crate):
        url=f"https://static.crates.io/crates/{crate['name']}/{crate['name']}-{crate['version']}.crate"
        dest=archives/(crate['name']+'-'+crate['version']+'.crate')
        row={'name':crate['name'],'version':crate['version'],'url':url,'kind':'rust-transitive'}
        try:
            actual=download(url,dest,crate['checksum'])
            row.update(sha256=actual,packet_archive='archives/'+dest.name,status='cargo_lock_checksum_verified')
            with tarfile.open(dest) as source:
                license_files=[]
                for member in source.getmembers():
                    filename=Path(member.name).name
                    if member.isfile() and filename.lower().startswith(('license','copying','notice','copyright')):
                        target=stage/'rust-notices'/(crate['name']+'-'+crate['version'])/member.name.replace('/','__')
                        target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_bytes(source.extractfile(member).read())
                        license_files.append({'path':str(target.relative_to(stage)),'sha256':sha(target)})
                    if member.name.endswith('/Cargo.toml') and member.name.count('/')==1:
                        config=tomllib.loads(source.extractfile(member).read().decode())
                        row['declared_license']=config['package'].get('license')
                row['license_files']=license_files
                if not license_files:
                    row['notice_review']='No standalone license text found; inspect crate source notices'
                    if crate['name'] in {'r-efi','wit-bindgen-rt'}:
                        row['platform_scope_evidence']='getrandom 0.3.3 Cargo.toml gates r-efi to UEFI and wasi to wasm32-wasi-p2; wasi Cargo.toml depends on wit-bindgen-rt. These target chains are excluded on macOS.' 
        except Exception as error:
            row.update(status='missing',error=str(error))
        return row
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows.extend(pool.map(rust,crates.values()))
    runtime=app/'Contents/Resources/DiscPorterRuntime'
    binaries=[]
    for file in sorted(runtime.rglob('*')):
        if file.is_file() and not file.is_symlink() and (file.suffix in {'.so','.dylib'} or file.name=='Python'):
            binaries.append({'path':str(file.relative_to(app)),'sha256':sha(file),'dependencies':subprocess.check_output(['otool','-L',str(file)],text=True).replace(str(app),'<APP>')})
    tools=[]
    for name in ['ffmpeg','ffprobe']:
        file=app/'Contents/Tools'/name
        tools.append({'name':name,'sha256':sha(file),'version':subprocess.run([str(file),'-version'],capture_output=True,text=True).stdout})
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    blockers=[r for r in rows if r.get('status')=='missing']
    manifest={'bundle_version':info.get('CFBundleShortVersionString'),'bundle_build':info.get('CFBundleVersion'),'source_components':rows,'runtime_native_files':binaries,'tools':tools,'source_capture_errors':blockers,'evidence_limits':['Native-wheel source and Cargo.lock checksums establish captured registry content, not independent reproduction of publisher wheel builds.','CPython PSF installer correspondence is based on its exact release build recipe; installer binaries were not independently rebuilt.','Captured notice .pyc build caches are excluded; they are not governing license texts and embed private compiler paths.','MIT covers original Disc Porter code; third-party component licenses are preserved separately.','Publish this matching packet beside the binary and validate its remote hash before distribution; no remote publication is performed by this tool.']}
    (stage/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if (ROOT/'docs/THIRD_PARTY_RELEASE.md').exists():
        shutil.copy2(ROOT/'docs/THIRD_PARTY_RELEASE.md',stage/'README.md')
    inventory=[{'path':str(p.relative_to(stage)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(stage.rglob('*')) if p.is_file() and p.name!='SHA256_MANIFEST.json']
    (stage/'SHA256_MANIFEST.json').write_text(json.dumps(inventory,indent=2)+'\n')
    archive=out/f"Disc_Porter_{info.get('CFBundleShortVersionString')}_Third_Party_Sources.zip"
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as packet:
        for p in sorted(stage.rglob('*')):
            if p.is_file():
                packet.write(p,'Third_Party_Sources/'+str(p.relative_to(stage)))
    digest=sha(archive)
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n')
    print(json.dumps({'archive':str(archive),'sha256':digest,'sources':len(rows),'missing':len(blockers),'native_files':len(binaries)},indent=2))
    return 1 if blockers else 0

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,default=Path.home()/'Applications/Disc Porter.app')
    parser.add_argument('--output',type=Path,default=Path.home()/'Library/Caches/DiscPorter/Release')
    raise SystemExit(package(parser.parse_args()))
