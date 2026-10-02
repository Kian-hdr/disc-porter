#!/usr/bin/env bash
# Local task-authorized installation; public distribution is a separate release gate.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -ge 1 ]] || { echo 'Usage: install_local.sh VERIFIED_APP [--no-launch]' >&2; exit 2; }
SOURCE_APP="$1"
DESTINATION="$HOME/Applications/Disc Porter.app"
/usr/bin/codesign --verify --deep --strict "$SOURCE_APP"
python3 - "$SOURCE_APP" <<'PY'
import plistlib,sys
from pathlib import Path
info=plistlib.loads((Path(sys.argv[1])/'Contents/Info.plist').read_bytes())
assert info['CFBundleIdentifier']=='dev.discporter.app', 'Wrong application bundle'
assert info['CFBundleShortVersionString']=='0.2.0', 'Wrong application version'
PY
python3 "$ROOT_DIR/script/runtime_gate.py"
pkill -x DiscPorter >/dev/null 2>&1 || true
mkdir -p "$HOME/Applications"
if [[ -e "$DESTINATION" ]]; then
  "$HOME/.local/bin/codex-recovery" stash "$DESTINATION"
fi
# Install into an adjacent disposable candidate, seal and check before swapping.
INSTALL_ROOT="$(mktemp -d "$HOME/Applications/.disc-porter-install-XXXXXXXX")"
CANDIDATE="$INSTALL_ROOT/Disc Porter.app"
/usr/bin/ditto "$SOURCE_APP" "$CANDIDATE"
/usr/bin/xattr -cr "$CANDIDATE"
/usr/bin/codesign --force --sign - "$CANDIDATE"
/usr/bin/codesign --verify --deep --strict "$CANDIDATE"
python3 - "$CANDIDATE" "$DESTINATION" "$INSTALL_ROOT" <<'PY'
import fcntl,os,sys
from pathlib import Path
candidate,destination,base=map(Path,sys.argv[1:])
previous=base/'previous.app'
state=Path(os.environ.get('DISC_PORTER_STATE_DIR',str(Path.home()/'Library/Application Support/DiscPorter')))
state.mkdir(parents=True,exist_ok=True,mode=0o700)
owner=(state/'owner.lock').open('a+')
try:fcntl.flock(owner,fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:raise RuntimeError('An engine started during staging; installed app remains untouched. Pause it before retrying.')
if destination.exists():destination.rename(previous)
try:candidate.rename(destination)
except BaseException:
 if previous.exists():previous.rename(destination)
 raise
print('Disc Porter 0.2 installed. Previous generated bundle is recoverable.')
PY
/usr/bin/codesign --verify --deep --strict "$DESTINATION"
if [[ "${2:-}" != --no-launch ]]; then /usr/bin/open -n "$DESTINATION"; fi
