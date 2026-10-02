"""Retain inherited state-owner descriptor until every owned tool is stopped."""
import os
import signal
import subprocess
import sys
import time


def supervise(parent,command):
    child=subprocess.Popen(command,start_new_session=True)
    def stop_child():
        if child.poll()is not None:return
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait()
    def interrupted(signum,frame):raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    try:
        while child.poll()is None:
            try:os.kill(int(parent),0)
            except ProcessLookupError:stop_child();return 125
            time.sleep(.25)
        return child.returncode
    finally:stop_child()

if __name__=='__main__':sys.exit(supervise(int(sys.argv[1]),sys.argv[2:]))
