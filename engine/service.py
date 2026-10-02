"""Version 2 control plane, compatible with the original durable pipeline."""
from copy import deepcopy
import hashlib
import fcntl
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from engine.core import Engine as V1Engine, ArchiveError, PHASES, identity, check_identity, safe_name, snapshot, digest, now, language
from engine.schema import DEFAULTS, RECIPE, ENGINE_VERSION, builtins, validate, settings_schema

def busy(method):
    def wrapped(self,*args,**kwargs):
        with self.mutex:self.control_busy+=1
        try:return method(self,*args,**kwargs)
        finally:
            with self.mutex:self.control_busy-=1
    return wrapped

class Conflict(ArchiveError):
    def __init__(self, revision):
        super().__init__('Revision changed; refresh the resource and retry')
        self.current_revision=revision
        self.code='revision_conflict'

class Waiting(ArchiveError):
    def __init__(self,state,message):super().__init__(message);self.state=state

class Stopped(ArchiveError):pass

from engine.transfers import Transfers

class ReviewRequired(ArchiveError):pass

class Engine(Transfers,V1Engine):
    def __init__(self,state_dir,tools=None,start_worker=True):
        self.disconnect_fenced=False; self.processes={};self.process_mutex=threading.RLock();self.transfer_threads={};self.explicit_tools=tools
        self.thread_context=threading.local();self.runtime_threads=[];self.scan_cancel=threading.Event();self.stop_events={};self.control_busy=0
        super().__init__(state_dir,tools=tools,start_worker=False)
        try:self._migrate()
        except BaseException:
            self.db.close();fcntl.flock(self.lockfile,fcntl.LOCK_UN);self.lockfile.close();raise
        self.disconnect_fenced=bool(self._get('control','disconnect') or False)
        self._resolve_tools()
        for j in self.jobs():
            if j.get('cleanup_status')=='deleting'and j.get('cleanup_journal'):
                try:self._finish_cleanup(j)
                except (OSError,ArchiveError)as e:j['cleanup_status']='blocked';j['message']='Cleanup recovery blocked: '+str(e);self._job_save(j)
        for transfer in self._all('export'):
            if transfer['state'] in ('running','queued'):transfer.update(state='paused',message='Recovered; verified files retained, unfinished file restarts');self._save('export',transfer['id'],transfer)
        if start_worker:self.thread.start();self.heartbeat_thread.start()

    def _save(self,kind,key,body):
        if getattr(self,'_migrating',False):
            with self.mutex:self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)',(kind,key,json.dumps(body)))
        else:super()._save(kind,key,body)

    def _migrate(self):
        old=self._get('settings','settings')
        if old.get('schema_version')==2 and all('revision'in j and'plan_revision'in j for j in self.jobs())and all('revision'in p for p in self.profiles()):return
        has_history=bool(self.jobs() or self.profiles() or old.get('output_root'))
        if has_history:
            backup=self.state_dir/('migration-v1-'+uuid.uuid4().hex+'.sqlite3')
            with sqlite3.connect(backup) as target:self.db.backup(target)
            os.chmod(backup,0o600)
        self._migrating=True
        try:
            self.db.execute('BEGIN IMMEDIATE')
            settings=deepcopy(DEFAULTS)
            if has_history:
                settings.update({k:v for k,v in old.items() if k in settings or k.startswith('_')})
                if old.get('schema_version')!=2:settings.update(preset_id='legacy',schema_version=2,revision=1,cleanup_policy='keep',folder_layout='flat',deinterlace='off')
            settings['_recipe_overrides']={k:deepcopy(v)for k,v in old.items()if k in RECIPE}if has_history else{}
            self._save('settings','settings',settings)
            for profile in self.profiles():
                profile.update(revision=profile.get('revision',1),overrides=profile.get('overrides',{}));self._save('profile',profile['disc_id'],profile)
            for job in self.jobs():
                if'revision'in job and'plan_revision'in job:continue
                legacy=deepcopy(DEFAULTS);legacy.update(job['settings']);legacy.update(preset_id='legacy',cleanup_policy='keep',folder_layout='flat',deinterlace='off')
                job.update(schema_version=1,revision=1,plan_revision=1,preset_id='legacy',settings=legacy,queue_order=job.get('queue_order',0),acceptance={'playback':'pending','perceptual':'pending'},checkpoint_detail={'phase':job['checkpoint'],'title_id':None},pending_changes=[],cleanup_status='ineligible_legacy',generation=1,title_checkpoints={},manual_pause=True,pause_cause='recovery')
                for artifact in job['artifacts']:artifact['cleanup_eligible']=False
                self._job_save(job)

            self.db.commit()
        except Exception:
            self.db.rollback();raise
        finally:self._migrating=False

    def _resolve_tools(self):
        if self.explicit_tools is not None:return
        s=self._get('settings','settings');bundle=os.environ.get('DISC_PORTER_BUNDLE_TOOLS','')
        for key,binary,development in [('ffmpeg','ffmpeg','/opt/homebrew/bin/ffmpeg'),('ffprobe','ffprobe','/opt/homebrew/bin/ffprobe'),('makemkv','makemkvcon','/Applications/MakeMKV.app/Contents/MacOS/makemkvcon')]:
            override=s.get(key+'_path',''); bundled=Path(bundle)/binary if bundle else None
            if override:
                if not Path(override).is_file()or not os.access(override,os.X_OK):self.tools[key]=None
                else:self.tools[key]=override
            elif bundled and bundled.is_file():self.tools[key]=str(bundled)
            else:self.tools[key]=shutil.which(binary) or (development if Path(development).is_file() else None)

    def _revision(self,resource,data,allow_legacy=False):
        supplied=data.get('expected_revision')
        if supplied is None:
            if not allow_legacy:raise ArchiveError('expected_revision is required; refresh this resource')
        elif supplied!=resource.get('revision',1):raise Conflict(resource.get('revision',1))

    def _event(self,operation,resource_id,result='ok',actor='local-client'):
        with self.mutex:
            last=self.db.execute("SELECT MAX(CAST(id AS INTEGER)) FROM records WHERE kind='event'").fetchone()[0] or 0
            seq=last+1
            self.db.execute('INSERT INTO records VALUES(?,?,?)',('event',str(seq),json.dumps(dict(sequence=seq,time=now(),actor=actor,operation=operation,resource_id=resource_id,result=result))))
            self.db.execute("DELETE FROM records WHERE kind='event' AND CAST(id AS INTEGER) < ?",(max(0,seq-5000),));self.db.commit()

    def events(self,after=0,limit=100):
        after=max(0,int(after));limit=min(500,max(1,int(limit)))
        with self.mutex:values=[json.loads(r[0]) for r in self.db.execute("SELECT body FROM records WHERE kind='event' AND CAST(id AS INTEGER)>? ORDER BY CAST(id AS INTEGER) LIMIT ?",(after,limit))]
        return dict(events=values,next_cursor=values[-1]['sequence'] if values else after)

    def settings(self,changes=None,legacy=False):
        old=self._get('settings','settings')
        if changes is None:return old
        request=deepcopy(changes);self._revision(old,request,allow_legacy=legacy or set(request)-{'_identity'}<= {'output_root','auto_start','video_codec','quality','languages'})
        request.pop('expected_revision',None);request.pop('_identity',None)
        if not legacy and 'expected_revision' not in changes and set(request)-{'output_root','auto_start','video_codec','quality','languages'}:raise ArchiveError('New settings require expected_revision')
        if legacy:
            unknown={k for k,v in request.items()if k not in('output_root','auto_start','video_codec','quality','languages')and v!=old.get(k)}
            if unknown:raise ArchiveError('Use PATCH /settings with expected_revision for new settings: '+', '.join(sorted(unknown)))
            request={k:v for k,v in request.items()if k in('output_root','auto_start','video_codec','quality','languages')}
        validate(request,patch=True)
        updated=deepcopy(old)
        if request.get('preset_id',old['preset_id'])!=old['preset_id']:
            preset=self.preset(request['preset_id']);updated.update(preset['settings']);updated['_recipe_overrides']={}
        updated.setdefault('_recipe_overrides',{}).update({k:deepcopy(v)for k,v in request.items()if k in RECIPE})
        updated.update(request);validate({k:v for k,v in updated.items() if k in DEFAULTS})
        for field in ('output_root','work_root','original_root'):
            if field in request and request[field]!=old.get(field,''):
                if request[field]:
                    p=Path(request[field]).expanduser().resolve(strict=True)
                    if not p.is_dir():raise ArchiveError(field+' must be an existing destination directory')
                    updated[field]=str(p);updated['_'+field+'_identity']=identity(p)
                    if field=='output_root':updated['_identity']=updated['_'+field+'_identity']
                else:
                    updated.pop('_'+field+'_identity',None)
                    if field=='output_root':updated.pop('_identity',None)
        if updated.get('output_root') and '_identity' not in updated:updated['_identity']=identity(updated['output_root'])
        for name in ('ffmpeg','ffprobe','makemkv'):
            path=updated[name+'_path']
            if path and (not Path(path).is_file() or not os.access(path,os.X_OK)):raise ArchiveError(name+' override must be executable')
        with self.mutex:
            current=self._get('settings','settings')
            if current['revision']!=old['revision']:raise Conflict(current['revision'])
            updated['revision']=old['revision']+1;self._save('settings','settings',updated)
        self._resolve_tools();self._event('settings.update','settings')
        if updated['auto_start'] and not old['auto_start']:self.poll_signature=None;self.wake.set()
        return updated

    def presets(self):return builtins()+self._all('preset')
    def preset(self,pid):
        p=next((p for p in self.presets() if p['id']==pid),None)
        if not p:raise ArchiveError('Preset not found')
        return p
    def create_preset(self,data):
        name=data.get('name','');safe_name(name)
        base=self.preset(data.get('base_id','balanced'));pid=uuid.uuid4().hex
        p=dict(id=pid,name=name,builtin=False,revision=1,settings=deepcopy(base['settings']))
        self._save('preset',pid,p);self._event('preset.create',pid);return p
    def edit_preset(self,pid,data,delete=False):
        with self.mutex:
            p=self.preset(pid)
            if p['builtin']:raise ArchiveError('Built-in presets are immutable; duplicate one first')
            self._revision(p,data)
            if delete:
                if self.settings()['preset_id']==pid:raise ArchiveError('Choose another default preset before deleting this one')
                self.db.execute("DELETE FROM records WHERE kind='preset' AND id=?",(pid,));self.db.commit();self._event('preset.delete',pid);return dict(deleted=True)
            if 'name'in data:safe_name(data['name']);p['name']=data['name']
            validate(data.get('settings',{}),patch=True,recipe=True);p['settings'].update(data.get('settings',{}))
            v=dict(DEFAULTS,**p['settings']);validate(v);p['revision']+=1;self._save('preset',pid,p);self._event('preset.update',pid);return p

    def profile(self,data):
        self._validate_mapping(data);validate(data.get('overrides',{}),patch=True,recipe=True)
        disc=next((d for d in self.discs if d['id']==data.get('disc_id')),None)
        if not disc:raise ArchiveError('Scan the exact disc before storing its profile')
        if any(t['id'] not in {t['id'] for t in disc['titles']} for t in data['titles']):raise ArchiveError('Mapped title absent from scan')
        with self.mutex:
            old=self._get('profile',data['disc_id'])
            if old:self._revision(old,data,allow_legacy=not data.get('overrides'))
            p={k:deepcopy(data[k]) for k in ('disc_id','collection','kind','titles')};p.update(revision=old['revision']+1 if old else 1,overrides=deepcopy(data.get('overrides',{})))
            self._save('profile',p['disc_id'],p);self._event('profile.save',p['disc_id']);return p
    def edit_profile(self,pid,data,delete=False):
        with self.mutex:
            p=self._get('profile',pid)
            if not p:raise ArchiveError('Profile not found')
            self._revision(p,data)
            if delete:self.db.execute("DELETE FROM records WHERE kind='profile' AND id=?",(pid,));self.db.commit();self._event('profile.delete',pid);return dict(deleted=True)
            p.update({k:deepcopy(v) for k,v in data.items() if k in ('collection','kind','titles','overrides')});self._validate_mapping(p);validate(p.get('overrides',{}),patch=True,recipe=True);p['revision']+=1;self._save('profile',pid,p);return p

    def _effective(self,settings,data,profile=None,preset_snapshot=None):
        recipe=deepcopy(settings)
        pid=data.get('preset_id',settings['preset_id'])
        recipe.update((preset_snapshot or self.preset(pid))['settings'])
        if 'preset_id'not in data:recipe.update(settings.get('_recipe_overrides',{}))
        recipe.update((profile or {}).get('overrides',{}));validate(data.get('overrides',{}),patch=True,recipe=True);recipe.update(data.get('overrides',{}))
        recipe['preset_id']=pid;validate({k:v for k,v in recipe.items() if k in DEFAULTS})
        effective={}
        for t in data['titles']:
            validate(t.get('overrides',{}),patch=True,recipe=True);r=dict(recipe,**t.get('overrides',{}));validate({k:v for k,v in r.items() if k in DEFAULTS});effective[str(t['id'])]=r
            for key in ('audio_streams','subtitle_streams','forced_subtitle_streams'):
                if key in t and (not isinstance(t[key],list) or any(type(x)is not int or x<0 for x in t[key]) or len(t[key])!=len(set(t[key]))):raise ArchiveError(key+' must contain unique nonnegative source indices')
        return recipe,effective

    def _plan_fingerprint(self,settings,data,profile,preset):
        recipe,effective=self._effective(settings,data,profile,preset)
        source=str(Path(data.get('source_path','')).expanduser().resolve())
        source_hint=None
        try:
            stat=Path(source).stat();source_hint=dict(dev=stat.st_dev,ino=stat.st_ino,size=stat.st_size,mtime_ns=stat.st_mtime_ns)
        except OSError:pass
        payload=dict(source_identity_hint=source_hint,recipe=recipe,title_settings=effective,titles=data['titles'],collection=data['collection'],kind=data['kind'],source_path=source,disc_id=data.get('disc_id'),metadata=data.get('metadata',{}),settings_revision=settings['revision'],preset_revision=preset['revision'],profile_revision=(profile or{}).get('revision'))
        return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    @busy
    def create_job(self,data):
        data=deepcopy(data);self._validate_mapping(data)
        if data.get('kind')=='series'and 'expected_settings_revision'in data and any('season'not in t or'episode'not in t for t in data['titles']):raise ArchiveError('Series jobs require explicitly confirmed season and episode for every title')
        key=data.get('idempotency_key')
        if key is not None and (not isinstance(key,str) or not 1<=len(key)<=128):raise ArchiveError('idempotency_key must be 1..128 characters')
        fingerprint=hashlib.sha256(json.dumps({k:v for k,v in data.items() if k not in ('idempotency_key','expected_settings_revision','expected_plan_fingerprint')},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.mutex:
            if self.disconnect_fenced:raise ArchiveError('Disconnect fence active; resume archiving before creating jobs')
            previous=self._get('idempotency',key) if key else None
            if previous:
                if previous['fingerprint']!=fingerprint:raise ArchiveError('Idempotency key already used with a different request')
                return self.job(previous['job_id'])
            settings=self.settings();profile=self._get('profile',data.get('disc_id',''));preset_snapshot=deepcopy(self.preset(data.get('preset_id',settings['preset_id'])))
            initial_fingerprint=self._plan_fingerprint(settings,data,profile,preset_snapshot)
            if data.get('expected_plan_fingerprint')and data['expected_plan_fingerprint']!=initial_fingerprint:raise Conflict(settings['revision'])
            if data.get('expected_settings_revision',settings['revision'])!=settings['revision']:raise Conflict(settings['revision'])
        recipe,effective=self._effective(settings,data,profile,preset_snapshot)
        if recipe['encoder']=='hardware'and not self._tool_support()['hardware_encoders']:raise ArchiveError('This FFmpeg build has no VideoToolbox hardware encoder; choose software')
        if not recipe['output_root']:raise ArchiveError('Choose an existing output directory first')
        check_identity(recipe['_identity'])
        p=Path(data.get('source_path','')).expanduser().resolve(strict=True)
        source=identity(p,p.is_file()) # Heavy I/O intentionally outside control lock.
        preflight=self.preview_start(data)
        if not preflight['can_apply']:raise ArchiveError(preflight.get('reason')or'Job preflight failed')
        if preflight.get('requires_confirmation')and not data.get('confirm_transforms'):raise ArchiveError('Review and confirm the listed source transforms before creating this job')
        disc_id=None;drive=None;streams={};title_sizes={}
        if p.is_dir():
            disc_id,_=snapshot(p);matches=[d for d in self.discs if d['id']==disc_id]
            if data.get('disc_id')!=disc_id or len(matches)!=1 or matches[0]['source_path']!=str(p):raise ArchiveError('Scan and choose an exact unambiguous disc')
            if any(t['id'] not in {t['id'] for t in matches[0]['titles']} for t in data['titles']):raise ArchiveError('Selected title absent from scan')
            drive=matches[0]['drive_index'];streams=matches[0].get('stream_inventory',{});title_sizes={str(t['id']):t.get('bytes')for t in matches[0]['titles']}
        elif len(data['titles'])!=1 or data['titles'][0]['id']!=0:raise ArchiveError('Local files require one title ID 0')
        output=Path(recipe['output_root'])
        if recipe['folder_layout']=='organized':output/={'film':'Movies','series':'TV','extras':'Extras'}[data['kind']]
        output/=safe_name(data['collection'])
        jid=uuid.uuid4().hex
        job=dict(id=jid,collection=data['collection'],kind=data['kind'],state='queued',phase='scan',checkpoint='',stop_after=data.get('stop_after',recipe['default_checkpoint']),source_path=str(p),output_path=str(output),progress=0,message='Queued with explicit content mapping',safe_to_disconnect=False,titles=deepcopy(data['titles']),created_at=now(),updated_at=now(),disc_id=disc_id,drive_index=drive,source_identity=source,destination_identity=recipe['_identity'],settings=recipe,artifacts=[],reports=[],pause_requested=False,cancel_requested=False,disc_streams=streams,disc_title_sizes=title_sizes,phase_progress=None,current_title=None,processed_bytes=None,total_bytes=None,completed_items=0,total_items=len(data['titles']),elapsed_seconds=0,throughput_bps=None,eta_seconds=None,last_progress_at=None,heartbeat_at=now(),stall_reason=None,next_checkpoint='scan',progress_basis='completed title checkpoints',schema_version=2,revision=1,plan_revision=1,preset_id=recipe['preset_id'],effective_settings=effective,queue_order=len(self.jobs()),acceptance={'playback':'pending','perceptual':'pending'},checkpoint_detail={'phase':'','title_id':None},pending_changes=[],cleanup_status='keep',generation=1,title_checkpoints={},manual_pause=False,pause_cause=None,overrides=data.get('overrides',{}),metadata=data.get('metadata',{}),tool_paths=deepcopy(self.tools),ledger=[],confirm_transforms=bool(data.get('confirm_transforms',False)))
        if job['stop_after'] not in PHASES:raise ArchiveError('Invalid stop_after phase')
        self._safe_descendant(job,output)
        with self.mutex:
            if self.closed or self.disconnect_fenced:raise ArchiveError('Engine paused for disconnect')
            if self.settings()['revision']!=settings['revision']:raise Conflict(self.settings()['revision'])
            current_profile=self._get('profile',data.get('disc_id',''));current_preset=self.preset(data.get('preset_id',settings['preset_id']))
            if self._plan_fingerprint(self.settings(),data,current_profile,current_preset)!=initial_fingerprint:raise Conflict(self.settings()['revision'])
            previous=self._get('idempotency',key) if key else None
            if previous:
                if previous['fingerprint']!=fingerprint:raise ArchiveError('Conflicting idempotency request')
                return self.job(previous['job_id'])
            if any(j['source_path']==str(p) and j['state']in('running','queued') for j in self.jobs()):raise ArchiveError('This source already has an active job')
            self.db.execute('INSERT INTO records VALUES(?,?,?)',('job',jid,json.dumps(job)))
            if key:self.db.execute('INSERT INTO records VALUES(?,?,?)',('idempotency',key,json.dumps(dict(job_id=jid,fingerprint=fingerprint))))
            if data.get('remember_profile'):
                if not disc_id:self.db.rollback();raise ArchiveError('Only an exact scanned disc can be remembered')
                mapping={k:deepcopy(data[k]) for k in ('collection','kind','titles')};mapping.update(disc_id=disc_id,revision=(profile or {}).get('revision',0)+1,overrides=data.get('overrides',{}))
                self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)',('profile',disc_id,json.dumps(mapping)))
            self.db.commit()
        self._event('job.create',jid);self.wake.set();return job

    def start_scan(self):
        with self.mutex:
            if self.disconnect_fenced:raise ArchiveError('Scans fenced for disconnect')
            sid=uuid.uuid4().hex;record=dict(id=sid,state='queued',discs=[],message='Read-only scan queued');self._save('scan',sid,record)
        def task():
            record.update(state='running');self._save('scan',sid,record)
            try:record.update(discs=self.scan(auto_start=False),state='completed',message='Read-only scan complete')
            except Exception as e:record.update(state='failed',message=str(e))
            self._save('scan',sid,record)
        t=threading.Thread(target=task,daemon=True);self.runtime_threads.append(t);t.start();return dict(id=sid,state='queued')
    def scan_record(self,sid):
        r=self._get('scan',sid)
        if not r:raise ArchiveError('Scan not found')
        return r
    def scan(self,auto_start=False):
        if self.disconnect_fenced:raise Stopped('Scans fenced for disconnect')
        return super().scan(auto_start)

    def status(self):
        value=super().status();s=value['settings'];available=False;free=None
        try:available=bool(s['output_root']and Path(s['output_root']).is_dir());free=shutil.disk_usage(s['output_root']).free if available else None
        except OSError:pass
        with self.process_mutex:active=bool(self.processes)
        value.update(api_version=2,engine_version=ENGINE_VERSION,disconnect_fenced=self.disconnect_fenced,presets=self.presets(),storage=dict(free_bytes=free,reserve_bytes=s['reserve_bytes'],output_available=available),scans=self._all('scan'),safe_to_disconnect=value['safe_to_disconnect']and not any(s['state']in('running','queued')for s in self._all('scan'))and not active and not self.control_busy and not self.pipeline_lock.locked()and not any(e['state']in('running','queued') for e in self._all('export')),message='Technical verification and recorded manual acceptance are separate')
        return value

    def capabilities(self):
        tools={}
        for k,p in self.tools.items():
            version=None
            if p:
                try:
                    r=self._capture([p,'-version' if k!='makemkv' else '--version'],timeout=10,inspection=True);version=(r.stdout or r.stderr).splitlines()[0][:200] if(r.stdout or r.stderr)else None
                except (OSError,subprocess.TimeoutExpired):pass
            tools[k]=dict(path=p,available=bool(p),version=version)
        return dict(api_version=2,engine_version=ENGINE_VERSION,settings_schema=settings_schema(),tools=tools,encoders=[dict(id='software',video_codecs=['hevc','h264'],speeds=['ultrafast','superfast','veryfast','faster','fast','medium','slow','slower','veryslow']),dict(id='hardware',video_codecs=['hevc','h264'],speeds=['fast','medium','slow'],available=bool(self._tool_support()['hardware_encoders']),supported_codecs=self._tool_support()['hardware_encoders'],requires_bitrate=True,pilots=self._tool_support()['hardware_pilots'],validation='Synthetic SDR 8-bit pilot only; actual source-class encode still validated independently')],features=['presets','revision_conflicts','idempotency','async_scan','per_title_checkpoints','stop_now','disconnect_fence','exports','technical_cleanup','manual_stream_selection','sdr_transforms','acceptance','local_metadata']+(['text_subtitle_burn']if self._tool_support()['text_subtitle_burn']else[]),encoder_limits=dict(max_encoders=1,reason='Serial media pipeline; CPU thread count is configurable'),platform=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version()))

    def _safe_descendant(self,job,path):
        roots=[job['destination_identity']]+[v for k,v in job['settings'].items()if k in ('_work_root_identity','_original_root_identity')]
        target=Path(path)
        if any(p in ('.','..')for p in target.parts):raise ArchiveError('Unsafe path component')
        root=next((Path(r['path'])for r in roots if target.is_relative_to(Path(r['path']))),None)
        if root is None:raise ArchiveError('Path escaped the bound archive roots')
        cursor=root
        for part in target.relative_to(root).parts:
            cursor/=part
            if cursor.is_symlink():raise ArchiveError('Archive path contains a symlink')
        if not target.resolve().is_relative_to(root):raise ArchiveError('Archive path escaped its destination')

    def _sync_tree(self,job,path):
        roots=[Path(job['destination_identity']['path'])]+[Path(v['path'])for k,v in job['settings'].items()if k in ('_work_root_identity','_original_root_identity')]
        current=Path(path).parent;root=next((r for r in roots if current.is_relative_to(r)),None)
        if root is None:raise ArchiveError('Cannot sync an unbound archive path')
        while current.is_relative_to(root):
            fd=os.open(current,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
            if current==root:break
            current=current.parent

    def _attempt(self,job,phase):
        self._guards(job)
        root=Path(job['settings'].get('work_root')or job['output_path']);self._safe_descendant(job,root)
        root.mkdir(parents=True,exist_ok=True)
        attempt=root/'.work'/job['id']/('g'+str(job['generation']))/(phase+'-'+uuid.uuid4().hex)
        self._safe_descendant(job,attempt);attempt.mkdir(parents=True);return attempt

    def _guards(self,job,require_source=False):
        for binding in [job['destination_identity']]+[v for k,v in job['settings'].items()if k in ('_work_root_identity','_original_root_identity')]:
            try:check_identity(binding)
            except (ArchiveError,OSError)as e:raise Waiting('waiting_destination',str(e))
        if require_source:
            try:
                check_identity(job['source_identity'],bool(job['source_identity'].get('sha256')))
                if job['disc_id']and snapshot(job['source_path'])[0]!=job['disc_id']:raise ArchiveError('Inserted disc identity changed')
            except (ArchiveError,OSError)as e:raise Waiting('waiting_media',str(e))
        self._safe_descendant(job,job['output_path'])
        for a in job['artifacts']:
            for k in ('original','candidate','final','acquisition_candidate'):
                if a.get(k):self._safe_descendant(job,a[k])
            if a.get('original')and a.get('acquisition_committed',True)and a.get('original_status')!='deleted':
                if not Path(a['original']).is_file()or digest(a['original'])!=a['original_sha256']:raise Waiting('waiting_media','Retained original missing or changed')

    def _conditions(self,job,phase):
        self._guards(job,phase in ('scan','acquire'))
        if job['settings']['on_battery']=='pause'and self._on_battery():raise Waiting('waiting_power','Power source is battery; connect power or choose run on battery')
        settings=job['settings'];reserve=settings['reserve_bytes'];roots={settings['output_root'],settings.get('work_root')or settings['output_root'],settings.get('original_root')or settings['output_root']}
        acquisition_bytes=0
        if phase=='acquire':
            if Path(job['source_path']).is_file():acquisition_bytes=Path(job['source_path']).stat().st_size
            else:acquisition_bytes=sum(job.get('disc_title_sizes',{}).get(str(t['id']))or 0 for t in job['titles'])
        work=Path(settings.get('work_root')or settings['output_root']);original=Path(settings.get('original_root')or settings['output_root'])
        for value in roots:
            root=Path(value);needed=reserve
            if phase=='acquire'and(root==work or root==original):needed+=acquisition_bytes
            if shutil.disk_usage(root).free<needed:raise Waiting('waiting_space','Available space at a bound archive root is below reserved capacity and known acquisition bytes')

    def _on_battery(self):
        if sys.platform!='darwin':return False
        try:
            r=subprocess.run(['/usr/bin/pmset','-g','batt'],capture_output=True,text=True,timeout=5)
            return "'Battery Power'"in r.stdout
        except(OSError,subprocess.TimeoutExpired):return False

    def _worker(self):
        while not self.closed:
            if not self.disconnect_fenced:
                for j in self.jobs():
                    if j['state'].startswith('waiting_')and j['settings'].get('auto_resume')and not j.get('manual_pause'):
                        try:self._conditions(j,j['phase'])
                        except ArchiveError:continue
                        with self.mutex:
                            current=self.job(j['id'])
                            if current['state'].startswith('waiting_')and not current.get('manual_pause'):current.update(state='queued',safe_to_disconnect=False);self._job_save(current)
                jobs=sorted((j for j in self.jobs()if j['state']=='queued'),key=lambda j:j.get('queue_order',0))
                if jobs:self.run_job(jobs[0]['id']);continue
                try:
                    mounts=Path('/Volumes');signature=tuple(sorted((str(p),p.stat().st_dev,p.stat().st_ino)for p in mounts.iterdir()if p.is_dir()and((p/'BDMV').is_dir()or(p/'VIDEO_TS').is_dir())))if mounts.is_dir()else()
                    if signature!=self.poll_signature:
                        self.poll_signature=signature
                        if signature:self.scan(auto_start=True)
                        else:self.discs=[]
                except(OSError,ValueError,subprocess.TimeoutExpired):pass
            self.wake.wait(2);self.wake.clear()

    def _process_started(self,process,job=None):
        with self.process_mutex:self.processes[process.pid]=dict(process=process,job_id=job['id']if job else None)
        if (self.disconnect_fenced and not job)or(job and self.stop_events.get(job['id'],threading.Event()).is_set()):process.terminate()
    def _process_finished(self,process):
        with self.process_mutex:self.processes.pop(process.pid,None)
    def _capture(self,command,timeout=120,inspection=False):
        with self.process_mutex:
            job_id=getattr(self.thread_context,'job_id',None)
            if job_id and self.stop_events.get(job_id,threading.Event()).is_set():raise Stopped('Owned read stopped before launch')
            if self.disconnect_fenced and not job_id and not inspection:raise Stopped('Operation fenced for disconnect')
            command=list(command);tool_paths=getattr(self.thread_context,'tool_paths',{})or{}
            for key,current in self.tools.items():
                if current and command[0]==current and tool_paths.get(key):command[0]=tool_paths[key];break
            supervisor=[sys.executable,'supervise',str(os.getpid()),'--',*command]if getattr(sys,'frozen',False)else[sys.executable,str(Path(__file__).with_name('runner.py')),str(os.getpid()),*command]
            process=subprocess.Popen(supervisor,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,pass_fds=(self.lockfile.fileno(),))
            self.processes[process.pid]=dict(process=process,job_id=job_id)
        try:
            stdout,stderr=process.communicate(timeout=timeout)
            if job_id and self.stop_events.get(job_id,threading.Event()).is_set():raise Stopped('Owned read stopped before launch')
            if self.disconnect_fenced and not job_id and not inspection:raise Stopped('Scan stopped for disconnect')
            return subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
        except subprocess.TimeoutExpired:
            process.terminate();process.communicate();raise
        finally:self._process_finished(process)

    def _run(self,command,log,timeout=None,job=None,duration=None,total_bytes=None,title=None):
        if job and self.stop_events.setdefault(job['id'],threading.Event()).is_set():raise Stopped('Stopped; unfinished phase retained and will restart')
        command=list(command)
        if job:
            for key,current in self.tools.items():
                if current and command[0]==current and job.get('tool_paths',{}).get(key):command[0]=job['tool_paths'][key];break
        try:super()._run(command,log,timeout=timeout,job=job,duration=duration,title=title)
        except ArchiveError:
            if job and self.stop_events[job['id']].is_set():raise Stopped('Immediate stop completed; unfinished title will restart')
            raise
        if job and self.stop_events[job['id']].is_set():raise Stopped('Stopped; unfinished phase will restart into a new candidate')

    def _title_commit(self,job,phase,title_id):
        with self.mutex:
            current=self.job(job['id']);job.update(pause_requested=current.get('pause_requested',False),cancel_requested=current.get('cancel_requested',False),manual_pause=current.get('manual_pause',False),pause_cause=current.get('pause_cause'))
            job['title_checkpoints'][str(title_id)]=phase
            job['checkpoint_detail']=dict(phase=phase,title_id=title_id)
            job['last_progress_at']=now();job['completed_items']+=1
            aggregate=all(str(t['id'])in job['title_checkpoints']and PHASES.index(job['title_checkpoints'][str(t['id'])])>=PHASES.index(phase)for t in job['titles'])
            if aggregate:
                job['checkpoint']=phase;job['next_checkpoint']=PHASES[min(PHASES.index(phase)+1,4)]
            n=len(job['titles']);job['progress']=sum((PHASES.index(job['title_checkpoints'].get(str(t['id']),'scan'))+1)if str(t['id'])in job['title_checkpoints']else 0 for t in job['titles'])/(len(PHASES)*n)
            self._job_save(job)
            if (job.get('next_one')or job['pause_requested']or job['cancel_requested']or self.disconnect_fenced)and not(phase=='complete'and aggregate):
                job['next_one']=False;job.update(state='cancelled'if job['cancel_requested']else'paused',safe_to_disconnect=True,message='Stopped at durable title checkpoint');self._job_save(job)
                return False
            return True

    def run_job(self,jid):
        if not self.pipeline_lock.acquire(blocking=False):raise ArchiveError('Archive worker already active')
        try:
            job=self.job(jid)
            self.thread_context.job_id=jid;self.thread_context.tool_paths=job.get('tool_paths',self.tools)
            if job['state']!='queued'or self.disconnect_fenced:return
            if job.get('schema_version')!=2:
                # Upgrade execution bookkeeping without granting old originals cleanup eligibility.
                job.setdefault('effective_settings',{str(t['id']):job['settings']for t in job['titles']});job.setdefault('ledger',[])
            self.stop_events.setdefault(jid,threading.Event())
            if self.stop_events[jid].is_set()or self.job(jid).get('stop_requested'):raise Stopped('Immediate stop requested before phase start')
            while True:
                idx=PHASES.index(job['checkpoint'])+1 if job['checkpoint']else 0
                if idx>=len(PHASES):break
                phase=PHASES[idx];job.update(state='running',phase=phase,safe_to_disconnect=False,current_title=None,phase_progress=None,completed_items=0,total_items=len(job['titles']),next_checkpoint=phase,heartbeat_at=now(),message='Running '+phase)
                if phase=='encode'and all(job['effective_settings'][str(t['id'])]['mode']=='original'for t in job['titles']):job['message']='Original archive mode: preparing original promotion without lossy encoding'
                self._job_save(job);self._conditions(job,phase)
                if phase=='scan':
                    if Path(job['source_path']).is_file():job['source_probe']=self.probe(job['source_path'])
                    for t in job['titles']:
                        prior=job['title_checkpoints'].get(str(t['id']))
                        if prior and PHASES.index(prior)>=idx:job['completed_items']+=1;continue
                        if not self._title_commit(job,phase,t['id']):return
                else:
                    for t in job['titles']:
                        committed=job['title_checkpoints'].get(str(t['id']))
                        if committed and PHASES.index(committed)>=idx:job['completed_items']+=1;continue
                        if self.stop_events[jid].is_set():raise Stopped('Immediate stop; unfinished title restarts')
                        self._conditions(job,phase)
                        if self.disconnect_fenced:raise Stopped('Disconnect fence active at title boundary')
                        originals=job['titles'];job['_full_titles']=originals;job['titles']=[t]
                        try:
                            if phase=='acquire':self._acquire(job)
                            elif phase=='encode':self._encode_title(job,t)
                            elif phase=='verify':self._verify_title(job,t)
                            else:self._promote_title(job,t)
                        finally:job['titles']=originals;job.pop('_full_titles',None)
                        # Base title routines may persist subset while working; restore full plan before checkpoint.
                        if not self._title_commit(job,phase,t['id']):return
                with self.mutex:
                    latest=self.job(jid);job.update(pause_requested=latest.get('pause_requested',False),cancel_requested=latest.get('cancel_requested',False))
                    job.update(checkpoint=phase,phase_progress=1.,progress=(idx+1)/5,completed_items=len(job['titles']),heartbeat_at=now(),next_checkpoint=PHASES[min(idx+1,4)],message='Committed '+phase+' checkpoint')
                    if phase=='complete':job.update(state='completed',safe_to_disconnect=True,message='Technical archive complete; manual acceptance recorded separately')
                    elif job['stop_after']==phase or job['pause_requested']:job.update(state='paused',safe_to_disconnect=True,pause_cause=job.get('pause_cause')or'checkpoint')
                    self._job_save(job)
                if job['state']!='running':break
            if job['state']=='completed'and any(r.get('cleanup_policy')=='delete_verified'and r.get('mode')!='original'for r in job.get('effective_settings',{}).values()):
                try:self.cleanup(job['id'],{'expected_revision':job['revision']},automatic=True)
                except ArchiveError as e:
                    j=self.job(jid);j.update(state='completed',message='Technical archive complete; optional cleanup blocked: '+str(e));self._job_save(j)
        except ReviewRequired as e:
            j=self.job(jid);j.update(state='paused',safe_to_disconnect=True,message=str(e),manual_pause=True,pause_cause='transform_confirmation');self._job_save(j)
        except Waiting as e:
            j=self.job(jid);j.update(state=e.state,safe_to_disconnect=True,message=str(e),pause_cause='condition');self._job_save(j)
        except Stopped as e:
            j=self.job(jid);j.update(state='paused',safe_to_disconnect=True,message=str(e),manual_pause=True,pause_cause='stop_now');self._job_save(j)
        except Exception as e:
            j=self.job(jid);key=j['phase']+':'+str(j.get('checkpoint_detail',{}).get('title_id'))
            attempts=j.setdefault('retry_attempts',{});count=attempts.get(key,0)
            retryable=isinstance(e,ArchiveError)and(str(e).startswith('Processing failed')or'timed out'in str(e))
            if retryable and count<j['settings']['retry_count']and not j.get('manual_pause')and not self.disconnect_fenced:
                attempts[key]=count+1;j.update(state='queued',safe_to_disconnect=False,message='Processing failed; retained candidates; automatic retry '+str(count+1)+' of '+str(j['settings']['retry_count']))
            else:j.update(state='blocked'if isinstance(e,(ArchiveError,OSError))else'failed',safe_to_disconnect=True,message=str(e))
            self._job_save(j)
        finally:
            finished=self.job(jid)
            if finished['state']in('completed','blocked','failed'):
                self._event('job.'+finished['state'],jid,result=finished['message'],actor='local-engine')
            self.thread_context.job_id=None;self.thread_context.tool_paths=None;self.pipeline_lock.release()

    def action(self,jid,data):
        action=data.get('action')
        if action=='reprocess':return self.reprocess(jid,data)
        if action=='stop_now':
            with self.mutex:
                job=self.job(jid);self._revision(job,data,allow_legacy=False);job.update(manual_pause=True,stop_requested=True,pause_cause='stop_now',revision=job['revision']+1);self._job_save(job);self.stop_events.setdefault(jid,threading.Event()).set()
            with self.process_mutex:processes=[v['process']for v in self.processes.values()if v['job_id']==jid]
            for p in processes:
                if p.poll()is None:p.terminate()
            for p in processes:p.wait(timeout=15)
            drained=self.pipeline_lock.acquire(timeout=15)
            if drained:self.pipeline_lock.release()
            with self.mutex:
                job=self.job(jid)
                if job['state']not in('completed','cancelled')and drained:job.update(state='paused',safe_to_disconnect=True,message='Owned tools stopped; unfinished title will restart');self._job_save(job)
            self._event('job.stop_now',jid);return job
        with self.mutex:
            job=self.job(jid);self._revision(job,data,allow_legacy=action in('resume','pause_after_checkpoint','next_checkpoint','cancel'))
            if action in('resume','retry','next_checkpoint'):
                if job.get('pause_cause')=='transform_confirmation'and not job.get('confirm_transforms')and job.get('pending_changes'):raise ArchiveError('Confirm the listed transforms with PATCH plan confirm_transforms=true before resuming')
                if self.disconnect_fenced:raise ArchiveError('Resume archiving first; disconnect fence active')
                if job['state']=='running':raise ArchiveError('Pause before resuming or changing checkpoint')
                if job['state']in('completed','cancelled'):raise ArchiveError('Use reprocess to create a new job generation')
                stop=data.get('stop_after',job['stop_after'])
                if action=='next_checkpoint':job['next_one']=True;stop='complete'
                if stop not in PHASES:raise ArchiveError('Invalid stop_after')
                job.update(state='queued',safe_to_disconnect=False,pause_requested=False,cancel_requested=False,manual_pause=False,stop_requested=False,pause_cause=None,stop_after=stop,revision=job['revision']+1)
                self.stop_events.setdefault(jid,threading.Event()).clear();self._job_save(job,reset_requests=True)
            elif action=='pause_after_checkpoint':
                job.update(pause_requested=True,manual_pause=True,pause_cause='manual',revision=job['revision']+1)
                if job['state']=='queued':job.update(state='paused',safe_to_disconnect=True)
                self._job_save(job)
            elif action=='cancel':
                job.update(cancel_requested=True,manual_pause=True,revision=job['revision']+1)
                if job['state']!='running':job.update(state='cancelled',safe_to_disconnect=True)
                self._job_save(job)
            else:raise ArchiveError('Unknown action')
        self._event('job.'+action,jid);self.wake.set();return job

    def queue_action(self,data):
        action=data.get('action')
        with self.mutex:
            if action=='prepare_disconnect':
                self.disconnect_fenced=True;self._save('control','disconnect',True)
                for j in self.jobs():
                    if j['state']in('running','queued'):
                        j.update(pause_requested=True,pause_cause='disconnect',revision=j['revision']+1)
                        if j['state']=='queued':j.update(state='paused',safe_to_disconnect=True)
                        self._job_save(j)
            elif action=='resume_archiving':
                self.disconnect_fenced=False;self._save('control','disconnect',False);self.scan_cancel.clear()
                for j in self.jobs():
                    if j['state']=='paused'and j.get('pause_cause')=='disconnect'and not j.get('manual_pause'):j.update(state='queued',pause_requested=False,safe_to_disconnect=False,pause_cause=None,revision=j['revision']+1);self._job_save(j,reset_requests=True)
            elif action=='reorder':
                ids=data.get('job_ids',[])
                if len(set(ids))!=len(ids):raise ArchiveError('Duplicate queue IDs')
                jobs=[self.job(j)for j in ids]
                if any(j['state']!='queued'for j in jobs):raise ArchiveError('Only queued jobs can be reordered')
                for i,j in enumerate(jobs):j.update(queue_order=i,revision=j['revision']+1);self._job_save(j)
            else:raise ArchiveError('Unknown queue action')
        if action=='prepare_disconnect':
            for e in self._all('export'):
                if e['state']in('running','queued'):self.export_action(e['id'],dict(action='pause',pause_cause='disconnect'))
            # Scanners stop immediately; media workers honor next durable title checkpoint.
            with self.process_mutex:scanners=[v['process']for v in self.processes.values()if v['job_id']is None]
            for p in scanners:
                if p.poll()is None:p.terminate()
            for p in scanners:p.wait(timeout=15)
        if action=='resume_archiving':
            for e in self._all('export'):
                if e['state']=='paused'and e.get('pause_cause')=='disconnect'and not e.get('manual_pause'):
                    try:self.export_action(e['id'],dict(action='resume'))
                    except ArchiveError:pass
        self._event('queue.'+action,'queue');self.wake.set();return self.status()

    def _job_save(self,job,reset_requests=False):
        # A single-title phase view never replaces the durable whole-disc plan.
        view=job
        if job.get('_full_titles'):
            view=deepcopy(job);view['titles']=deepcopy(job['_full_titles']);view.pop('_full_titles',None)
        with self.mutex:
            current=self._get('job',job['id'])
            if current:
                stale=current.get('revision',1)>view.get('revision',1)
                if stale:
                    for key in('acceptance','queue_order','confirm_transforms'):
                        if key in current:view[key]=deepcopy(current[key])
                view['revision']=max(view.get('revision',1),current.get('revision',1))
                if not reset_requests and current.get('manual_pause')and view.get('state')=='running':
                    view['manual_pause']=True;view['pause_cause']=current.get('pause_cause')
                if not reset_requests and current.get('stop_requested'):view['stop_requested']=True
            super()._job_save(view,reset_requests=reset_requests)
        job['updated_at']=view['updated_at'];job['revision']=view.get('revision',1)
        if 'acceptance'in view:job['acceptance']=deepcopy(view['acceptance'])

    def _filename(self,job,title,extension):
        r=job.get('effective_settings',{}).get(str(title['id']),job['settings'])
        for key in('season','episode','year'):
            if ('{'+key)in r['file_template']and key not in title and key not in job.get('metadata',{}):raise ArchiveError('File template requires explicitly supplied '+key)
        values=dict(title=title['name'],collection=job['collection'],season=title.get('season',0),episode=title.get('episode',0),year=title.get('year',job.get('metadata',{}).get('year',0)))
        stem=safe_name(r['file_template'].format(**values))
        if job.get('generation',1)>1:stem+='_g'+str(job['generation'])
        return stem+'.'+extension

    def _acquire(self,job):
        r=job['settings'];base=Path(r.get('original_root')or job['output_path'])
        if r.get('original_root'):
            if r['folder_layout']=='organized':base/={'film':'Movies','series':'TV','extras':'Extras'}[job['kind']]
            base/=safe_name(job['collection'])
        job['_original_dir']=str(base/'Original_MKV')
        super()._acquire(job)
        for a in job['artifacts']:
            if not a.get('ownership_recorded')and a.get('acquisition_committed'):
                candidate=Path(a['acquisition_candidate']);paths=[str(candidate),a['original']]
                for p in candidate.parent.rglob('*.mkv'):
                    if p.is_file()and os.path.samefile(candidate,p):paths.append(str(p))
                for intent in job.get('publications',[]):
                    if intent.get('destination')==a['original']and intent.get('copy_candidate'):paths.append(intent['copy_candidate'])
                groups={}
                for p in sorted(set(paths)):
                    st=Path(p).stat();groups.setdefault((st.st_dev,st.st_ino),[]).append(p)
                for(dev,ino),aliases in groups.items():
                    entry=dict(id=uuid.uuid4().hex,title_id=a['title_id'],role='temporary_original',generation=job['generation'],aliases=aliases,sha256=a['original_sha256'],bytes=Path(aliases[0]).stat().st_size,dev=dev,ino=ino,lifecycle='retained',app_created=True,cleanup_eligible=job.get('schema_version')==2,source_imported=not bool(job['disc_id']))
                    job['ledger'].append(entry)
                a.update(ownership_recorded=True,original_status='retained',cleanup_eligible=job.get('schema_version')==2);self._job_save(job)

    def _commit_original(self,job,artifact):
        self._guards(job)
        self._publish(job,artifact['acquisition_candidate'],artifact['original'],artifact['original_sha256'])
        artifact['acquisition_committed']=True;self._job_save(job)

    def _probe_any(self,path):
        r=self._capture([self.tools['ffprobe'],'-v','error','-show_streams','-show_format','-of','json',str(path)],timeout=120)
        if r.returncode:raise ArchiveError('Probe failed: '+r.stderr[-400:])
        return json.loads(r.stdout)

    def _stream_hash(self,path,index):
        r=self._capture([self.tools['ffmpeg'],'-nostdin','-v','error','-i',str(path),'-map','0:'+str(index),'-c','copy','-f','streamhash','-hash','sha256','-'],timeout=None)
        if r.returncode:raise ArchiveError('Cannot verify original stream payload: '+r.stderr[-400:])
        match=__import__('re').search(r'SHA256=([a-f0-9]{64})',r.stdout)
        if not match:raise ArchiveError('Stream payload hash is absent')
        return match.group(1)

    def _sidecars(self,job,a,recipe,attempt):
        src=a['source_probe'];sidecars=[]
        for s in src['streams']:
            typ=s['codec_type']
            if typ=='audio'and recipe['preserve_original_audio']:ext='mka'
            elif typ=='subtitle'and(recipe['preserve_bitmap_subtitles']or s.get('codec_name')in __import__('engine.media',fromlist=['TEXT']).TEXT):ext='mks'
            else:continue
            candidate=attempt/('Source_'+str(s['index'])+'.'+ext)
            self._run([self.tools['ffmpeg'],'-nostdin','-v','error','-n','-i',a['original'],'-map','0:'+str(s['index']),'-c','copy','-f','matroska',str(candidate)],attempt/('sidecar-'+str(s['index'])+'.log'),job=job,title=a['name'])
            copied=self._probe_any(candidate)['streams']
            if len(copied)!=1 or copied[0]['codec_type']!=typ or copied[0]['codec_name']!=s['codec_name']or(typ=='audio'and copied[0].get('channels')!=s.get('channels'))or(language(copied[0])or'und')!=(language(s)or'und'):raise ArchiveError('Sidecar stream inventory mismatch')
            source_hash=self._stream_hash(a['original'],s['index']);copy_hash=self._stream_hash(candidate,copied[0]['index'])
            if source_hash!=copy_hash:raise ArchiveError('Sidecar original-stream payload mismatch')
            self._fsync(candidate);self._sync_tree(job,candidate)
            sidecars.append(dict(source_index=s['index'],type=typ,codec=s['codec_name'],language=language(s)or'und',channels=s.get('channels'),candidate=str(candidate),sha256=digest(candidate),payload_sha256=copy_hash,verification='passed',extension=ext))
        a['sidecars']=sidecars;self._job_save(job)

    def _encode_title(self,job,title):
        a=next(a for a in job['artifacts']if a['title_id']==title['id']);recipe=job['effective_settings'][str(title['id'])]
        if recipe['mode']=='original':a.update(candidate=a['original'],candidate_sha256=a['original_sha256'],transforms=[],audio_map=[],subtitle_map=[],expected_video=None,original_deliverable=True);return
        from engine.media import build
        attempt=self._attempt(job,'encode');source=self.probe(a['original']);a['source_probe']=source
        self._check_render_support(source,recipe,title)
        candidate=attempt/self._filename(job,title,recipe['output_container'])
        command,plan=build(source,recipe,title,a['original'],str(candidate),self.tools['ffmpeg'])
        if any(x.get('kind')=='bit_depth'and x.get('source')=='yuv420p10le'and x.get('target')=='yuv420p'for x in plan['transforms'])and not (job.get('confirm_transforms')or job.get('overrides',{}).get('bit_depth')=='8'or title.get('overrides',{}).get('bit_depth')=='8'):
            job['pending_changes']=plan['transforms'];self._job_save(job);raise ReviewRequired('10-bit to 8-bit conversion requires explicit transform confirmation; original acquired and retained')
        self._run(command,attempt/'encode.log',job=job,duration=float(source['format'].get('duration',0)),title=title['name'])
        if recipe['output_container']=='mp4'and plan['subtitle_map']:
            from engine.mp4 import set_subtitle_defaults
            set_subtitle_defaults(candidate,[s['default']for s in plan['subtitle_map']])
        self._fsync(candidate);self._sync_tree(job,candidate);a.update(plan,candidate=str(candidate),effective_recipe=recipe)
        self._sidecars(job,a,recipe,attempt);self._job_save(job)

    def _verify_title(self,job,title):
        from engine.media import number
        a=next(a for a in job['artifacts']if a['title_id']==title['id']);recipe=job['effective_settings'][str(title['id'])]
        attempt=self._attempt(job,'verify');source=self.probe(a['original']);output=self.probe(a['candidate'])
        sv=next(s for s in source['streams']if s['codec_type']=='video');ov=next(s for s in output['streams']if s['codec_type']=='video')
        if recipe['mode']=='original':
            if digest(a['candidate'])!=a['original_sha256']:raise ArchiveError('Original archive byte identity changed')
        else:
            expected=a['expected_video']
            for k in('width','height','pix_fmt','codec_name'):
                if ov.get(k)!=expected[k]:raise ArchiveError('Export does not match planned '+k)
            if abs(number(ov.get('sample_aspect_ratio'))-expected['sample_aspect_ratio'])>.001:raise ArchiveError('Export display aspect does not match planned transform')
            if expected['frame_rate']and abs(number(ov.get('r_frame_rate'),0)-expected['frame_rate'])>.02:raise ArchiveError('Export frame rate differs from plan')
            if expected['progressive']and ov.get('field_order')not in(None,'unknown','progressive'):raise ArchiveError('Deinterlaced output still signals interlace')
            for k in('color_range','color_space','color_transfer','color_primaries'):
                if sv.get(k)not in(None,'unknown','N/A')and ov.get(k)!=sv.get(k):raise ArchiveError('Signalled '+k+' changed unexpectedly')
            subtitle_evidence=[]
            audio=[s for s in output['streams']if s['codec_type']=='audio'];subs=[s for s in output['streams']if s['codec_type']=='subtitle']
            if len(audio)!=len(a['audio_map'])or len(subs)!=len(a['subtitle_map']):raise ArchiveError('Export stream counts differ from selected mappings')
            for actual,expected in zip(audio,a['audio_map']):
                if actual.get('codec_name')!=expected['codec']or actual.get('channels')!=expected['channels']or(language(actual)or'und')!=expected['language']or bool(actual.get('disposition',{}).get('default'))!=expected['default']:raise ArchiveError('Audio codec/channel/language/default mapping mismatch')
                if recipe['audio_codec']=='copy'and self._stream_hash(a['original'],expected['source_index'])!=self._stream_hash(a['candidate'],actual['index']):raise ArchiveError('Copied audio payload mismatch')
            for actual,expected in zip(subs,a['subtitle_map']):
                if actual.get('codec_name')!=expected['codec']or(language(actual)or'und')!=expected['language']or bool(actual.get('disposition',{}).get('forced'))!=expected['forced']or bool(actual.get('disposition',{}).get('default'))!=expected['default']:raise ArchiveError('Subtitle codec/language/forced/default mapping mismatch')
                if recipe['subtitle_policy']=='text':subtitle_evidence.append(self._verify_text_cues(a['original'],expected['source_index'],a['candidate'],actual['index']))
                elif self._stream_hash(a['original'],expected['source_index'])!=self._stream_hash(a['candidate'],actual['index']):raise ArchiveError('Copied subtitle packet payload mismatch')
        sd=float(source['format'].get('duration',0));od=float(output['format'].get('duration',0))
        if sd<=0 or abs(sd-od)>max(.5,sd*.001):raise ArchiveError('Source/export duration mismatch')
        warnings=self._decode(a['candidate'],attempt/'decode.log',job=job,title=title['name'])
        # PCM without an explicit layout can be valid; recorded guessed layout is not decode corruption.
        hard=[w for w in warnings if'Guessed Channel Layout:'not in w]
        if hard:raise ArchiveError('Full decode reported warnings; inspect '+str(attempt))
        a['candidate_sha256']=digest(a['candidate']);a['technical_verified']=True
        report=dict(subtitle_evidence=subtitle_evidence if recipe['mode']!='original'else[],title_id=title['id'],title=title['name'],technical_validation='passed',full_decode='passed',source_duration=sd,output_duration=od,audio_map=a.get('audio_map',[]),subtitle_map=a.get('subtitle_map',[]),transforms=a.get('transforms',[]),original_sha256=a['original_sha256'],output_sha256=a['candidate_sha256'],sidecars=a.get('sidecars',[]),warnings=warnings,playback_acceptance=job['acceptance']['playback'],perceptual_acceptance=job['acceptance']['perceptual'],original_status=a.get('original_status','retained'),effective_recipe=recipe,source_video={k:sv.get(k)for k in('codec_name','width','height','r_frame_rate','sample_aspect_ratio','field_order','pix_fmt','color_range','color_space','color_primaries','color_transfer')},output_video={k:ov.get(k)for k in('codec_name','width','height','r_frame_rate','sample_aspect_ratio','field_order','pix_fmt','color_range','color_space','color_primaries','color_transfer')},actual_audio=[dict(codec=s.get('codec_name'),channels=s.get('channels'),language=language(s)or'und',bit_rate=s.get('bit_rate'))for s in output['streams']if s['codec_type']=='audio'])
        job['reports']=[r for r in job['reports']if r.get('title_id')!=title['id']]+[report]
        (attempt/'report.json').write_text(json.dumps(report,indent=2));self._fsync(attempt/'report.json');self._sync_tree(job,attempt/'report.json');self._job_save(job)

    def _publish(self,job,source,final,sha256):
        source=Path(source);final=Path(final);self._safe_descendant(job,source);self._safe_descendant(job,final)
        if digest(source)!=sha256:raise ArchiveError('Verified publication candidate changed')
        final.parent.mkdir(parents=True,exist_ok=True)
        intents=job.setdefault('publications',[])
        prior=next((e for e in reversed(intents)if e.get('destination')==str(final)and e.get('sha256')==sha256),None)
        if final.exists():
            origin=Path(prior.get('created_from',source))if prior else source
            if not prior or not origin.exists()or not os.path.samefile(final,origin)or digest(final)!=sha256:raise ArchiveError('Output collision; no overwrite: '+str(final))
            self._fsync(final);self._sync_tree(job,final);prior['state']='committed';self._job_save(job);return
        intent=dict(source=str(source),destination=str(final),sha256=sha256,state='prepared',created_from=str(source));intents.append(intent);self._job_save(job)
        try:os.link(source,final)
        except OSError as e:
            import errno
            if e.errno not in(errno.EXDEV,errno.EPERM,errno.ENOTSUP,errno.EOPNOTSUPP):raise
            candidate=final.with_name('.'+final.name+'.copy-'+uuid.uuid4().hex)
            with source.open('rb')as src,candidate.open('xb')as dst:
                shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
            if digest(candidate)!=sha256:raise ArchiveError('Publication copy verification failed')
            self._fsync(candidate);self._sync_tree(job,candidate)
            intent.update(copy_candidate=str(candidate),created_from=str(candidate));self._job_save(job)
            os.link(candidate,final)
        self._fsync(final);self._sync_tree(job,final);intent['state']='committed';self._job_save(job)

    def _promote_title(self,job,title):
        a=next(a for a in job['artifacts']if a['title_id']==title['id']);recipe=job['effective_settings'][str(title['id'])]
        extension='mkv'if recipe['mode']=='original'else recipe['output_container'];final=self._destination(job,title)
        self._publish(job,a['candidate'],final,a['candidate_sha256']);a['final']=str(final)
        stat=final.stat();a['final_stat']=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns,ino=stat.st_ino)
        for side in a.get('sidecars',[]):
            finalside=Path(job['output_path'])/(final.stem+'_Source_'+str(side['source_index'])+'.'+side['extension'])
            self._publish(job,side['candidate'],finalside,side['sha256']);side['path']=str(finalside)
        if recipe['mode']=='original':
            a['original_deliverable']=True
            for e in job['ledger']:
                if e['title_id']==title['id']:e['cleanup_eligible']=False;e['role']='original_archive_deliverable'
        self._job_save(job)

    def acceptance(self,jid,data):
        with self.mutex:
            j=self.job(jid);self._revision(j,data)
            for key in('playback','perceptual'):
                if key in data:
                    if data[key]not in('accepted','pending','rejected'):raise ArchiveError('Invalid acceptance value')
                    j['acceptance'][key]=data[key]
            for r in j['reports']:r['playback_acceptance']=j['acceptance']['playback'];r['perceptual_acceptance']=j['acceptance']['perceptual']
            j['revision']+=1;self._job_save(j);self._event('job.acceptance',jid);return j

    def report(self,jid):
        j=self.job(jid);artifacts=deepcopy(j['artifacts'])
        references=self._original_references(j)
        retained=any(a.get('original_status')!='deleted'and Path(a.get('original','')).is_file()for a in references)or any(e.get('lifecycle')!='deleted'and any(Path(p).is_file()for p in e['aliases'])for e in j.get('ledger',[]))
        return dict(job_id=jid,state=j['state'],checkpoint=j['checkpoint'],checkpoint_detail=j.get('checkpoint_detail'),reports=[dict(r,playback_acceptance=j.get('acceptance',{}).get('playback','pending'),perceptual_acceptance=j.get('acceptance',{}).get('perceptual','pending'))for r in j['reports']],artifacts=artifacts,originals_retained=retained,cleanup_status=j.get('cleanup_status'),ownership_ledger=j.get('ledger',[]),acceptance=j.get('acceptance',{'playback':'pending','perceptual':'pending'}),perceptual_acceptance=j.get('acceptance',{}).get('perceptual','pending'),tv_acceptance=j.get('acceptance',{}).get('playback','pending'),content_identity='Explicit user-supplied mapping; no title/episode inferred from duration',subtitles='See mapped export tracks and verified original subtitle sidecars')

    def library(self):
        items=[]
        for j in self.jobs():
            for a in j['artifacts']:
                if not a.get('final')or not a.get('technical_verified'):continue
                path=Path(a['final']);verification='missing'
                if path.is_file():
                    st=path.stat();expected=a.get('final_stat');verification='changed'if expected and any(expected[k]!=getattr(st,{'size':'st_size','mtime_ns':'st_mtime_ns','ino':'st_ino'}[k])for k in expected)else'passed'
                items.append(dict(id=j['id']+':'+str(a['title_id']),job_id=j['id'],title=a['name'],path=str(path),kind=j['kind'],bytes=path.stat().st_size if path.is_file()else 0,original_status=a.get('original_status','retained'),verification=verification,acceptance=j.get('acceptance',{})))
        return dict(items=items,total=len(items))

    def _validate_mapping(self,data):
        super()._validate_mapping(data)
        for t in data['titles']:
            for key in('default_audio_stream','default_subtitle_stream'):
                if key in t and(type(t[key])is not int or t[key]<0):raise ArchiveError(key+' must be a source stream index')
            for key in('season','episode','year'):
                if key in t and(type(t[key])is not int or t[key]<0 or(key=='episode'and t[key]<1)):raise ArchiveError(key+' must be a valid nonnegative integer (episode starts at 1)')

    def _destination(self,job,title):
        r=job.get('effective_settings',{}).get(str(title['id']),job['settings']);folder=Path(job['output_path'])
        if job['kind']=='series'and r['folder_layout']=='organized'and'season'in title:folder/=('Season_'+str(title['season']).zfill(2))
        ext='mkv'if r['mode']=='original'else r['output_container'];return folder/self._filename(job,title,ext)

    @busy
    def preview_start(self,data):
        self._validate_mapping(data)
        if data.get('kind')=='series'and any('season'not in t or'episode'not in t for t in data['titles']):raise ArchiveError('Series preview requires confirmed season and episode for every title')
        with self.mutex:
            settings=self.settings();profile=self._get('profile',data.get('disc_id',''));preset_snapshot=deepcopy(self.preset(data.get('preset_id',settings['preset_id'])))
            plan_fingerprint=self._plan_fingerprint(settings,data,profile,preset_snapshot)
        if data.get('expected_settings_revision',settings['revision'])!=settings['revision']:raise Conflict(settings['revision'])
        recipe,effective=self._effective(settings,data,profile,preset_snapshot)
        root=Path(recipe['output_root'])
        if recipe['folder_layout']=='organized':root/={'film':'Movies','series':'TV','extras':'Extras'}[data['kind']]
        root/=safe_name(data['collection'])
        pseudo=dict(settings=recipe,effective_settings=effective,output_path=str(root),collection=data['collection'],kind=data['kind'],metadata=data.get('metadata',{}),generation=1)
        destinations=[];reason=None
        if not recipe['output_root']:reason='Choose an existing output destination'
        elif not Path(recipe['output_root']).is_dir():reason='Output destination is unavailable'
        if self.disconnect_fenced:reason='Disconnect fence active; resume archiving first'
        for title in data['titles']:
            dest=self._destination(pseudo,title);destinations.append(dict(title_id=title['id'],path=str(dest),collision=dest.exists()))
        if any(d['collision']for d in destinations):reason='Output collision; choose a different explicit name or destination'
        transforms=[];requires_confirmation=False
        source_path=Path(data.get('source_path',''))
        if source_path.is_file():
            from engine.media import build
            try:
                probe=self.probe(source_path)
                for t,d in zip(data['titles'],destinations):
                    r=effective[str(t['id'])]
                    if r['mode']=='original':continue
                    self._check_render_support(probe,r,t)
                    _,plan=build(probe,r,t,str(source_path),d['path'],self.tools['ffmpeg']);transforms+=plan['transforms']
                    if any(x.get('kind')=='bit_depth'and x.get('source')=='yuv420p10le'and x.get('target')=='yuv420p'for x in plan['transforms'])and not(data.get('confirm_transforms')or data.get('overrides',{}).get('bit_depth')=='8'or t.get('overrides',{}).get('bit_depth')=='8'):requires_confirmation=True
            except ArchiveError as e:reason=str(e)
        return dict(effective_settings=recipe,title_settings=effective,destinations=destinations,collisions=[d for d in destinations if d['collision']],can_apply=reason is None,reason=reason,settings_revision=settings['revision'],requires_confirmation=requires_confirmation,transforms=transforms,plan_fingerprint=plan_fingerprint)

    @busy
    def plan_preview(self,jid,data):
        job=self.job(jid);self._revision(job,data)
        titles=deepcopy(data.get('titles',job['titles']));self._validate_mapping(dict(job,titles=titles))
        overrides=dict(job.get('overrides',{}),**data.get('overrides',{}))
        pinned=dict(id=job['preset_id'],settings={k:deepcopy(v)for k,v in job['settings'].items()if k in RECIPE})
        recipe,effective=self._effective(job['settings'],dict(titles=titles,overrides=overrides,preset_id=job['preset_id']),None,pinned)
        changes=[dict(field=k,before=job['settings'].get(k),after=v)for k,v in recipe.items()if k in RECIPE and job['settings'].get(k)!=v]
        if titles!=job['titles']:changes.append(dict(field='titles',before=job['titles'],after=titles))
        current={t['id']for t in job['titles']};added=any(t['id']not in current for t in titles)
        render_changes=[c for c in changes if c['field']not in('cleanup_policy','reserve_bytes')]
        restart='acquire'if added else'encode'if render_changes else None
        pseudo=dict(job,settings=recipe,effective_settings=effective,titles=titles,generation=job['generation']+1 if restart else job['generation'])
        destinations=[dict(title_id=t['id'],path=str(self._destination(pseudo,t)),collision=self._destination(pseudo,t).exists())for t in titles]
        reason='Pause the running job before editing'if job['state']in('running','queued')else'Output collision'if any(d['collision']for d in destinations)else None
        return dict(changes=changes,restart_from=restart,effective_settings=recipe,title_settings=effective,destinations=destinations,can_apply=reason is None,reason=reason)

    def edit_plan(self,jid,data):
        preview=self.plan_preview(jid,data)
        if not preview['can_apply']:raise ArchiveError(preview['reason'])
        with self.mutex:
            job=self.job(jid);self._revision(job,data)
            if job['state']in('running','queued'):raise ArchiveError('Pause job before changing plan')
            if not preview['changes']:
                if data.get('confirm_transforms'):job.update(confirm_transforms=True,pending_changes=[],revision=job['revision']+1,plan_revision=job['plan_revision']+1);self._job_save(job)
                return job
            if preview['restart_from']is None:
                job.update(settings=preview['effective_settings'],effective_settings=preview['title_settings'],revision=job['revision']+1,plan_revision=job['plan_revision']+1,overrides=dict(job.get('overrides',{}),**data.get('overrides',{})))
                self._job_save(job);return job
            job.setdefault('generations',[]).append(dict(generation=job['generation'],plan_revision=job['plan_revision'],settings=deepcopy(job['settings']),titles=deepcopy(job['titles']),artifacts=deepcopy(job['artifacts']),reports=deepcopy(job['reports'])))
            job.update(confirm_transforms=bool(data.get('confirm_transforms',job.get('confirm_transforms',False))),titles=deepcopy(data.get('titles',job['titles'])),settings=preview['effective_settings'],effective_settings=preview['title_settings'],generation=job['generation']+1,plan_revision=job['plan_revision']+1,revision=job['revision']+1,pending_changes=[],reports=[],state='paused',manual_pause=True,pause_cause='plan_edit',overrides=dict(job.get('overrides',{}),**data.get('overrides',{})))
            # Preserve acquired source paths; invalidate derived outputs without deleting older generations.
            artifacts=[]
            for title in job['titles']:
                old=next((a for a in job['artifacts']if a['title_id']==title['id']),None)
                if old:
                    keep={k:deepcopy(v)for k,v in old.items()if k in('title_id','original','original_sha256','source_probe','acquisition_candidate','acquisition_committed','ownership_recorded','original_status','cleanup_eligible')};keep['name']=title['name'];artifacts.append(keep)
            job['artifacts']=artifacts
            restart=preview['restart_from'];job['checkpoint']='scan'if restart=='acquire'else'acquire'if len(artifacts)==len(job['titles'])else'scan'
            job['title_checkpoints']={str(a['title_id']):'acquire'for a in artifacts};job['checkpoint_detail']=dict(phase=job['checkpoint'],title_id=None);job['progress']=PHASES.index(job['checkpoint'])/5
            self._job_save(job);self._event('job.plan.update',jid);return job

    @busy
    def reprocess(self,jid,data):
        old=self.job(jid);self._revision(old,data,allow_legacy=False)
        if old.get('cleanup_status')in('deleting','deleted'):return dict(reacquisition_needed=True,reason='Original cleanup is active or complete; reacquire the exact source')
        available=[a for a in old['artifacts']if a.get('original_status')!='deleted'and Path(a.get('original','')).is_file()]
        if len(available)!=len(old['titles']):return dict(reacquisition_needed=True,reason='A retained original is unavailable; reinsert exact disc or restore imported source')
        # Multi-title reprocessing reuses verified originals without re-acquiring the drive.
        new=deepcopy(old);newid=uuid.uuid4().hex
        new.update(id=newid,state='paused',checkpoint='acquire',phase='encode',generation=old.get('generation',1)+1,revision=1,plan_revision=1,created_at=now(),updated_at=now(),reports=[],publications=[],cleanup_status='keep',pause_requested=False,cancel_requested=False,manual_pause=False,pause_cause=None,parent_job_id=jid,tool_paths=deepcopy(self.tools),title_checkpoints={str(t['id']):'acquire'for t in old['titles']})
        new['artifacts']=[{k:deepcopy(v)for k,v in a.items()if k in('title_id','name','original','original_sha256','source_probe','acquisition_candidate','acquisition_committed','original_status','cleanup_eligible','ownership_recorded')}for a in available]
        # Shared originals remain owned by the original job; derived generation cannot delete them independently.
        new['ledger']=[]
        for a in new['artifacts']:a['cleanup_eligible']=False
        with self.mutex:
            current=self.job(jid)
            if current.get('cleanup_status')in('deleting','deleted'):raise ArchiveError('Original cleanup has claimed these paths; reacquisition required')
            self._save('job',newid,new)
        self._event('job.reprocess',newid);return new

    def _original_references(self,job):
        refs=list(job.get('artifacts',[]))
        for generation in job.get('generations',[]):refs.extend(generation.get('artifacts',[]))
        return refs

    @busy
    def cleanup_preview(self,jid):
        job=self.job(jid);reasons=[];paths=[]
        requested={int(k)for k,r in job.get('effective_settings',{}).items()if r.get('cleanup_policy')=='delete_verified'and r.get('mode')!='original'}
        if not requested:reasons.append('Original retention policy is Keep or original archive mode')
        if job.get('schema_version')!=2:reasons.append('Legacy originals are ineligible')
        if job['state']!='completed':reasons.append('Technical archive is not complete')
        
        for artifact in job['artifacts']:
            if artifact['title_id']not in requested or artifact.get('original_status')=='deleted':continue
            if not artifact.get('technical_verified')or not artifact.get('final')or not Path(artifact['final']).is_file():reasons.append('Verified final deliverable unavailable');continue
            if digest(artifact['final'])!=artifact.get('candidate_sha256'):reasons.append('Final deliverable changed since verification')
            source=artifact['source_probe']['streams'];preserved={s['source_index']for s in artifact.get('sidecars',[])if s.get('verification')=='passed'and s.get('path')and Path(s['path']).is_file()and digest(s['path'])==s['sha256']}
            required={s['index']for s in source if s['codec_type']in('audio','subtitle')}
            if not required<=preserved:reasons.append('All source audio/subtitle streams must have verified retained sidecars')
            entries=[e for e in job.get('ledger',[])if e['title_id']==artifact['title_id']and e['role']=='temporary_original'and e.get('cleanup_eligible')]
            if not entries:reasons.append('No eligible ownership ledger for this original');continue
            for entry in entries:
                if entry.get('lifecycle')=='deleted':continue
                aliases=set(entry['aliases'])
                for other in self.jobs():
                    if other['id']==jid:continue
                    if any(a.get('original')in aliases and a.get('original_status')!='deleted'for a in self._original_references(other)):
                        reasons.append('Original is referenced by another job or generation; retain it')
                present=[]
                for p in entry['aliases']:
                    path=Path(p)
                    try:
                        self._safe_descendant(job,path)
                        if not path.is_file()or path.is_symlink()or digest(path)!=entry['sha256']:raise ArchiveError('Original ownership alias missing or changed')
                        stat=path.stat()
                        if(stat.st_dev,stat.st_ino)!=(entry['dev'],entry['ino']):raise ArchiveError('Original alias identity changed')
                        present.append(path)
                    except(OSError,ArchiveError)as e:reasons.append(str(e))
                if present and present[0].stat().st_nlink!=len(present):reasons.append('Untracked original hardlinks exist; refuse cleanup')
                for p in present:paths.append(dict(path=str(p),bytes=p.stat().st_size,ledger_id=entry['id']))
        return dict(eligible=not reasons,blocking_reasons=sorted(set(reasons)),artifacts=paths,logical_bytes=sum(e['bytes']for e in job.get('ledger',[])if e['id']in{p['ledger_id']for p in paths}),policy=job['settings']['cleanup_policy'])

    def cleanup(self,jid,data,automatic=False):
        with self.mutex:self.control_busy+=1
        try:return self._cleanup_impl(jid,data,automatic)
        finally:
            with self.mutex:self.control_busy-=1

    def _cleanup_impl(self,jid,data,automatic=False):
        job=self.job(jid);self._revision(job,data,allow_legacy=automatic)
        preview=self.cleanup_preview(jid)
        # Already completed cleanup is idempotent, and reports are accurate after recovery.
        if job.get('cleanup_status')=='deleted':return self.report(jid)
        if not preview['eligible']:job['cleanup_status']='blocked';self._job_save(job);raise ArchiveError('; '.join(preview['blocking_reasons']))
        with self.mutex:
            current=self.job(jid)
            if current['revision']!=job['revision']:raise Conflict(current['revision'])
            aliases={p['path']for p in preview['artifacts']}
            if any(other['id']!=jid and any(a.get('original')in aliases and a.get('original_status')!='deleted'for a in self._original_references(other))for other in self.jobs()):raise ArchiveError('Another job claimed these originals; retain them')
            job['cleanup_journal']=dict(state='prepared',paths=preview['artifacts'],removed=[],created_at=now());job['cleanup_status']='deleting';self._job_save(job)
        self._finish_cleanup(job);self._event('job.cleanup',jid);return self.report(jid)

    def _finish_cleanup(self,job):
        journal=job['cleanup_journal'];removed=set(journal['removed'])
        for entry in journal['paths']:
            path=Path(entry['path']);ledger=next(e for e in job['ledger']if e['id']==entry['ledger_id'])
            if str(path)in removed:continue
            self._safe_descendant(job,path)
            if path.exists():
                stat=path.stat()
                if path.is_symlink()or(stat.st_dev,stat.st_ino)!=(ledger['dev'],ledger['ino'])or digest(path)!=ledger['sha256']:raise ArchiveError('Cleanup identity changed; deletion stopped')
                if str(path)==job['source_path']:raise ArchiveError('Imported source is never deleted')
                path.unlink()  # Explicit enabled policy authorizes permanent cleanup of these journaled owned aliases only.
                self._sync_tree(job,path)
            journal['removed'].append(str(path));self._job_save(job)
        covered={p['ledger_id']for p in journal['paths']}
        removed_paths={p['path']for p in journal['paths']}
        for e in job['ledger']:
            if e['id']in covered and set(e['aliases'])<=removed_paths:e['lifecycle']='deleted'
        for a in job['artifacts']:
            if a.get('original')in removed_paths:a['original_status']='deleted'
        for generation in job.get('generations',[]):
            for a in generation.get('artifacts',[]):
                if a.get('original')in{p['path']for p in journal['paths']}:a['original_status']='deleted'
        for r in job['reports']:
            artifact=next((a for a in job['artifacts']if a['title_id']==r.get('title_id')),None)
            if artifact:r['original_status']=artifact.get('original_status','retained')
        journal['state']='committed';job.update(cleanup_status='deleted',revision=job['revision']+1);self._job_save(job)

    def metadata_credential(self,data=None,delete=False):
        if sys.platform!='darwin':raise ArchiveError('Metadata credentials require macOS Keychain')
        base=['/usr/bin/security']
        if delete:
            subprocess.run(base+['delete-generic-password','-s','dev.discporter.tmdb','-a','api-token'],capture_output=True)
            self._event('metadata.credential.delete','tmdb');return dict(configured=False)
        if data is not None:
            token=data.get('token')
            if not isinstance(token,str)or not token.strip()or len(token)>4096:raise ArchiveError('Provide a TMDb API access token')
            r=subprocess.run(base+['add-generic-password','-U','-s','dev.discporter.tmdb','-a','api-token','-w',token],capture_output=True)
            if r.returncode:raise ArchiveError('Keychain could not store this credential; no credential saved in settings')
            self._event('metadata.credential.store','tmdb');return dict(configured=True)
        r=subprocess.run(base+['find-generic-password','-s','dev.discporter.tmdb','-a','api-token'],capture_output=True)
        return dict(configured=r.returncode==0)

    @busy
    def identify(self,data):
        provider=data.get('provider','local');query=data.get('query','');suggestions=[];inventory=[]
        if provider=='local':
            for p in self.profiles():
                if data.get('disc_id')and p['disc_id']!=data['disc_id']:continue
                if query and query.casefold()not in p['collection'].casefold():continue
                suggestions.append(dict(title=p['collection'],kind=p['kind'],provider='local',evidence='Previously saved explicit local mapping; verify disc/title/cut before use',confidence=.9))
            if data.get('source_path'):
                path=Path(data['source_path']).expanduser().resolve(strict=True)
                if not path.is_file():raise ArchiveError('Local technical inventory requires one media file')
                probe=self.probe(path)
                inventory=[dict(index=s['index'],type=s['codec_type'],codec=s.get('codec_name'),language=__import__('engine.core',fromlist=['language']).language(s)or'und',channels=s.get('channels'),width=s.get('width'),height=s.get('height'),disposition=s.get('disposition',{}),title=s.get('tags',{}).get('title',''))for s in probe['streams']]
        elif provider=='tmdb':
            if not self.settings()['online_lookup']:raise ArchiveError('Enable online_lookup explicitly before TMDb search')
            if not query.strip():raise ArchiveError('TMDb lookup requires a user-provided text query')
            import urllib.parse,urllib.request
            r=subprocess.run(['/usr/bin/security','find-generic-password','-s','dev.discporter.tmdb','-a','api-token','-w'],capture_output=True,text=True)
            if r.returncode:raise ArchiveError('Configure TMDb token in macOS Keychain first')
            url='https://api.themoviedb.org/3/search/multi?'+urllib.parse.urlencode(dict(query=query,include_adult='false'))
            try:
                req=urllib.request.Request(url,headers={'Authorization':'Bearer '+r.stdout.strip(),'Accept':'application/json'})
                with urllib.request.urlopen(req,timeout=20)as response:result=json.load(response)
            except Exception:raise ArchiveError('TMDb search failed; credentials and private source paths were not included in the query')
            for s in result.get('results',[])[:20]:
                if s.get('media_type')not in('movie','tv'):continue
                date=s.get('release_date')or s.get('first_air_date')or''
                item=dict(title=s.get('title')or s.get('name'),kind='film'if s['media_type']=='movie'else'series',provider='tmdb',evidence='https://www.themoviedb.org/'+('movie/'if s['media_type']=='movie'else'tv/')+str(s['id']),confidence=.5)
                if date[:4].isdigit():item['year']=int(date[:4])
                suggestions.append(item)
        else:raise ArchiveError('Provider must be local or tmdb')
        return dict(suggestions=suggestions,requires_confirmation=True,technical_inventory=inventory)

    def _tool_support(self):
        path=self.tools.get('ffmpeg')
        if getattr(self,'_support_cache',{}).get('path')==path:return self._support_cache
        result=dict(path=path,hardware_encoders=[],software_encoders=[],text_subtitle_burn=False,hardware_pilots={})
        if path:
            try:
                enc=self._capture([path,'-hide_banner','-encoders'],timeout=15,inspection=True);filters=self._capture([path,'-hide_banner','-filters'],timeout=15,inspection=True)
                for codec in('hevc','h264'):
                    if codec+'_videotoolbox'in enc.stdout:
                        try:
                            pilot=self._capture([path,'-nostdin','-v','error','-f','lavfi','-i','color=size=64x64:rate=2:duration=0.5','-c:v',codec+'_videotoolbox','-allow_sw','0','-b:v','1000k','-f','null','-'],timeout=5,inspection=True)
                            passed=pilot.returncode==0
                        except(OSError,subprocess.TimeoutExpired,Stopped):passed=False
                        result['hardware_pilots'][codec]=dict(source_class='synthetic SDR 8-bit 4:2:0',passed=passed)
                        if passed:result['hardware_encoders'].append(codec)
                for codec,name in [('hevc','libx265'),('h264','libx264')]:
                    if name in enc.stdout:result['software_encoders'].append(codec)
                result['text_subtitle_burn']=bool(__import__('re').search(r'\bsubtitles\s+',filters.stdout))
            except(OSError,subprocess.TimeoutExpired,Stopped):pass
        self._support_cache=result;return result

    def _check_render_support(self,probe,recipe,title):
        from engine.media import select_streams,TEXT
        support=self._tool_support()
        codecs=support['hardware_encoders']if recipe['encoder']=='hardware'else support['software_encoders']
        if recipe['video_codec']not in codecs:raise ArchiveError('Selected video encoder is unavailable in this FFmpeg build')
        if recipe['subtitle_policy']=='burn':
            _,subs,_=select_streams(probe,recipe,title)
            if subs and subs[0].get('codec_name')in TEXT and not support['text_subtitle_burn']:raise ArchiveError('This FFmpeg build lacks libass subtitle burn; choose text/copy or original mode')

    def _verify_text_cues(self,source,source_index,output,output_index):
        import re
        def cues(path,index):
            r=self._capture([self.tools['ffmpeg'],'-nostdin','-v','error','-i',path,'-map','0:'+str(index),'-c:s','srt','-f','srt','-'],timeout=None)
            if r.returncode:raise ArchiveError('Subtitle text projection failed; preserve original for review')
            parsed=[]
            for block in re.split(r'\n\s*\n',r.stdout.replace('\r\n','\n').strip()):
                lines=block.splitlines()
                if not lines:continue
                timing=next((i for i,l in enumerate(lines)if'-->'in l),None)
                if timing is None:continue
                match=re.match(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)',lines[timing])
                if not match:raise ArchiveError('Invalid subtitle timing projection')
                n=list(map(int,match.groups()));start=n[0]*3600000+n[1]*60000+n[2]*1000+n[3];end=n[4]*3600000+n[5]*60000+n[6]*1000+n[7]
                text=' '.join(re.sub(r'<[^>]+>','', '\n'.join(lines[timing+1:])).split())
                if text:parsed.append((start,end,text))
            return parsed
        before=cues(source,source_index);after=cues(output,output_index)
        if len(before)!=len(after)or any(a[2]!=b[2]or abs(a[0]-b[0])>50 or abs(a[1]-b[1])>50 for a,b in zip(before,after)):raise ArchiveError('Subtitle cue content/timing differs from selected source')
        return dict(source_index=source_index,output_index=output_index,cue_count=len(before),normalized_text_and_timing='passed',timing_tolerance_ms=50,style_projection='SRT text projection; original styling retained in source/sidecar')
