"""Durable resumable, verified, no-overwrite archive exports."""
import errno
import os
from pathlib import Path
import shutil
import threading
import uuid
from engine.core import ArchiveError, check_identity, identity, digest, now

class StaleTransfer(ArchiveError):pass

class Transfers:
    def create_export(self,data):
        with self.mutex:self.control_busy+=1
        try:return self._create_export(data)
        finally:
            with self.mutex:self.control_busy-=1

    def _create_export(self,data):
        job=self.job(data['job_id']);self._revision(job,data,allow_legacy=True)
        if self.disconnect_fenced:raise ArchiveError('Exports fenced for disconnect')
        destination=Path(data.get('destination','')).expanduser().resolve(strict=True)
        if not destination.is_dir():raise ArchiveError('Export destination must already exist')
        binding=identity(destination);files=[]
        for a in job['artifacts']:
            if not a.get('final')or not a.get('technical_verified'):raise ArchiveError('Export requires verified final deliverables')
            paths=[(a['final'],a['candidate_sha256'])]+[(s['path'],s['sha256'])for s in a.get('sidecars',[])if s.get('path')]
            for src,verified_hash in paths:
                p=Path(src)
                if not p.is_file():raise ArchiveError('Archive deliverable missing')
                if digest(p)!=verified_hash:raise ArchiveError('Verified archive deliverable changed; export blocked')
                target=destination/p.name
                if target.exists():raise ArchiveError('Export collision: '+p.name)
                files.append(dict(source=str(p),destination=str(target),sha256=verified_hash,bytes=p.stat().st_size,state='pending',processed_bytes=0))
        if not files:raise ArchiveError('No verified deliverables to export')
        eid=uuid.uuid4().hex;transfer=dict(id=eid,job_id=job['id'],state='queued',files=files,destination_identity=binding,created_at=now(),updated_at=now(),message='Queued verified transfer',pause_requested=False,stop_requested=False,processed_bytes=0,total_bytes=sum(f['bytes']for f in files),revision=1,worker_epoch=0)
        with self.mutex:
            if self.disconnect_fenced:raise ArchiveError('Disconnect fence active')
            self._save('export',eid,transfer)
        self._start_export(eid);self._event('export.create',eid);return transfer
    def export(self,eid):
        t=self._get('export',eid)
        if not t:raise ArchiveError('Export not found')
        return t
    def exports(self):return dict(exports=self._all('export'))
    def _start_export(self,eid):
        if eid in self.transfer_threads and self.transfer_threads[eid].is_alive():return
        t=threading.Thread(target=self._run_export,args=(eid,),daemon=True);self.transfer_threads[eid]=t;t.start()
    def _save_transfer(self,t):
        with self.mutex:
            current=self.export(t['id'])
            if t.get('worker_epoch',0)!=current.get('worker_epoch',0):raise StaleTransfer('Older transfer worker superseded; state retained')
            for key in('manual_pause','pause_cause'):
                if key in current:t[key]=current[key]
            t['revision']=max(t.get('revision',1),current.get('revision',1))
            for k in('pause_requested','stop_requested'):t[k]=current.get(k,False)or t.get(k,False)
            t['updated_at']=now();self._save('export',t['id'],t)
    def _run_export(self,eid):
        t=self.export(eid)
        try:
            t.update(state='running',message='Copying verified deliverables');self._save_transfer(t)
            for f in t['files']:
                if f['state']=='completed':continue
                check_identity(t['destination_identity']);target=Path(f['destination']);src=Path(f['source'])
                if target.is_symlink()or target.parent!=Path(t['destination_identity']['path']):raise ArchiveError('Export destination identity/path changed')
                if digest(src)!=f['sha256']:raise ArchiveError('Export source changed')
                candidate=target.with_name('.'+target.name+'.transfer-'+uuid.uuid4().hex);f['candidate']=str(candidate);f['state']='copying';self._save_transfer(t)
                if target.exists():
                    # A committed intent can recover a link after a crash, but other output never replaces it.
                    if not f.get('publish_intent')or not Path(f.get('published_candidate','')).is_file()or not os.path.samefile(target,f['published_candidate'])or digest(target)!=f['sha256']:raise ArchiveError('Export output already exists')
                else:
                    try:os.link(src,candidate);f['processed_bytes']=f['bytes']
                    except OSError as e:
                        if e.errno not in(errno.EXDEV,errno.EPERM,errno.ENOTSUP,errno.EOPNOTSUPP):raise
                        with src.open('rb')as source,candidate.open('xb')as dest:
                            while True:
                                chunk=source.read(1024*1024)
                                if not chunk:break
                                dest.write(chunk);f['processed_bytes']+=len(chunk);t['processed_bytes']=sum(x['processed_bytes']for x in t['files']);self._save_transfer(t)
                                current=self.export(eid)
                                if current['stop_requested']or self.disconnect_fenced:
                                    t.update(state='paused',message='Stopped; partial candidate retained; unfinished file restarts');self._save_transfer(t);return
                            dest.flush();os.fsync(dest.fileno())
                    if digest(candidate)!=f['sha256']:raise ArchiveError('Copied file hash differs from archive')
                    self._fsync(candidate)
                    f['publish_intent']=True;f['published_candidate']=str(candidate);self._save_transfer(t)
                    os.link(candidate,target);self._fsync(target)
                f.update(state='completed',processed_bytes=f['bytes']);t['processed_bytes']=sum(x['processed_bytes']for x in t['files']);self._save_transfer(t)
                current=self.export(eid)
                if current['pause_requested']or current['stop_requested']or self.disconnect_fenced:
                    t.update(state='paused',message='Paused after committed file');self._save_transfer(t);return
            t.update(state='completed',message='Every export hash verified; manual playback acceptance unchanged');self._save_transfer(t)
        except StaleTransfer:return
        except Exception as e:t.update(state='waiting_destination'if isinstance(e,OSError)or'identity'in str(e).lower()else'blocked',message=str(e));self._save_transfer(t)
    def export_action(self,eid,data):
        action=data.get('action')
        thread=self.transfer_threads.get(eid)
        if action=='resume'and thread and thread.is_alive():
            thread.join(timeout=2)
            if thread.is_alive():raise ArchiveError('Transfer is still stopping; resume after its worker drains')
        with self.mutex:
            t=self.export(eid);self._revision(t,data,allow_legacy=True)
            if action=='resume':
                if self.disconnect_fenced:raise ArchiveError('Resume archiving before exports')
                t.update(state='queued',pause_requested=False,stop_requested=False,revision=t['revision']+1,worker_epoch=t.get('worker_epoch',0)+1)
                for f in t['files']:
                    if f['state']!='completed':f['processed_bytes']=0
                self._save('export',eid,t)
            elif action in('pause','stop_now'):
                t['pause_requested']=True;t['stop_requested']=action=='stop_now';t['revision']+=1;t['pause_cause']=data.get('pause_cause','manual');t['manual_pause']=t.get('manual_pause',False)or t['pause_cause']=='manual';self._save('export',eid,t)
            else:raise ArchiveError('Unknown export action')
        if action=='resume':self._start_export(eid)
        elif action=='stop_now':
            thread=self.transfer_threads.get(eid)
            if thread:thread.join(timeout=30)
        self._event('export.'+action,eid);return self.export(eid)
