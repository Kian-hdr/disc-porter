"""Capture exact installed keg recipes, notices and checksum-verified source archives.

This is provenance evidence, not an assertion that bottle corresponding-source duties
are satisfied. Failed retrieval and unarchived patch/resource URLs remain blockers.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from urllib.parse import urlparse


def capture(manifest_path, destination, archives):
    destination.mkdir(parents=True, exist_ok=True); archives.mkdir(parents=True, exist_ok=True)
    data = json.loads(manifest_path.read_text())
    providers = sorted({x['provider_build'] for x in data['files']})
    rows = []
    for provider in providers:
        name, version = provider.split('/', 1)
        keg = Path('/opt/homebrew/Cellar') / name / version
        formula = keg / '.brew' / (name + '.rb')
        out = destination / (name + '-' + version); out.mkdir(exist_ok=True)
        row = {'name': name, 'version': version, 'source_status': 'missing', 'release_duties_status': 'unverified', 'recipe': None, 'notice_files': []}
        if not formula.is_file():
            row['error'] = 'Installed formula recipe missing'; rows.append(row); continue
        text = formula.read_text(); shutil.copy2(formula, out / 'formula.rb')
        row['recipe'] = str((out / 'formula.rb').relative_to(destination))
        row['recipe_sha256'] = hashlib.sha256(formula.read_bytes()).hexdigest()
        receipt = keg / 'INSTALL_RECEIPT.json'
        if receipt.is_file(): shutil.copy2(receipt, out / 'INSTALL_RECEIPT.json')
        for p in list(keg.glob('*')) + list((keg / 'share/doc').glob('**/*')):
            if p.is_file() and any(x in p.name.lower() for x in ['license', 'copying', 'notice', 'copyright']):
                target = out / str(p.relative_to(keg)).replace('/', '__')
                shutil.copy2(p, target); row['notice_files'].append(target.name)
        match = re.search(r'^  url "([^"]+)"', text, re.M)
        checksum = re.search(r'^  sha256 "([0-9a-f]{64})"', text, re.M)
        revision = re.search(r'^\s+revision: "([0-9a-f]{40})"', text, re.M)
        license_match = re.search(r'^  license ([^\n]+)', text, re.M)
        row['formula_declared_license'] = license_match.group(1) if license_match else 'not parsed'
        url = match.group(1) if match else None
        expected = checksum.group(1) if checksum else None
        if url and url.endswith('.git') and revision:
            row['source_revision'] = revision.group(1)
            url = url[:-4] + '/-/archive/' + revision.group(1) + '/' + name + '-' + revision.group(1) + '.tar.gz'
        row['source_url'] = url; row['expected_sha256'] = expected
        # Resources/patches may require additional exact sources; keep visible rather than claiming complete.
        row['recipe_additional_source_urls'] = re.findall(r'^\s+(?:url|patch) "([^"]+)"', text, re.M)[1:]
        if not url:
            row['error'] = 'Source URL not parsed'; rows.append(row); continue
        suffix = next((x for x in ['.tar.gz','.tar.xz','.tar.bz2','.tgz','.zip'] if urlparse(url).path.endswith(x)), '.archive')
        archive = archives / (name.replace('@', '_') + '-' + version + suffix)
        try:
            if not archive.exists():
                subprocess.run(['curl', '--fail', '--location', '--retry', '2', '--max-time', '180', '--silent', '--show-error', url, '-o', str(archive)], check=True)
            actual = hashlib.sha256(archive.read_bytes()).hexdigest()
            if expected and actual != expected:
                raise ValueError('Source checksum differs from installed recipe')
            row.update(source_status='captured_checksum_verified' if expected else 'captured_exact_revision_unverified_archive_checksum', archive=archive.name, archive_sha256=actual)
            with tarfile.open(archive) as tar:
                for member in tar.getmembers():
                    if member.isfile() and member.size < 2000000 and any(x in Path(member.name).name.lower() for x in ['license', 'copying', 'copyright']):
                        nameout = 'SOURCE__' + member.name.replace('/', '__')
                        if len(nameout) > 200: continue
                        content = tar.extractfile(member).read()
                        (out / nameout).write_bytes(content); row['notice_files'].append(nameout)
        except Exception as error:
            row['error'] = str(error)
        rows.append(row)
    result = {'capture_scope': 'Exact installed FFmpeg dylib closure. Formula recipes/receipts are evidence, not proof of complete corresponding source.', 'archives_shipped_in_app': False, 'public_redistribution_status': 'blocked_pending_source_and_license_review', 'components': rows}
    (destination / 'SOURCE_MANIFEST.json').write_text(json.dumps(result, indent=2) + '\n')
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--binary-manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--archives', type=Path, required=True)
    a = p.parse_args(); capture(a.binary_manifest, a.output, a.archives)
