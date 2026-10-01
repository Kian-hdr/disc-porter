#!/usr/bin/env python3
"""Authenticated loopback-only archive API."""
import argparse
import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.core import Engine, ArchiveError


def serve(state_dir):
    engine = Engine(state_dir)
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def respond(self, status, value):
            data = json.dumps(value).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(data)
        def handle_request(self):
            if self.headers.get('Origin') or self.headers.get('Host') != '127.0.0.1:' + str(server.server_port) or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                return self.respond(403, {'error': 'Loopback bearer authentication required; browser origins rejected'})
            try:
                data = {}
                if self.command == 'POST':
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 <= size <= 65536: raise ArchiveError('Request body exceeds limit')
                    data = json.loads(self.rfile.read(size) or b'{}')
                    if not isinstance(data, dict): raise ArchiveError('Request body must be an object')
                path = self.path.split('?')[0].strip('/').split('/')
                if self.command == 'GET':
                    if path == ['status']: result = engine.status()
                    elif path == ['settings']: result = engine.settings()
                    elif path == ['profiles']: result = {'profiles': engine.profiles()}
                    elif len(path) == 2 and path[0] == 'jobs': result = engine.job(path[1])
                    elif len(path) == 2 and path[0] == 'report': result = engine.report(path[1])
                    else: return self.respond(404, {'error': 'Route not found'})
                else:
                    if path == ['scan']: result = {'discs': engine.scan(auto_start=False)}
                    elif path == ['settings']: result = engine.settings(data)
                    elif path == ['jobs']: result = engine.create_job(data)
                    elif path == ['profiles']: result = engine.profile(data)
                    elif len(path) == 3 and path[0] == 'jobs' and path[2] == 'action': result = engine.action(path[1], data)
                    elif path == ['shutdown']:
                        engine.close(); result = {'accepted': True}; threading.Thread(target=server.shutdown, daemon=True).start()
                    else: return self.respond(404, {'error': 'Route not found'})
                return self.respond(200, result)
            except (ArchiveError, OSError, ValueError, KeyError, TypeError) as e: return self.respond(409 if isinstance(e, ArchiveError) else 400, {'error': str(e)})
            except Exception: return self.respond(500, {'error': 'Internal engine error; state retained'})
        do_GET = handle_request
        do_POST = handle_request
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    endpoint = Path(state_dir) / 'endpoint.json'
    temp = endpoint.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(dict(url='http://127.0.0.1:' + str(server.server_port), token=token), f); f.flush(); os.fsync(f.fileno())
    os.chmod(temp, 0o600); os.replace(temp, endpoint)
    server.serve_forever(); server.server_close()
    endpoint.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--state-dir', required=True)
    args = parser.parse_args()
    serve(args.state_dir)
