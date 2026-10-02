#!/usr/bin/env python3
"""Preserve active engine work before replacing a local application bundle."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import time
import urllib.error
import urllib.parse
import urllib.request

def stop_idle(state):
    endpoint = state / 'endpoint.json'
    if not endpoint.exists(): return
    info = endpoint.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise RuntimeError('Invalid engine endpoint ownership/permissions; refusing replacement')
    connection = json.loads(endpoint.read_text())
    url = urllib.parse.urlsplit(connection['url'])
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.username or url.password or url.query or url.fragment:
        raise RuntimeError('Invalid engine endpoint; refusing replacement')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, body=None):
        req = urllib.request.Request(connection['url'].rstrip('/') + path, data=body,
            headers={'Authorization':'Bearer '+connection['token'],'Content-Type':'application/json'})
        with opener.open(req,timeout=5) as response:return json.load(response)
    try: status = request('/status')
    except urllib.error.HTTPError as error:
        raise RuntimeError('Engine rejected status/authentication; refusing replacement') from error
    except urllib.error.URLError:
        # A crashed parent can leave supervised readers holding the owner lock.
        lock = state / 'owner.lock'
        with lock.open('a+') as handle:
            try: fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('An engine or supervised reader still owns this state; refusing replacement') from error
        return
    if not status.get('safe_to_disconnect'):
        raise RuntimeError('Disc Porter processing/readers are active. Finish a checkpoint or Prepare to disconnect before replacement. Work is preserved.')
    request('/shutdown',b'{}')
    for _ in range(50):
        if not endpoint.exists():return
        time.sleep(.1)
    raise RuntimeError('Engine teardown is pending; refusing replacement until it releases its handles')

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--state-dir',type=Path,default=Path(os.environ.get('DISC_PORTER_STATE_DIR',str(Path.home()/'Library/Application Support/DiscPorter'))))
    args=parser.parse_args()
    try:stop_idle(args.state_dir)
    except (RuntimeError,OSError,ValueError) as error:parser.exit(2,str(error)+'\n')
