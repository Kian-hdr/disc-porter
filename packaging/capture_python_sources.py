"""Archive dependency recipes from the exact CPython release installer builder."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
root=Path(__file__).resolve().parent
archive=root/'sources/python_3.13-3.13.15.13.15.tgz'
out=root/'provenance/python-org';out.mkdir(parents=True,exist_ok=True)
with tarfile.open(archive) as t:
    builder=t.extractfile('Python-3.13.15/Mac/BuildScript/build-installer.py').read()
    (out/'CPYTHON_BUILD_INSTALLER.py').write_bytes(builder)
    license_text=t.extractfile('Python-3.13.15/LICENSE').read();(out/'CPYTHON_LICENSE').write_bytes(license_text)
# Exact versions/checksums inspected in the matching CPython build recipe.
components=[
 ('OpenSSL','3.0.21','https://github.com/openssl/openssl/releases/download/openssl-3.0.21/openssl-3.0.21.tar.gz','617e29af8e421f46649484a4937e48c685e47f46488167c982f88bc4ec1d522f'),
 ('NCurses','6.5','https://ftp.gnu.org/gnu/ncurses/ncurses-6.5.tar.gz','136d91bc269a9a5785e5f9e980bc76ab57428f604ce3e5a5a90cebc767971cc6'),
 ('SQLite','3.50.4','https://www.sqlite.org/2025/sqlite-autoconf-3500400.tar.gz','a3db587a1b92ee5ddac2f66b3edb41b26f9c867275782d46c3a088977d6a5b18'),
 ('libmpdec','4.0.1','https://www.bytereef.org/software/mpdecimal/releases/mpdecimal-4.0.1.tar.gz','96d33abb4bb0070c7be0fed4246cd38416188325f820468214471938545b1ac8'),
 ('XZ','5.2.3','https://tukaani.org/xz/xz-5.2.3.tar.gz','ef68674fb47a8b8e741b34e429d86e9d')]
rows=[]
for name,version,url,expected in components:
    path=root/'sources'/('python-org-'+name+'-'+version+'.tar.gz')
    row={'name':name,'version':version,'url':url,'expected_checksum':expected,'recipe':'CPYTHON_BUILD_INSTALLER.py','status':'missing'}
    try:
        if not path.exists():subprocess.run(['curl','--fail','--location','--retry','2','--max-time','180',url,'-o',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        payload=path.read_bytes();actual=(hashlib.sha256(payload).hexdigest() if len(expected)==64 else hashlib.md5(payload).hexdigest())
        if actual!=expected:raise ValueError('Source differs from upstream CPython installer recipe')
        row.update(status='captured_recipe_checksum_verified',archive=path.name,sha256=hashlib.sha256(payload).hexdigest())
        with tarfile.open(path) as t:
            for item in t.getmembers():
                if item.isfile() and item.size<2000000 and any(x in Path(item.name).name.lower() for x in ['license','copying','copyright']):
                    file=name+'-'+item.name.replace('/','__')
                    if len(file)<200:(out/file).write_bytes(t.extractfile(item).read())
    except Exception as error:row['error']=str(error)
    rows.append(row)
(out/'NATIVE_SOURCE_MANIFEST.json').write_text(json.dumps({'scope':'Dependency recipe matches exact CPython release builder; this does not prove every PSF installer binary was independently rebuilt from these archives','components':rows},indent=2)+'\n')
