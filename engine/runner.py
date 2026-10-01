"""Tool supervisor: retain inherited state-owner lock until owned tool exits."""
import os
import signal
import subprocess
import sys
import time

parent = int(sys.argv[1])
child = subprocess.Popen(sys.argv[2:], start_new_session=True)


def stop_child():
    if child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()  # Lock survives until kernel reports that the owned tool exited.


def interrupted(signum, frame):
    raise SystemExit(128 + signum)


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
try:
    while child.poll() is None:
        try:
            os.kill(parent, 0)
        except ProcessLookupError:
            stop_child()
            sys.exit(125)
        time.sleep(.25)
    sys.exit(child.returncode)
finally:
    stop_child()
