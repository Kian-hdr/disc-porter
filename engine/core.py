"""Durable archive pipeline.

Workflow informed by dvd-digitize-archive (disc_snapshot, compatible_encode,
makemkv_job). Implemented independently; no private configuration is imported.
A structural ID identifies content structure, not a physical pressing or title.
"""
import csv
import fcntl
import hashlib
import json
import os
import plistlib
import re
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PHASES = ['scan', 'acquire', 'encode', 'verify', 'complete']
DEFAULTS = dict(output_root='', auto_start=False, video_codec='hevc', quality=18, languages=['eng', 'deu'])


class ArchiveError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 180:
        raise ArchiveError('Provide a nonempty collection/title name under 180 characters')
    value = value.strip()
    if value in {'.', '..'} or '/' in value or '\\' in value or any(ord(c) < 32 for c in value):
        raise ArchiveError('Names cannot contain paths or control characters')
    return re.sub(r'[^\w .()-]', '_', value.strip()).replace(' ', '_')


def identity(path, content=False):
    p = Path(path).resolve(strict=True)
    s = p.stat()
    result = dict(path=str(p), dev=s.st_dev, ino=s.st_ino)
    # UUID detects a different mounted volume, while inode/device detect path replacement.
    if sys.platform == 'darwin':
        # diskutil does not accept arbitrary directories inside an external disk.
        mount = p if p.is_dir() else p.parent
        while mount.parent != mount and mount.parent.stat().st_dev == mount.stat().st_dev:
            mount = mount.parent
        if p.parts[:2] == ('/', 'Volumes') and len(p.parts) >= 3:
            mount = Path(*p.parts[:3])
        r = subprocess.run(['/usr/sbin/diskutil', 'info', '-plist', str(mount)], capture_output=True, timeout=15)
        if r.returncode == 0:
            v = plistlib.loads(r.stdout)
            result.update(volume_uuid=v.get('VolumeUUID'), mount=v.get('MountPoint'))
            if v.get('VolumeUUID'):
                result.pop('dev', None)  # Device number may change after a normal remount.
        elif str(p).startswith('/Volumes/'):
            raise ArchiveError('Cannot verify destination/source volume identity')
    if content and p.is_file():
        result.update(size=s.st_size, sha256=digest(p))
    return result


def check_identity(saved, content=False):
    try:
        current = identity(saved['path'], content)
    except (OSError, ValueError) as e:
        raise ArchiveError('Required source or destination is missing: ' + saved['path']) from e
    if current != saved:
        raise ArchiveError('Source or destination identity changed; restore the exact original path/volume')


def snapshot(path):
    root = Path(path).resolve(strict=True)
    names = {p.name.upper(): p for p in root.iterdir()}
    candidates = [names[k] for k in ('BDMV', 'VIDEO_TS') if k in names]
    if len(candidates) != 1:
        raise ArchiveError('Ambiguous or missing disc structure: expected exactly one BDMV or VIDEO_TS')
    folder = candidates[0]
    extensions = {'.bdmv', '.mpls', '.clpi'} if folder.name.upper() == 'BDMV' else {'.ifo', '.bup'}
    controls = sorted((p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in extensions), key=lambda p: str(p.relative_to(root)).casefold())
    if not controls:
        raise ArchiveError('Disc control files are missing')
    h = hashlib.sha256()
    for p in controls:
        h.update(str(p.relative_to(root)).encode() + b'\0' + str(p.stat().st_size).encode() + b'\0' + bytes.fromhex(digest(p)))
    return h.hexdigest(), 'Blu-ray' if folder.name.upper() == 'BDMV' else 'DVD'


def robot_records(text, record):
    for line in text.splitlines():
        if line.startswith(record + ':'):
            try:
                yield next(csv.reader([line.split(':', 1)[1]]))
            except (csv.Error, StopIteration):
                continue


def language(stream):
    lang = stream.get('tags', {}).get('language', '').lower()
    return {'en': 'eng', 'de': 'deu', 'ger': 'deu'}.get(lang, lang)


def main_audio(stream):
    disp = stream.get('disposition', {})
    title = stream.get('tags', {}).get('title', '').lower()
    special = any(disp.get(k) for k in ('comment', 'hearing_impaired', 'visual_impaired', 'descriptions')) or any(k in title for k in ('commentary', 'description', 'descriptive'))
    codec = stream.get('codec_name', '')
    fidelity = 3 if codec in ('truehd', 'flac', 'pcm_s24le') or 'MA' in stream.get('profile', '') else 2 if codec in ('dts', 'eac3') else 1
    return (not special, fidelity, stream.get('channels', 0), -stream['index'])


