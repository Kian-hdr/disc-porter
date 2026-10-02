# Reproducible one-folder build. Run via script/build_helper.sh.
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules
root = Path(SPECPATH).parent
# Root publishes a packaging-safe module name, never a local top-level mcp package.
datas = collect_data_files('mcp')
binaries = collect_dynamic_libs('mcp')
hiddenimports = collect_submodules('mcp', filter=lambda name: not name.startswith('mcp.cli'))
for package in ('pydantic', 'httpx', 'httpcore', 'anyio'):
    d, b, h = collect_all(package)
    datas += d; binaries += b; hiddenimports += h
hiddenimports += ['engine.server', 'engine.core', 'disc_porter_control.server']
a = Analysis([str(root / 'engine/helper.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], runtime_hooks=[], excludes=['tkinter', 'pytest', 'IPython'],
             noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name='disc-porter-helper', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=True, target_arch=os.environ.get('DISC_PORTER_ARCH', 'arm64'),
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DiscPorterHelper')