class Engine:
    def __init__(self, state_dir, tools=None, start_worker=True):
        self.state_dir = Path(state_dir).resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        self.lockfile = (self.state_dir / 'owner.lock').open('a+')
        try:
            fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lockfile.close()
            raise ArchiveError('Another archive engine already owns this state directory')
        self.mutex = threading.RLock()
        self.closed = False
        self.scanning = False
        self.scan_lock = threading.Lock()
        self.pipeline_lock = threading.Lock()
        self.poll_signature = None
        self.wake = threading.Event()
        self.tools = tools or {name: shutil.which(name) or (path if Path(path).is_file() else None) for name, path in dict(ffmpeg='/opt/homebrew/bin/ffmpeg', ffprobe='/opt/homebrew/bin/ffprobe', makemkv='/Applications/MakeMKV.app/Contents/MacOS/makemkvcon').items()}
        self.db = sqlite3.connect(self.state_dir / 'archive.sqlite3', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))')
        self.db.commit()
        self.discs = []
        if not self._get('settings', 'settings'):
            self._save('settings', 'settings', DEFAULTS.copy())
        # A committed phase is resumable; any interrupted phase restarts in a new path.
        for job in self.jobs():
            if job['state'] in ('running', 'queued'):
                job.update(state='paused', safe_to_disconnect=True, message='Recovered after interruption; resume restarts the unfinished phase in a new candidate')
                self._job_save(job)
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.heartbeat_thread = threading.Thread(target=self._heartbeat, daemon=True)
        if start_worker:
            self.thread.start()
            self.heartbeat_thread.start()

    def _get(self, kind, key):
        with self.mutex:
            row = self.db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
            return json.loads(row[0]) if row else None

    def _all(self, kind):
        with self.mutex:
            return [json.loads(row[0]) for row in self.db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid', (kind,))]

    def _save(self, kind, key, body):
        with self.mutex:
            self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)', (kind, key, json.dumps(body)))
            self.db.commit()

    def _job_save(self, job, reset_requests=False):
        with self.mutex:
            latest = self._get('job', job['id'])
            if latest and not reset_requests:
                for key in ('pause_requested', 'cancel_requested'):
                    job[key] = job.get(key, False) or latest.get(key, False)
            job['updated_at'] = now()
            self._save('job', job['id'], job)

    def settings(self, changes=None):
        with self.mutex:
            old = self._get('settings', 'settings')
            if changes is None:
                return old
            if any(j['state'] in ('running', 'queued') for j in self.jobs()) and any(k != 'auto_start' and changes.get(k) != old.get(k) for k in changes):
                raise ArchiveError('Pause jobs at a checkpoint before changing processing settings')
            if not isinstance(changes, dict) or set(changes) - set(DEFAULTS) - {'_identity'}:
                raise ArchiveError('Unknown settings fields')
            v = dict(old, **changes)
            if type(v['auto_start']) is not bool or v['video_codec'] not in ('hevc', 'h264') or type(v['quality']) is not int or not 0 <= v['quality'] <= 51:
                raise ArchiveError('Invalid auto_start, video_codec or quality')
            if not isinstance(v['languages'], list) or not v['languages'] or any(not isinstance(x, str) or not re.fullmatch('[a-z]{3}', x) for x in v['languages']) or len(set(v['languages'])) != len(v['languages']):
                raise ArchiveError('Languages must be unique three-letter codes')
            if v['output_root'] and v['output_root'] != old['output_root']:
                p = Path(v['output_root']).expanduser().resolve(strict=True)
                if not p.is_dir():
                    raise ArchiveError('Output root must be an existing directory on the intended volume')
                v['output_root'] = str(p)
                v['_identity'] = identity(p)
            elif v['output_root']:
                v['_identity'] = old.get('_identity')
            else:
                v.pop('_identity', None)
            self._save('settings', 'settings', v)
            if v['auto_start'] and not old['auto_start']:
                self.poll_signature = None
                self.wake.set()
            return v

    def jobs(self):
        return self._all('job')

    def job(self, job_id):
        result = self._get('job', job_id)
        if not result:
            raise ArchiveError('Job not found')
        return result

    def profiles(self):
        return self._all('profile')

    def profile(self, data):
        self._validate_mapping(data)
        if not re.fullmatch('[a-f0-9]{64}', str(data.get('disc_id', ''))):
            raise ArchiveError('Profile requires exact structural disc SHA-256 ID')
        if not any(d['id'] == data['disc_id'] for d in self.discs):
            raise ArchiveError('Scan this exact disc before saving its profile')
        disc = next(d for d in self.discs if d['id'] == data['disc_id'])
        available = {t['id'] for t in disc['titles']}
        if any(t['id'] not in available for t in data['titles']):
            raise ArchiveError('Mapped title is absent from the current scan')
        value = {k: data[k] for k in ('disc_id', 'collection', 'kind', 'titles')}
        self._save('profile', data['disc_id'], value)
        return value

    def _validate_mapping(self, data):
        safe_name(data.get('collection'))
        if data.get('kind') not in ('film', 'series', 'extras'):
            raise ArchiveError('Choose film, series or extras')
        titles = data.get('titles')
        if not isinstance(titles, list) or not titles:
            raise ArchiveError('Exact title identification is required; duration does not establish identity')
        ids, names = set(), set()
        for t in titles:
            if not isinstance(t, dict) or type(t.get('id')) is not int or t['id'] < 0:
                raise ArchiveError('Title IDs must be nonnegative integers')
            name = safe_name(t.get('name'))
            if t['id'] in ids or name.casefold() in names:
                raise ArchiveError('Duplicate title IDs or output names are ambiguous')
            ids.add(t['id']); names.add(name.casefold())

    def scan(self, auto_start=False):
        with self.mutex:
            if self.closed: raise ArchiveError('Engine is shutting down')
            if not self.scan_lock.acquire(blocking=False):
                raise ArchiveError('Disc scan already in progress')
            self.scanning = True
        try:
            return self._scan(auto_start)
        finally:
            self.scanning = False
            self.scan_lock.release()

    def _scan(self, auto_start):
        # Only mounted paths are considered; never create or acquire from them.
        discs = []
        if self.tools.get('makemkv'):
            r = subprocess.run([self.tools['makemkv'], '-r', '--minlength=0', 'info', 'disc:9999'], capture_output=True, text=True, timeout=90)
            if r.returncode:
                raise ArchiveError('MakeMKV scan failed: ' + r.stderr[-400:])
            for row in robot_records(r.stdout, 'DRV'):
                if len(row) < 7 or not row[6]:
                    continue
                mount_path = self._drive_mount(row[6])
                if not mount_path: continue
                try:
                    fp, fmt = snapshot(mount_path)
                    info = subprocess.run([self.tools['makemkv'], '-r', '--minlength=0', 'info', 'disc:' + row[0]], capture_output=True, text=True, timeout=120)
                    if info.returncode:
                        raise ArchiveError('MakeMKV title inspection failed')
                    titles = {}
                    for t in robot_records(info.stdout, 'TINFO'):
                        if len(t) >= 4 and t[0].isdigit():
                            item = titles.setdefault(int(t[0]), dict(id=int(t[0]), name='Unidentified title ' + t[0], duration='', size='', selected=False))
                            if t[1] == '9': item['duration'] = t[3]
                            if t[1] == '10': item['size'] = t[3]
                    inventory = {}
                    for stream in robot_records(info.stdout, 'SINFO'):
                        if len(stream) >= 5 and stream[0].isdigit() and stream[1].isdigit():
                            inventory.setdefault(stream[0], {}).setdefault(stream[1], {})[stream[2]] = stream[4]
                    profile = self._get('profile', fp)
                    if profile:
                        for mapped in profile['titles']:
                            if mapped['id'] in titles:
                                titles[mapped['id']]['name'] = mapped['name']
                                titles[mapped['id']]['selected'] = True
                    discs.append(dict(id=fp, label=row[5], format=fmt, source_path=str(Path(mount_path).resolve()), drive_index=int(row[0]), identified=bool(profile), collection=profile['collection'] if profile else None, kind=profile['kind'] if profile else None, selected_titles=profile['titles'] if profile else [], stream_inventory=inventory, titles=list(titles.values()), message='Saved exact mapping' if profile else 'needs_identification: establish content and map titles'))
                except (OSError, ValueError) as e:
                    discs.append(dict(id='', label=row[5], format='unknown', source_path=mount_path, drive_index=int(row[0]), identified=False, collection=None, titles=[], message=str(e)))
        counts = {}
        for d in discs: counts[d['id']] = counts.get(d['id'], 0) + 1
        for d in discs:
            if d['id'] and counts[d['id']] > 1:
                d.update(identified=False, message='Ambiguous duplicate structural identity; automatic acquisition blocked')
        with self.mutex:
            self.discs = discs
        if auto_start and self.settings()['auto_start']:
            for d in discs:
                if d['identified'] and not any(j.get('disc_id') == d['id'] for j in self.jobs()):
                    p = self._get('profile', d['id'])
                    self.create_job(dict(p, source_path=d['source_path'], stop_after='complete'))
        return discs

    def _drive_mount(self, device):
        if Path(device).is_dir(): return device  # Synthetic fixtures/local test source.
        if sys.platform != 'darwin': return None
        r = subprocess.run(['/usr/sbin/diskutil', 'info', '-plist', device], capture_output=True, timeout=15)
        if r.returncode: return None
        try:
            info = plistlib.loads(r.stdout)
            mount = info.get('MountPoint')
            return mount if mount and Path(mount).is_dir() else None
        except (ValueError, plistlib.InvalidFileException): return None

    def create_job(self, data):
        with self.mutex:
            if self.closed: raise ArchiveError('Engine is shutting down')
            self._validate_mapping(data)
            if data.get('stop_after', 'complete') not in PHASES:
                raise ArchiveError('Invalid stop_after phase')
            settings = self.settings()
            if not settings['output_root']:
                raise ArchiveError('Choose an existing destination directory first')
            check_identity(settings['_identity'])
            p = Path(data.get('source_path', '')).expanduser().resolve(strict=True)
            source = identity(p, p.is_file())
            disc_id = None; drive = None; streams = {}
            if p.is_dir():
                disc_id, _ = snapshot(p)
                matches = [d for d in self.discs if d['id'] == disc_id]
                if data.get('disc_id') != disc_id or len(matches) != 1 or matches[0]['source_path'] != str(p):
                    raise ArchiveError('Scan and select the exact unambiguous disc identity before acquisition')
                available = {t['id'] for t in matches[0]['titles']}
                if any(t['id'] not in available for t in data['titles']):
                    raise ArchiveError('Selected title is absent from this disc scan')
                drive = matches[0]['drive_index']
                streams = matches[0].get('stream_inventory', {})
            elif not p.is_file() or len(data['titles']) != 1 or data['titles'][0]['id'] != 0:
                raise ArchiveError('Local media sources require exactly title ID 0')
            if any(j['state'] in ('running', 'queued') and j['source_path'] == str(p) for j in self.jobs()):
                raise ArchiveError('This source already has an active job')
            jid = uuid.uuid4().hex
            output = Path(settings['output_root']) / safe_name(data['collection'])
            job = dict(id=jid, collection=data['collection'], kind=data['kind'], state='queued', phase='scan', checkpoint='', stop_after=data.get('stop_after', 'complete'), source_path=str(p), output_path=str(output), progress=0, message='Queued; exact content mapping supplied by user', safe_to_disconnect=False, titles=data['titles'], created_at=now(), updated_at=now(), disc_id=disc_id, drive_index=drive, source_identity=source, destination_identity=settings['_identity'], settings=settings, artifacts=[], reports=[], pause_requested=False, cancel_requested=False, disc_streams=streams, phase_progress=None, current_title=None, processed_bytes=None, total_bytes=None, completed_items=0, total_items=len(data['titles']), elapsed_seconds=0, throughput_bps=None, eta_seconds=None, last_progress_at=None, heartbeat_at=now(), stall_reason=None, next_checkpoint='scan', progress_basis='completed checkpoints')
            self._safe_descendant(job, output)
            self._job_save(job); self.wake.set()
            return job

    def action(self, jid, data):
        with self.mutex:
            job = self.job(jid); action = data.get('action')
            if action not in ('resume', 'pause_after_checkpoint', 'next_checkpoint', 'cancel'):
                raise ArchiveError('Unknown job action')
            if job['state'] in ('completed', 'cancelled'):
                raise ArchiveError('This job is terminal; create a new job')
            if action == 'pause_after_checkpoint':
                if job['state'] in ('running', 'queued'):
                    job['pause_requested'] = True
            elif action == 'cancel':
                job['cancel_requested'] = True
                if job['state'] != 'running': job.update(state='cancelled', safe_to_disconnect=True)
                job['message'] = 'Cancel requested; candidates and originals retained'
            else:
                if job['state'] == 'running':
                    raise ArchiveError('Job is running; pause after checkpoint first')
                stop = data.get('stop_after', job['stop_after'])
                if action == 'next_checkpoint':
                    index = PHASES.index(job['checkpoint']) + 1 if job['checkpoint'] else 0
                    stop = PHASES[min(index, len(PHASES)-1)]
                if stop not in PHASES: raise ArchiveError('Invalid stop_after phase')
                if job['checkpoint'] and PHASES.index(stop) <= PHASES.index(job['checkpoint']):
                    raise ArchiveError('Choose a phase after the current checkpoint or use next_checkpoint')
                job.update(state='queued', safe_to_disconnect=False, pause_requested=False, cancel_requested=False, stop_after=stop, message='Queued to resume from committed checkpoint')
            self._job_save(job, reset_requests=action in ('resume', 'next_checkpoint')); self.wake.set()
            return job

    def status(self):
        jobs = self.jobs()
        return dict(settings=self.settings(), jobs=jobs, discs=self.discs, tools=self.tools, safe_to_disconnect=not self.scanning and not any(j['state'] in ('running', 'queued') for j in jobs), message='Originals retained; physical playback and perceptual acceptance require review')

    def report(self, jid):
        j = self.job(jid)
        return dict(job_id=jid, state=j['state'], checkpoint=j['checkpoint'], reports=j['reports'], artifacts=j['artifacts'], originals_retained=True, perceptual_acceptance='pending', tv_acceptance='pending', content_identity='user-supplied mapping; not inferred from duration', subtitles='Original tracks retained in MKV; text export when supported; bitmap/OCR acceptance pending')

    def _heartbeat(self):
        while not self.closed:
            with self.mutex:
                for j in self.jobs():
                    if j['state'] == 'running':
                        j['heartbeat_at'] = now()
                        self._save('job', j['id'], j)
            time.sleep(1)

    def _worker(self):
        while not self.closed:
            job = next((j for j in self.jobs() if j['state'] == 'queued'), None)
            if job:
                self.run_job(job['id'])
            else:
                try:
                    mounts = Path('/Volumes')
                    signature = tuple(sorted((str(p), p.stat().st_dev, p.stat().st_ino) for p in mounts.iterdir() if p.is_dir() and ((p/'BDMV').is_dir() or (p/'VIDEO_TS').is_dir()))) if mounts.is_dir() else ()
                    if signature != self.poll_signature:
                        self.poll_signature = signature
                        if signature: self.scan(auto_start=True)
                        else: self.discs = []
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
                self.wake.wait(2); self.wake.clear()

    def _guards(self, job, require_source=False):
        check_identity(job['destination_identity'])
        if require_source:
            check_identity(job['source_identity'], Path(job['source_path']).is_file())
            if job['disc_id']:
                fp, _ = snapshot(job['source_path'])
                if fp != job['disc_id']: raise ArchiveError('The inserted disc content changed')
        self._safe_descendant(job, job['output_path'])
        for a in job['artifacts']:
            for key in ('original', 'candidate', 'final', 'acquisition_candidate'):
                if a.get(key): self._safe_descendant(job, a[key])
            if a.get('original') and a.get('acquisition_committed', True):
                if not Path(a['original']).is_file() or digest(a['original']) != a['original_sha256']:
                    raise ArchiveError('A retained original is missing or changed')

    def run_job(self, jid):
        # Worker and direct callers cannot run pipeline concurrently.
        if not self.pipeline_lock.acquire(blocking=False):
            raise ArchiveError('An archive phase is already running')
        try:
            job = self.job(jid)
            if job['state'] != 'queued': return
            while True:
                idx = PHASES.index(job['checkpoint']) + 1 if job['checkpoint'] else 0
                phase = PHASES[idx]
                job.update(state='running', phase=phase, safe_to_disconnect=False, message='Running ' + phase, phase_progress=None, completed_items=0, current_title=None, processed_bytes=None, total_bytes=None, elapsed_seconds=0, throughput_bps=None, eta_seconds=None, next_checkpoint=phase, heartbeat_at=now(), stall_reason=None)
                self._job_save(job)
                self._guards(job, phase in ('scan', 'acquire'))
                if phase == 'scan':
                    if Path(job['source_path']).is_file(): self.probe(job['source_path'])
                elif phase == 'acquire': self._acquire(job)
                elif phase == 'encode': self._encode(job)
                elif phase == 'verify': self._verify(job)
                else: self._promote(job)
                with self.mutex:
                    # Re-read requests without clobbering phase-produced artifacts.
                    latest = self.job(jid)
                    job.update(pause_requested=latest['pause_requested'], cancel_requested=latest['cancel_requested'])
                    job.update(checkpoint=phase, progress=(idx+1)/len(PHASES), message='Committed ' + phase + ' checkpoint', phase_progress=1.0, completed_items=len(job['titles']), last_progress_at=now(), heartbeat_at=now(), next_checkpoint=PHASES[min(idx+1,4)])
                    if phase == 'complete': job.update(state='completed', safe_to_disconnect=True, message='Technical archive complete; originals retained; perceptual and TV acceptance pending')
                    elif job['cancel_requested']: job.update(state='cancelled', safe_to_disconnect=True)
                    elif job['pause_requested'] or job['stop_after'] == phase: job.update(state='paused', safe_to_disconnect=True)
                    self._job_save(job)
                if job['state'] != 'running': break
        except Exception as e:
            job = self.job(jid)
            job.update(state='blocked' if isinstance(e, (ArchiveError, OSError)) else 'failed', safe_to_disconnect=True, message=str(e))
            self._job_save(job)
        finally:
            self.pipeline_lock.release()

    def _run(self, command, log, timeout=None, job=None, duration=None, title=None):
        if not command[0]: raise ArchiveError('Required processing tool is unavailable')
        began = time.monotonic(); advanced = began; last_persist = 0; current_time = 0; current_bytes = 0
        if job: job.update(phase_progress=None, processed_bytes=None, total_bytes=None, current_title=title, throughput_bps=None, eta_seconds=None)
        lines = queue.Queue()
        with open(log, 'x') as out:
            out.write(json.dumps(command) + '\n'); out.flush()
            # Shared inherited owner descriptor keeps lock until supervisor kills an
            # orphaned tool. A new engine cannot falsely report safe while it runs.
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('runner.py')), str(os.getpid()), *command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, pass_fds=(self.lockfile.fileno(),))
            def read_output():
                for line in process.stdout: lines.put(line)
                lines.put(None)
            reader = threading.Thread(target=read_output, daemon=True); reader.start()
            eof = False
            while not eof:
                try: line = lines.get(timeout=.5)
                except queue.Empty: line = ''
                if line is None: eof = True
                elif line:
                    out.write(line); out.flush()
                    fraction = None; moved = False
                    if line.startswith('PRGV:'):
                        try:
                            row = next(robot_records(line, 'PRGV'))
                            fraction = min(1., max(0., float(row[1])/float(row[2])))
                        except (ValueError, ZeroDivisionError, IndexError, StopIteration): pass
                    elif line.startswith('out_time_us='):
                        try:
                            seconds = float(line.split('=',1)[1])/1000000
                            moved = seconds > current_time; current_time = max(current_time, seconds)
                            if duration and duration > 0: fraction = min(1., current_time/duration)
                        except ValueError: pass
                    elif line.startswith('total_size='):
                        try:
                            size = int(line.split('=',1)[1]); moved = size > current_bytes; current_bytes=max(current_bytes,size)
                        except ValueError: pass
                    if job and fraction is not None:
                        moved = moved or fraction > (job.get('phase_progress') or 0)
                        job['phase_progress'] = max(job.get('phase_progress') or 0, fraction)
                    if moved:
                        advanced=time.monotonic()
                        if job: job['last_progress_at']=now()
                elapsed=time.monotonic()-began
                if job and (time.monotonic()-last_persist >= .5 or eof):
                    job.update(current_title=title, elapsed_seconds=round(elapsed,3), processed_bytes=current_bytes or None, total_bytes=None, throughput_bps=round(current_bytes/elapsed,2) if current_bytes and elapsed else None, eta_seconds=((duration-current_time)*elapsed/current_time) if duration and current_time and duration>current_time else None, heartbeat_at=now(), stall_reason='No measured tool progress for 120 seconds; engine heartbeat continues; review media progress' if time.monotonic()-advanced>120 else None)
                    self._job_save(job); last_persist=time.monotonic()
                if timeout and elapsed>timeout:
                    process.terminate(); process.wait(timeout=10); raise ArchiveError('Processing timed out; candidate retained')
            code=process.wait(); reader.join(timeout=1); process.stdout.close()
        if code: raise ArchiveError('Processing failed (exit ' + str(code) + '); inspect ' + str(log))

    def _verify_acquired_inventory(self, job, title, probe):
        expected = job.get('disc_streams', {}).get(str(title['id']), {})
        if not expected: raise ArchiveError('MakeMKV stream inventory missing; cannot prove complete original acquisition')
        for role, kind in [('Video','video'), ('Audio','audio'), ('Subtitles','subtitle')]:
            expected_streams=[v for v in expected.values() if v.get('1') == role]
            actual=[v for v in probe['streams'] if v['codec_type']==kind]
            if len(actual)<len(expected_streams): raise ArchiveError('Acquisition omitted source ' + kind + ' streams')
            if kind in ('audio','subtitle'):
                for lang in {v.get('3') for v in expected_streams if v.get('3')}:
                    if sum(language(v)=={'ger':'deu'}.get(lang,lang) for v in actual)<sum(v.get('3')==lang for v in expected_streams):
                        raise ArchiveError('Acquisition omitted source ' + kind + ' language ' + lang)

    def probe(self, path):
        if not self.tools.get('ffprobe'): raise ArchiveError('ffprobe is unavailable')
        r = subprocess.run([self.tools['ffprobe'], '-v', 'error', '-show_streams', '-show_format', '-show_chapters', '-of', 'json', str(path)], capture_output=True, text=True, timeout=120)
        if r.returncode: raise ArchiveError('Media probe failed: ' + r.stderr[-500:])
        value = json.loads(r.stdout)
        if not any(s['codec_type'] == 'video' for s in value.get('streams', [])):
            raise ArchiveError('No readable video stream found')
        return value

    def _safe_descendant(self, job, path):
        base = Path(job['destination_identity']['path'])
        target = Path(path)
        if any(part in ('.', '..') for part in target.parts): raise ArchiveError('Output contains an unsafe path component')
        try: relative = target.relative_to(base)
        except ValueError: raise ArchiveError('Output escaped the chosen destination')
        cursor = base
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink(): raise ArchiveError('Output path contains a symlink; choose a real destination folder')
        if not target.resolve().is_relative_to(base): raise ArchiveError('Output escaped the chosen destination')

    def _attempt(self, job, phase):
        self._guards(job)
        root = Path(job['output_path'])
        root.mkdir(parents=True, exist_ok=True)
        attempt = root / '.work' / job['id'] / (phase + '-' + uuid.uuid4().hex)
        self._safe_descendant(job, attempt)
        attempt.mkdir(parents=True)
        return attempt

    def _decode(self, path, log, job=None, title=None):
        self._run([self.tools['ffmpeg'], '-nostdin', '-hide_banner', '-v', 'warning', '-xerror', '-err_detect', 'explode', '-progress', 'pipe:1', '-stats_period', '0.5', '-i', str(path), '-map', '0:v', '-map', '0:a?', '-f', 'null', '-'], log, job=job, duration=float(self.probe(path)['format'].get('duration', 0)), title=title)
        # Warnings are evidence requiring review, even with successful exit.
        return [line for line in Path(log).read_text().splitlines()[1:] if line and not re.match(r'^[a-z_0-9]+=.*$', line)]

    def _acquire(self, job):
        attempt = self._attempt(job, 'acquire'); artifacts = job['artifacts']
        original_dir = Path(job['output_path']) / 'Original_MKV'
        self._safe_descendant(job, original_dir)
        original_dir.mkdir(exist_ok=True)
        for title in job['titles']:
            existing = next((a for a in artifacts if a['title_id'] == title['id']), None)
            if existing:
                if not existing.get('acquisition_committed', True):
                    self._commit_original(job, existing)
                continue
            self._guards(job, True)
            dest = attempt / (safe_name(title['name']) + '.mkv')
            if job['disc_id']:
                # Re-scan drive assignments, as indices can change between acquisitions.
                discs = self.scan(auto_start=False)
                matches = [d for d in discs if d['id'] == job['disc_id'] and d['source_path'] == job['source_path']]
                if len(matches) != 1: raise ArchiveError('Disc is missing or ambiguous after fresh drive scan')
                extraction = attempt / ('title-' + str(title['id'])); extraction.mkdir()
                profile = attempt / ('all-streams-' + str(title['id']) + '.mmcp.xml')
                profile.write_text('<?xml version="1.0"?><profile><name lang="eng">Archive all source tracks</name><outputSettings name="copy" outputFormat="directCopy"/><trackSettings input="default"><output outputSettingsName="copy" defaultSelection="+sel:all"/></trackSettings></profile>')
                self._run([self.tools['makemkv'], '-r', '--minlength=0', '--profile=' + str(profile), '--progress=-same', 'mkv', 'disc:' + str(matches[0]['drive_index']), str(title['id']), str(extraction)], attempt / ('extract-' + str(title['id']) + '.log'), job=job, title=title['name'])
                log_text = (attempt / ('extract-' + str(title['id']) + '.log')).read_text()
                if 'MSG:5003,' in log_text: raise ArchiveError('MakeMKV reported a failed title despite successful exit')
                for record in robot_records(log_text, 'MSG'):
                    if record[0] == '5004' and len(record) >= 7 and (record[-2] != '1' or record[-1] != '0'):
                        raise ArchiveError('MakeMKV saved/failed title counts do not match one selected title')
                candidates = list(extraction.glob('*.mkv'))
                if len(candidates) != 1: raise ArchiveError('Expected exactly one complete extracted title MKV')
                os.link(candidates[0], dest)
            else:
                self._run([self.tools['ffmpeg'], '-nostdin', '-v', 'warning', '-progress', 'pipe:1', '-stats_period', '0.5', '-n', '-i', job['source_path'], '-map', '0', '-c', 'copy', str(dest)], attempt / 'remux.log', job=job, duration=float(self.probe(job['source_path'])['format'].get('duration',0)), title=title['name'])
            probe = self.probe(dest)
            if job['disc_id']: self._verify_acquired_inventory(job, title, probe)
            warnings = self._decode(dest, attempt / ('original-decode-' + str(title['id']) + '.log'), job=job, title=title['name'])
            if warnings: raise ArchiveError('Original decode produced warnings; retained for review in ' + str(attempt))
            self._guards(job, True)
            original = original_dir / (safe_name(title['name']) + '.mkv')
            # link is atomic no-clobber; a duplicate remains at its candidate path.
            self._fsync(dest)
            artifact = dict(title_id=title['id'], name=title['name'], original=str(original), original_sha256=digest(dest), source_probe=probe, acquisition_candidate=str(dest), acquisition_committed=False)
            artifacts.append(artifact)
            job['artifacts'] = artifacts
            self._sync_tree(job, dest)
            self._job_save(job)  # Intent before link; a crash can replay without overwrite.
            self._commit_original(job, artifact)

    def _commit_original(self, job, artifact):
        self._guards(job)
        candidate = Path(artifact['acquisition_candidate'])
        if not candidate.is_file() or digest(candidate) != artifact['original_sha256']:
            raise ArchiveError('Verified acquisition candidate missing or changed')
        original = Path(artifact['original'])
        if original.exists():
            if not os.path.samefile(original, candidate):
                raise ArchiveError('Original output exists; never overwrite ' + str(original))
        else:
            os.link(candidate, original)
        self._fsync(original)
        self._sync_tree(job, original)
        artifact['acquisition_committed'] = True
        job['completed_items'] = sum(a.get('acquisition_committed', True) for a in job['artifacts'])
        self._job_save(job)

    def _encode(self, job):
        attempt = self._attempt(job, 'encode')
        for a in job['artifacts']:
            self._guards(job)
            src = self.probe(a['original']); video = [s for s in src['streams'] if s['codec_type'] == 'video']
            if len(video) != 1: raise ArchiveError('Multiple video streams require an explicit feature-preserving plan')
            v = video[0]
            if v.get('pix_fmt') not in ('yuv420p', 'yuv420p10le') or v.get('color_transfer') in ('smpte2084', 'arib-std-b67') or v.get('color_primaries') == 'bt2020' or v.get('side_data_list') or v.get('field_order') not in (None, 'unknown', 'progressive') or v.get('sample_aspect_ratio') not in (None, 'N/A', '1:1'):
                raise ArchiveError('HDR, interlace, anamorphic, unusual chroma or special video features need a reviewed plan; original retained')
            if job['settings']['video_codec'] == 'h264' and v['pix_fmt'] != 'yuv420p': raise ArchiveError('H.264 fallback cannot reduce source bit depth')
            audio = [s for s in src['streams'] if s['codec_type'] == 'audio']
            if any(language(s) in ('', 'und') for s in audio): raise ArchiveError('Unknown audio language requires identification before export')
            chosen = []
            for lang in job['settings']['languages']:
                matches = [s for s in audio if language(s) == lang]
                if matches: chosen.append(max(matches, key=main_audio))
            if audio and not chosen: raise ArchiveError('No source audio matches requested languages; review the policy')
            target = attempt / (safe_name(a['name']) + '.mp4')
            cmd = [self.tools['ffmpeg'], '-nostdin', '-hide_banner', '-v', 'warning', '-progress', 'pipe:1', '-stats_period', '0.5', '-n', '-i', a['original'], '-map', '0:' + str(v['index'])]
            for s in chosen: cmd += ['-map', '0:' + str(s['index'])]
            text = [s for s in src['streams'] if s['codec_type'] == 'subtitle' and s.get('codec_name') in ('subrip', 'ass', 'ssa', 'mov_text', 'webvtt', 'text')]
            for s in text: cmd += ['-map', '0:' + str(s['index'])]
            codec = 'libx265' if job['settings']['video_codec'] == 'hevc' else 'libx264'
            cmd += ['-c:v', codec, '-preset', 'medium', '-crf', str(job['settings']['quality']), '-pix_fmt', v['pix_fmt']]
            if codec == 'libx265': cmd += ['-tag:v', 'hvc1', '-x265-params', 'pools=2:log-level=error']
            for key, flag in [('color_range', '-color_range'), ('color_space', '-colorspace'), ('color_transfer', '-color_trc'), ('color_primaries', '-color_primaries')]:
                if v.get(key) not in (None, 'unknown'): cmd += [flag, v[key]]
            cmd += ['-c:a', 'aac', '-b:a', '384k', '-c:s', 'mov_text', '-map_chapters', '0', '-movflags', '+faststart']
            for i, s in enumerate(chosen):
                cmd += ['-metadata:s:a:' + str(i), 'language=' + language(s), '-disposition:a:' + str(i), 'default' if i == 0 else '0']
            cmd += [str(target)]
            self._run(cmd, attempt / ('encode-' + str(a['title_id']) + '.log'), job=job, duration=float(src['format'].get('duration',0)), title=a['name'])
            self._fsync(target)
            self._sync_tree(job, target)
            a.update(candidate=str(target), audio_map=[dict(source_index=s['index'], language=language(s), channels=s['channels']) for s in chosen], text_subtitles=len(text), bitmap_subtitles=sum(s['codec_type'] == 'subtitle' for s in src['streams'])-len(text))
            job['completed_items'] += 1
            self._job_save(job)

    def _verify(self, job):
        attempt = self._attempt(job, 'verify'); reports = []
        for a in job['artifacts']:
            src = self.probe(a['original']); out = self.probe(a['candidate'])
            sv = next(s for s in src['streams'] if s['codec_type'] == 'video'); ov = next(s for s in out['streams'] if s['codec_type'] == 'video')
            for k in ('width', 'height', 'pix_fmt', 'r_frame_rate', 'sample_aspect_ratio', 'color_range', 'color_space', 'color_transfer', 'color_primaries'):
                if sv.get(k) not in (None, 'unknown', 'N/A') and sv.get(k) != ov.get(k): raise ArchiveError('Output differs from source ' + k)
            sd = float(src['format'].get('duration', 0)); od = float(out['format'].get('duration', 0))
            if sd <= 0 or abs(sd-od) > max(.5, sd*.001): raise ArchiveError('Source/output duration mismatch')
            audio = [s for s in out['streams'] if s['codec_type'] == 'audio']
            if len(audio) != len(a['audio_map']): raise ArchiveError('Audio track count mismatch')
            for i, (s, expected) in enumerate(zip(audio, a['audio_map'])):
                if s.get('codec_name') != 'aac' or language(s) != expected['language'] or s.get('channels') != expected['channels'] or bool(s.get('disposition', {}).get('default')) != (i == 0): raise ArchiveError('Audio language/channel/default mapping mismatch')
            if sum(s['codec_type'] == 'subtitle' for s in out['streams']) != a['text_subtitles']: raise ArchiveError('Text subtitle track count mismatch')
            warnings = self._decode(a['candidate'], attempt / ('decode-' + str(a['title_id']) + '.log'), job=job, title=a['name'])
            if warnings: raise ArchiveError('Full decode produced warnings; candidate retained for review')
            a['candidate_sha256'] = digest(a['candidate'])
            report = dict(title=a['name'], technical_validation='passed', full_decode='passed', source_duration=sd, output_duration=od, audio_map=a['audio_map'], original_sha256=a['original_sha256'], output_sha256=a['candidate_sha256'], subtitle_packet_validation='pending visual/selectability review', bitmap_subtitles_retained_in_original=a['bitmap_subtitles'], unknown_color_metadata=any(sv.get(k) in (None, 'unknown') for k in ('color_primaries', 'color_transfer', 'color_space')), perceptual_acceptance='pending', tv_acceptance='pending')
            (attempt / (str(a['title_id']) + '.json')).write_text(json.dumps(report, indent=2))
            reports.append(report)
            job['completed_items'] += 1
            self._job_save(job)
        job['reports'] = reports

    def _sync_tree(self, job, file_path):
        base = Path(job['destination_identity']['path'])
        current = Path(file_path).parent
        while current.is_relative_to(base):
            fd = os.open(current, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
            if current == base: break
            current = current.parent

    @staticmethod
    def _fsync(path):
        with open(path, 'rb') as f: os.fsync(f.fileno())
        fd = os.open(str(Path(path).parent), os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def _promote(self, job):
        # Journal each promoted file individually so crash recovery is idempotent.
        for a in job['artifacts']:
            self._guards(job)
            if digest(a['candidate']) != a['candidate_sha256']: raise ArchiveError('Verified candidate changed before promotion')
            final = Path(job['output_path']) / (safe_name(a['name']) + '.mp4')
            if final.exists():
                if not os.path.samefile(final, a['candidate']): raise ArchiveError('Final output already exists; never overwrite ' + str(final))
            else: os.link(a['candidate'], final)
            self._fsync(final); self._sync_tree(job, final); a['final'] = str(final)
            self._job_save(job)

    def close(self):
        with self.mutex:
            if not self.status()['safe_to_disconnect']:
                raise ArchiveError('Pause or finish active jobs before shutdown')
            self.closed = True; self.wake.set()
        if self.thread.is_alive(): self.thread.join(timeout=3)
        if self.heartbeat_thread.is_alive(): self.heartbeat_thread.join(timeout=3)
        self.db.close(); fcntl.flock(self.lockfile, fcntl.LOCK_UN); self.lockfile.close()
