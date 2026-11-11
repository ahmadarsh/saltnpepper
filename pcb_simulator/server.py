"""Local, persistent job server for the PCB simulation workbench.

Only the Python standard library is required by this server. CAD and FEM work runs
in one isolated worker process at a time; Gmsh is never called from HTTP threads.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit
import uuid
import urllib.request
import webbrowser

APP=Path(__file__).resolve().parent
ROOT=APP.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
DATA=APP/'data'
MAX_UPLOAD=512*1024*1024
ID=re.compile(r'^[a-f0-9]{32}$')

def write_json(path:Path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)

def read_json(path:Path,default=None):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return default

def process_alive(pid):
    """Check a parent without os.kill(pid, 0), which terminates processes on Windows."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 5: raise PermissionError('Parent process access denied')
            return False
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)): raise OSError('Cannot inspect parent')
            return code.value == 259  # STILL_ACTIVE
        finally: kernel.CloseHandle(handle)
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    return True

class Workbench:
    def __init__(self):
        self.lock=threading.RLock();self.jobs={};self.processes={};self.pending=queue.Queue()
        for folder in ('jobs','models','runs'):(DATA/folder).mkdir(parents=True,exist_ok=True)
        for kind,success in (('models','ready'),('runs','succeeded')):
            for path in (DATA/kind).glob('*/meta.json'):
                meta=read_json(path,{})
                if meta.get('status')==success and 'error' in meta:
                    meta.pop('error');write_json(path,meta)
        for path in (DATA/'jobs').glob('*/status.json'):
            job=read_json(path)
            if not job:continue
            if job['status'] in ('queued','running'):
                job.update(status='failed',stage='interrupted',message='The server stopped before this job finished. Saved intermediate files are retained.',error='Interrupted by server shutdown.')
                write_json(path,job)
                if job.get('run_id'):
                    meta_path=DATA/'runs'/job['run_id']/'meta.json';meta=read_json(meta_path,{})
                    meta.update(status='failed',error=job['error']);write_json(meta_path,meta)
                if job.get('model_id') and job['kind']=='import_model':
                    model_path=DATA/'models'/job['model_id'];meta=read_json(model_path/'meta.json',{})
                    meta['status']='ready' if (model_path/'inventory.json').exists() and (model_path/'preview.json').exists() else 'failed'
                    write_json(model_path/'meta.json',meta)
            self.jobs[job['id']]=job
        self.thread=threading.Thread(target=self._run_queue,daemon=True,name='pcb-job-queue');self.thread.start()

    def _save_job(self,job):
        job['updated_at']=time.time();write_json(DATA/'jobs'/job['id']/'status.json',job)

    def submit(self,kind,request,**identifiers):
        with self.lock:
            key=uuid.uuid4().hex
            job=dict(id=key,kind=kind,status='queued',stage='queued',message='Waiting for the local simulation worker.',created_at=time.time(),**identifiers)
            folder=DATA/'jobs'/key;folder.mkdir()
            request.update(job_id=key,job_dir=str(folder))
            write_json(folder/'request.json',request)
            self.jobs[key]=job;self._save_job(job);self.pending.put(key)
            return dict(job)

    def _run_queue(self):
        while True:
            key=self.pending.get()
            try:
                with self.lock:
                    job=self.jobs.get(key)
                    if not job or job['status']=='cancelled':continue
                    job.update(status='running',stage='starting',message='Starting the local worker.');self._save_job(job)
                folder=DATA/'jobs'/key
                with (folder/'worker.log').open('wb') as log:
                    options=dict(stdout=log,stderr=log,cwd=str(ROOT),env=dict(os.environ,PYTHONIOENCODING='utf-8'))
                    if os.name=='nt':options['creationflags']=subprocess.CREATE_NO_WINDOW
                    command=([sys.executable,'--worker',str(folder/'request.json')] if getattr(sys,'frozen',False)
                             else [sys.executable,'-u',str(APP/'worker.py'),str(folder/'request.json')])
                    process=subprocess.Popen(command,**options)
                    with self.lock:
                        self.processes[key]=process
                        # Cancellation can arrive during subprocess creation.
                        if job['status']=='cancelled' and process.poll() is None:process.terminate()
                    previous=None
                    while process.poll() is None:
                        progress=read_json(folder/'progress.json')
                        if progress and progress!=previous:
                            with self.lock:
                                if job['status']!='cancelled':
                                    job.update(stage=progress.get('stage','running'),message=progress.get('message','Working.'),progress=progress.get('progress'))
                                    self._save_job(job)
                            previous=progress
                        time.sleep(.2)
                    result=read_json(folder/'result.json',{})
                with self.lock:
                    self.processes.pop(key,None)
                    if job['status']=='cancelled':pass
                    elif process.returncode==0 and result.get('status')=='succeeded':
                        job.pop('error',None)
                        job.update(status='succeeded',stage='complete',message='Import complete.' if job['kind']=='import_model' else 'Simulation and result viewer are ready.')
                    else:
                        error=result.get('error',f'Worker exited with code {process.returncode}. See the saved log.')
                        job.update(status='failed',stage='failed',message=error,error=error)
                    self._save_job(job)
                    if 'model_id' in job and job['kind']=='import_model':
                        path=DATA/'models'/job['model_id']/'meta.json';meta=read_json(path,{})
                        meta.update(status='ready' if job['status']=='succeeded' else job['status'])
                        if job['status']=='succeeded':meta.pop('error',None)
                        if job.get('error'):meta['error']=job['error']
                        inventory=read_json(path.parent/'inventory.json',{})
                        meta['counts']=inventory.get('counts',{})
                        write_json(path,meta)
                    if 'run_id' in job:
                        path=DATA/'runs'/job['run_id']/'meta.json';meta=read_json(path,{})
                        meta.update(status=job['status'])
                        if job['status']=='succeeded':meta.pop('error',None)
                        if job.get('error'):meta['error']=job['error']
                        write_json(path,meta)
            except Exception as exc:
                with self.lock:
                    self.jobs[key].update(status='failed',stage='failed',message=str(exc),error=str(exc));self._save_job(self.jobs[key])
            finally:self.pending.task_done()

    def job(self,key):
        with self.lock:
            if key not in self.jobs:return None
            job=dict(self.jobs[key])
        path=DATA/'jobs'/key/'worker.log'
        if path.exists():
            with path.open('rb') as f:
                f.seek(0,2);f.seek(max(0,f.tell()-18000));job['log_tail']=f.read().decode('utf-8',errors='replace')
        return job

    def cancel(self,key):
        with self.lock:
            job=self.jobs.get(key)
            if not job:return None
            if job['status'] in ('queued','running'):
                job.update(status='cancelled',stage='cancelled',message='Cancelled. Already saved CAD, mesh and port files are retained.');self._save_job(job)
                process=self.processes.get(key)
                if process and process.poll() is None:process.terminate()
                if job.get('run_id'):
                    path=DATA/'runs'/job['run_id']/'meta.json';meta=read_json(path,{})
                    meta.update(status='cancelled');write_json(path,meta)
                if job.get('model_id') and job['kind']=='import_model':
                    path=DATA/'models'/job['model_id']/'meta.json';meta=read_json(path,{})
                    meta.update(status='cancelled');write_json(path,meta)
            return dict(job)

    def stop(self):
        with self.lock:
            for key in list(self.jobs):self.cancel(key)
            processes=list(self.processes.values())
        for process in processes:
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)

    def delete_saved(self, kind, key=None):
        """Delete saved items and their logs only when related workers are idle."""
        if kind not in ('models', 'runs') or (key is not None and not ID.fullmatch(key)):
            raise ValueError('Invalid saved item.')
        with self.lock:
            folder=DATA/kind
            keys=[key] if key else [p.name for p in folder.iterdir() if p.is_dir() and ID.fullmatch(p.name)]
            if key and not (folder/key).is_dir():raise FileNotFoundError('Saved item not found.')
            field='model_id' if kind=='models' else 'run_id'
            related=[j for j in self.jobs.values() if j.get(field) in keys]
            if any(j['status'] in ('queued','running') or
                   (j['id'] in self.processes and self.processes[j['id']].poll() is None) for j in related):
                raise RuntimeError('Wait for related jobs to finish or cancel them before deleting.')
            # Completed runs retain their own source, fields and viewers when a model is removed.
            jobs=[j['id'] for j in related if kind=='runs' or j['kind']=='import_model']
            for item in keys:shutil.rmtree(folder/item)
            for job_id in jobs:
                shutil.rmtree(DATA/'jobs'/job_id,ignore_errors=True)
                self.jobs.pop(job_id,None)
            return dict(deleted=keys,deleted_jobs=jobs)

def artifacts(run_id):
    folder=DATA/'runs'/run_id
    if not folder.exists():return []
    rows=[]
    for path in sorted(folder.rglob('*')):
        if not path.is_file() or path.name.startswith('.') or path.suffix=='.tmp':continue
        name=path.relative_to(folder).as_posix()
        rows.append(dict(name=name,size=path.stat().st_size,url=f'/artifacts/{run_id}/'+quote(name,safe='/')))
    return rows

def validate_selection(data,inventory):
    rows={int(v['tag']):v for v in inventory.get('solids',[])};known=set(rows)
    groups=[]
    for key in ('input_tags','output_tags'):
        raw=data.get(key)
        if not isinstance(raw,list) or not raw or any(type(v) is not int for v in raw):raise ValueError('Choose at least one input pad and one output pad.')
        group=sorted(set(raw))
        if not set(group)<=known:raise ValueError('A selected pad does not belong to this imported model.')
        group=sorted({rows[tag].get('kicad_pad_tag',tag) for tag in group})
        if not set(group)<=known:raise ValueError('A pad refers to missing copper solids; import it again.')
        groups.append(group)
    if set(groups[0])&set(groups[1]):raise ValueError('The same pad cannot be both input and output.')
    return groups

class Handler(BaseHTTPRequestHandler):
    server_version='PCBWorkbench/1.0'
    def log_message(self,fmt,*args):
        # Polls are deliberately quiet; full job logs are persisted separately.
        if ' 4' in (fmt%args) or ' 5' in (fmt%args):super().log_message(fmt,*args)
    @property
    def workbench(self):return self.server.workbench
    def do_DELETE(self):
        if not self.safe_origin():self.send_json(dict(error='Open the app from its local URL.'),403);return
        parts=urlsplit(self.path).path.strip('/').split('/')
        if len(parts) not in (2,3) or parts[0]!='api' or parts[1] not in ('models','runs'):
            self.send_json(dict(error='Endpoint not found.'),404);return
        try:
            self.send_json(self.workbench.delete_saved(parts[1],parts[2] if len(parts)==3 else None))
        except ValueError as exc:self.send_json(dict(error=str(exc)),400)
        except FileNotFoundError as exc:self.send_json(dict(error=str(exc)),404)
        except RuntimeError as exc:self.send_json(dict(error=str(exc)),409)
        except OSError as exc:self.send_json(dict(error='Could not remove saved files: '+str(exc)),500)
    def send_json(self,value,status=200):
        body=json.dumps(value,allow_nan=False).encode('utf-8');self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def body_json(self):
        n=int(self.headers.get('Content-Length','0'))
        if n>1024*1024:raise ValueError('Request parameters are too large.')
        value=json.loads(self.rfile.read(n)) if n else {}
        if not isinstance(value,dict):raise ValueError('Expected a JSON object.')
        return value
    def safe_origin(self):
        origin=self.headers.get('Origin')
        if not origin:return True
        o=urlsplit(origin)
        return o.scheme=='http' and o.hostname in ('127.0.0.1','localhost') and o.port==self.server.server_port
    def do_POST(self):
        if not self.safe_origin():self.send_json(dict(error='Open the app from its local URL.'),403);return
        try:self.post()
        except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:self.send_json(dict(error=str(exc)),400)
        except Exception as exc:self.send_json(dict(error=str(exc)),500)
    def post(self):
        route=urlsplit(self.path);parts=route.path.strip('/').split('/')
        if route.path in ('/api/workspace/export','/api/workspace/import','/api/workspace/save-native','/api/workspace/open-native'):
            return self.workspace_post(route)
        if route.path.startswith('/api/kicad/'):
            return self.kicad_post(route,parts)
        if route.path=='/api/shutdown':
            value=self.body_json()
            if not hmac.compare_digest(str(value.get('token','')),self.server.control_token):
                self.send_json(dict(error='Use the Stop Salt and Pepper launcher.'),403);return
            try:self.send_json(dict(status='stopping'))
            except (BrokenPipeError,ConnectionResetError):pass
            self.workbench.stop();threading.Thread(target=self.server.shutdown,daemon=True).start();return
        if route.path=='/api/models':
            filename=parse_qs(route.query).get('filename',['model.step'])[0]
            filename=filename.replace('\\','/').split('/')[-1]
            if Path(filename).suffix.lower() not in ('.step','.stp'):raise ValueError('Choose a .step or .stp file.')
            length=int(self.headers.get('Content-Length','0'))
            if length<=0 or length>MAX_UPLOAD:raise ValueError('Choose a nonempty STEP file smaller than 512 MiB.')
            key=uuid.uuid4().hex;folder=DATA/'models'/key;folder.mkdir()
            source=folder/'source.step';digest=hashlib.sha256()
            remaining=length;first=True
            with source.open('wb') as f:
                while remaining:
                    chunk=self.rfile.read(min(1024*1024,remaining))
                    if not chunk:raise ValueError('The upload ended before the file was complete.')
                    if first:
                        if b'ISO-10303-21' not in chunk[:2048].upper():raise ValueError('This file does not contain a STEP exchange header.')
                        first=False
                    f.write(chunk);digest.update(chunk);remaining-=len(chunk)
            self.finish_model(key,filename,digest.hexdigest());return
        if route.path=='/api/models/example':
            source=ROOT/'examples'/'copper-bar.step'
            if not source.exists():raise ValueError('The example STEP is unavailable. Import your own file.')
            key=uuid.uuid4().hex;folder=DATA/'models'/key;folder.mkdir();shutil.copy2(source,folder/'source.step')
            self.finish_model(key,'copper-bar.step',hashlib.sha256(source.read_bytes()).hexdigest());return
        if route.path=='/api/runs':
            config=self.body_json();model_id=config.get('model_id','')
            if not ID.fullmatch(str(model_id)):raise ValueError('Choose an imported model first.')
            model=read_json(DATA/'models'/model_id/'meta.json',{})
            if model.get('status')!='ready':raise ValueError('Wait for the STEP import to finish.')
            inventory=read_json(DATA/'models'/model_id/'inventory.json',{})
            source_tags,output_tags=validate_selection(config,inventory)
            params=config.get('parameters',{})
            if not isinstance(params,dict):raise ValueError('Expected parameter values.')
            # Lightweight validation is repeated by the engine before CAD changes.
            import math
            for name,value in params.items():
                if isinstance(value,(int,float)) and not isinstance(value,bool) and not math.isfinite(value):raise ValueError(f'{name} must be finite.')
            key=uuid.uuid4().hex;folder=DATA/'runs'/key;folder.mkdir()
            source_file='source.xao' if model.get('source_file')=='source.xao' else 'source.step'
            request=dict(operation='simulate',source=str(DATA/'models'/model_id/source_file),inventory=str(DATA/'models'/model_id/'inventory.json'),
                output_dir=str(folder),input_tags=source_tags,output_tags=output_tags,parameters=params)
            write_json(folder/'config.json',dict(model_id=model_id,filename=model.get('filename'),input_tags=source_tags,output_tags=output_tags,parameters=params))
            job=self.workbench.submit('simulation',request,model_id=model_id,run_id=key)
            write_json(folder/'meta.json',dict(id=key,model_id=model_id,board_id=model.get('board_id'),filename=model.get('filename'),job_id=job['id'],status='queued',created_at=time.time()))
            self.send_json(dict(run_id=key,job_id=job['id']),202);return
        if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='cancel':
            job=self.workbench.cancel(parts[2])
            self.send_json(job if job else dict(error='Job not found.'),200 if job else 404);return
        self.send_json(dict(error='Endpoint not found.'),404)

    def workspace_post(self,route):
        from pcb_simulator.workspace_archive import export_workspace,import_workspace
        if route.path.endswith(('/save-native','/open-native')):
            if not getattr(self.server,'native_workspace_save',False):
                self.send_json(dict(error='Native workspace saving is not enabled for this server.'),403);return
            from pcb_simulator.windows_workspace import save_workspace,open_workspace
            value=self.body_json()
            lock=self.server.workspace_save_lock
            if not lock.acquire(blocking=False):
                self.send_json(dict(error='A workspace Save dialog is already open.'),409);return
            try:
                files=getattr(self.server,'workspace_files',{})
                token=value.get('file_token')
                if token is not None and (not isinstance(token,str) or token not in files):
                    self.send_json(dict(error='Reopen this workspace before saving to its original file.'),409);return
                if route.path.endswith('/open-native'):
                    result=open_workspace(DATA,owner_pid=self.server.desktop_parent,previous_path=getattr(self.server,'last_workspace_path',None))
                else:
                    result=save_workspace(DATA,value,owner_pid=self.server.desktop_parent,
                        previous_path=getattr(self.server,'last_workspace_path',None),existing_path=files.get(token),save_as=value.get('save_as') is True)
                if result['status'] in ('saved','opened'):
                    if not token or value.get('save_as') or result['status']=='opened':token=uuid.uuid4().hex
                    files[token]=result['path'];self.server.workspace_files=files
                    self.server.last_workspace_path=result['path'];result['native_file_token']=token
                self.send_json(result)
            finally:lock.release()
            return
        with tempfile.TemporaryDirectory(prefix='.workspace-transfer-',dir=DATA) as temporary:
            folder=Path(temporary)
            if route.path.endswith('/export'):
                value=self.body_json()
                result=export_workspace(DATA,board_id=value.get('board_id'),model_id=value.get('model_id'),name=value.get('name','Workspace'),ui_state=value.get('ui_state',{}),outputpath=folder/'workspace.pepper')
                # Serve the requested safe filename rather than the staging name.
                archive=folder/result['suggested_filename'];Path(result['path']).replace(archive)
                self.file(archive,attachment=True);return
            filename=parse_qs(route.query).get('filename',['workspace.pepper'])[0]
            if Path(filename).suffix.lower()!='.pepper':raise ValueError('Choose a .pepper workspace file.')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=2*1024**3:raise ValueError('Choose a workspace smaller than 2 GiB.')
            archive=folder/'workspace.pepper';remaining=length
            with archive.open('wb') as stream:
                while remaining:
                    chunk=self.rfile.read(min(1024**2,remaining))
                    if not chunk:raise ValueError('The workspace upload was incomplete.')
                    stream.write(chunk);remaining-=len(chunk)
            self.send_json(import_workspace(DATA,archive))

    def kicad_post(self,route,parts):
        base=DATA/'boards';base.mkdir(exist_ok=True)
        if route.path=='/api/kicad/boards':
            filename=parse_qs(route.query).get('filename',['board.kicad_pcb'])[0].replace('\\','/').split('/')[-1]
            if Path(filename).suffix.lower()!='.kicad_pcb':raise ValueError('Choose a .kicad_pcb file.')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16*1024*1024:raise ValueError('Choose a board smaller than 16 MiB for this prototype.')
            raw=self.rfile.read(length)
            if len(raw)!=length:raise ValueError('The board upload was incomplete.')
            if not raw.lstrip().startswith(b'(kicad_pcb'):raise ValueError('This is not a KiCad PCB file.')
            key=uuid.uuid4().hex;folder=base/key;folder.mkdir()
            (folder/'source.kicad_pcb').write_bytes(raw)
            job=self.workbench.submit('kicad_import',dict(operation='kicad_inspect',source=str(folder/'source.kicad_pcb'),output_dir=str(folder)),board_id=key)
            write_json(folder/'meta.json',dict(id=key,filename=filename,job_id=job['id'],created_at=time.time()))
            self.send_json(dict(board_id=key,job_id=job['id']),202);return
        if len(parts)==5 and parts[:3]==['api','kicad','boards'] and ID.fullmatch(parts[3]) and parts[4]=='colours':
            folder=base/parts[3];board=read_json(folder/'board.json')
            if not board:raise ValueError('Import a board before its project colours.')
            from pcb_simulator.kicad_preview import project_colours
            project=self.body_json();count=project_colours(board,project)
            write_json(folder/'project.kicad_pro',project)
            write_json(folder/'board.json',board)
            self.send_json(dict(board=board,imported=count));return
        if len(parts)==5 and parts[:3]==['api','kicad','boards'] and ID.fullmatch(parts[3]) and parts[4] in ('select','prepare'):
            folder=base/parts[3];board=read_json(folder/'board.json')
            if not board:raise ValueError('Wait for the board import to finish.')
            value=self.body_json();net=value.get('net')
            if net not in {n['name'] for n in board['nets']}:raise ValueError('Choose a net from this board.')
            key=uuid.uuid4().hex;output=folder/'exports'/key;output.mkdir(parents=True)
            op='kicad_net' if parts[4]=='select' else 'kicad_prepare'
            request=dict(operation=op,source=str(folder/'source.kicad_pcb'),output_dir=str(output),net=net)
            if op=='kicad_prepare':
                inputs=value.get('input_ids');outputs=value.get('output_ids')
                if not isinstance(inputs,list) or not isinstance(outputs,list):raise ValueError('Choose input and output pads.')
                request.update(input_ids=inputs,output_ids=outputs)
                model_id=uuid.uuid4().hex;model_folder=DATA/'models'/model_id;model_folder.mkdir()
                meta=read_json(folder/'meta.json',{})
                write_json(model_folder/'meta.json',dict(id=model_id,board_id=parts[3],filename=meta.get('filename','KiCad board')+' · '+net,status='queued',origin='kicad',source_file='source.xao',created_at=time.time()))
                request.update(workbench_dir=str(model_folder),board_file=str(folder/'board.json'))
                job=self.workbench.submit('import_model',request,board_id=parts[3],model_id=model_id)
                model_meta=read_json(model_folder/'meta.json');model_meta['job_id']=job['id'];write_json(model_folder/'meta.json',model_meta)
                self.send_json(dict(export_id=key,job_id=job['id'],model_id=model_id),202);return
            job=self.workbench.submit(op,request,board_id=parts[3])
            self.send_json(dict(export_id=key,job_id=job['id']),202);return
        self.send_json(dict(error='KiCad endpoint not found.'),404)

    def kicad_get(self,path,parts):
        if path=='/api/kicad/example':
            example=ROOT/'examples'/'USB-UART'/'USB-UART.kicad_pcb'
            if not example.exists():example=ROOT/'prototypes'/'v0.9-mac'/'examples'/'USB-UART.kicad_pcb'
            self.file(example if example.exists() else ROOT/'examples'/'two-layer-demo.kicad_pcb',attachment=True);return
        if path=='/api/kicad/example-project':
            example=ROOT/'examples'/'USB-UART'/'USB-UART.kicad_pro'
            if not example.exists():example=ROOT/'prototypes'/'v0.9-mac'/'examples'/'USB-UART.kicad_pro'
            self.file(example if example.exists() else ROOT/'examples'/'two-layer-demo.kicad_pro');return
        if path=='/api/kicad/example-project.zip':
            archive=ROOT/'examples'/'USB-UART.zip'
            self.file(archive if archive.exists() else ROOT/'USB-UART.zip',attachment=True);return
        if path=='/api/kicad/status':
            from pcb_simulator.kicad_preview import status
            self.send_json(dict(**status(),example_archive_available=(ROOT/'examples'/'USB-UART.zip').is_file() or (ROOT/'USB-UART.zip').is_file()));return
        if len(parts)>=4 and parts[:3]==['api','kicad','boards'] and ID.fullmatch(parts[3]):
            folder=DATA/'boards'/parts[3];meta=read_json(folder/'meta.json')
            if not meta:self.send_json(dict(error='Board not found.'),404);return
            if len(parts)==4:
                board=read_json(folder/'board.json')
                job=self.workbench.job(meta.get('job_id')) or {}
                result=dict(meta);result.update(status=job.get('status','succeeded' if board and meta.get('restored_from_workspace') else 'failed'),error=job.get('error'),board=board)
                self.send_json(result);return
            # Export file names are fixed; arbitrary paths and the original PCB are not served.
            if len(parts)==6 and parts[4]=='full' and parts[5] in ('top.svg','bottom.svg'):
                self.file(folder/'full'/parts[5]);return
            if len(parts)==6 and parts[4]=='coloured' and parts[5] in ('top.svg','bottom.svg'):
                self.file(folder/'coloured'/parts[5]);return
            if len(parts)==7 and parts[4]=='nets' and ID.fullmatch(parts[5]) and parts[6] in ('top.svg','bottom.svg'):
                self.file(folder/'nets'/parts[5]/parts[6]);return
            if len(parts)>=6 and parts[4]=='exports' and ID.fullmatch(parts[5]):
                relative='/'.join(parts[6:])
                if relative in ('selection.json','handoff.json','preview.json','copper.xao','highlight/top.svg','highlight/bottom.svg'):
                    target=folder/'exports'/parts[5]/relative
                    if relative.endswith('.json') and not target.exists():self.send_json(dict(error='Export is not ready.'),404);return
                    self.file(target,attachment=relative.endswith('.xao'));return
        self.send_json(dict(error='KiCad endpoint not found.'),404)

    def finish_model(self,key,filename,digest):
        folder=DATA/'models'/key
        job=self.workbench.submit('import_model',dict(operation='inspect',source=str(folder/'source.step'),output_dir=str(folder)),model_id=key)
        write_json(folder/'meta.json',dict(id=key,filename=filename,sha256=digest,status='queued',job_id=job['id'],created_at=time.time()))
        self.send_json(dict(model_id=key,job_id=job['id']),202)

    def do_GET(self):
        try:self.get()
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as exc:self.send_json(dict(error=str(exc)),500)
    def get(self):
        path=unquote(urlsplit(self.path).path);parts=path.strip('/').split('/')
        if path.startswith('/api/kicad/'):
            return self.kicad_get(path,parts)
        if path=='/api/workspace/capabilities':
            self.send_json(dict(native_save=bool(getattr(self.server,'native_workspace_save',False))));return
        if path=='/api/health':self.send_json(dict(status='ok',service='PCB Simulation Workbench',name='Salt and Pepper',version='2.0',local_only=True));return
        if path=='/api/models':
            rows=[read_json(p,{}) for p in (DATA/'models').glob('*/meta.json')]
            self.send_json(dict(models=sorted(rows,key=lambda v:v.get('created_at',0),reverse=True)));return
        if len(parts)==3 and parts[:2]==['api','models'] and ID.fullmatch(parts[2]):
            folder=DATA/'models'/parts[2];meta=read_json(folder/'meta.json')
            if meta:
                meta['inventory']=read_json(folder/'inventory.json',{})
                meta['preview_url']=f'/api/models/{parts[2]}/preview.json'
            self.send_json(meta or dict(error='Model not found.'),200 if meta else 404);return
        if len(parts)==4 and parts[:2]==['api','models'] and parts[3]=='preview.json' and ID.fullmatch(parts[2]):
            self.file(DATA/'models'/parts[2]/'preview.json');return
        if len(parts)==3 and parts[:2]==['api','jobs']:
            job=self.workbench.job(parts[2]);self.send_json(job or dict(error='Job not found.'),200 if job else 404);return
        if path=='/api/runs':
            rows=[read_json(p,{}) for p in (DATA/'runs').glob('*/meta.json')]
            self.send_json(dict(runs=sorted(rows,key=lambda v:v.get('created_at',0),reverse=True)));return
        if len(parts)==3 and parts[:2]==['api','runs'] and ID.fullmatch(parts[2]):
            folder=DATA/'runs'/parts[2];meta=read_json(folder/'meta.json')
            if meta:
                meta['report']=read_json(folder/'report.json');meta['artifacts']=artifacts(parts[2])
                meta['viewer_url']=f'/runs/{parts[2]}/viewer.html' if (folder/'viewer.html').exists() else None
            self.send_json(meta or dict(error='Run not found.'),200 if meta else 404);return
        if len(parts)>=3 and parts[0] in ('runs','artifacts') and ID.fullmatch(parts[1]):
            folder=(DATA/'runs'/parts[1]).resolve();target=(folder/Path(*parts[2:])).resolve()
            if not target.is_relative_to(folder):self.send_json(dict(error='Invalid artifact path.'),403);return
            self.file(target,attachment=parts[0]=='artifacts' and target.suffix not in ('.html','.png','.svg'));return
        relative='index.html' if path=='/' else path.lstrip('/')
        folder=(APP/'static').resolve();target=(folder/relative).resolve()
        if not target.is_relative_to(folder):self.send_json(dict(error='Invalid path.'),403);return
        self.file(target)
    def file(self,path:Path,attachment=False):
        if not path.is_file():self.send_json(dict(error='File not found.'),404);return
        self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(path.stat().st_size));self.send_header('Cache-Control','no-cache');self.send_header('X-Content-Type-Options','nosniff')
        if attachment:
            fallback=path.name.encode('ascii','replace').decode().replace('"','_').replace('\\','_')
            self.send_header('Content-Disposition','attachment; filename="'+fallback+'"; filename*=UTF-8\'\''+quote(path.name,safe=''))
        self.end_headers()
        with path.open('rb') as f:shutil.copyfileobj(f,self.wfile,1024*1024)

def main():
    global DATA
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8765);parser.add_argument('--no-browser',action='store_true');parser.add_argument('--stop',action='store_true')
    parser.add_argument('--data-dir',type=Path,help='Writable saved models, jobs and runs directory.')
    parser.add_argument('--desktop-parent',type=int,help=argparse.SUPPRESS)
    parser.add_argument('--native-workspace-dialogs',action='store_true',help='Enable native Open/Save dialogs for desktop source testing.')
    args=parser.parse_args()
    if args.data_dir:DATA=args.data_dir.expanduser().resolve()
    if args.stop:
        control=read_json(DATA/'server.json')
        if not control:print('Salt and Pepper is not running.');return
        request=urllib.request.Request(f'http://127.0.0.1:{control["port"]}/api/shutdown',data=json.dumps(dict(token=control['token'])).encode(),headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=5) as response:print(response.read().decode())
        except OSError as exc:raise SystemExit(f'Could not stop the server: {exc}')
        return
    # Check first: Windows can sometimes permit a second bind before accept.
    url=f'http://127.0.0.1:{args.port}/'
    try:
        with urllib.request.urlopen(url+'api/health',timeout=2) as response:existing=json.load(response)
        if existing.get('service')=='PCB Simulation Workbench':
            print(f'Salt and Pepper is already running: {url}')
            if not args.no_browser:webbrowser.open(url)
            return
    except (OSError,ValueError):pass
    try:server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError as exc:
        url=f'http://127.0.0.1:{args.port}/'
        try:
            with urllib.request.urlopen(url+'api/health',timeout=2) as response:
                existing=json.load(response)
            if existing.get('service')=='PCB Simulation Workbench':
                print(f'Salt and Pepper is already running: {url}')
                if not args.no_browser:webbrowser.open(url)
                return
        except (OSError,ValueError):pass
        raise SystemExit(f'Cannot start port {args.port}: {exc}. Use --port with another port.')
    workbench=Workbench()
    server.workbench=workbench
    server.desktop_parent=args.desktop_parent
    server.native_workspace_save=sys.platform in ('darwin','win32') and bool(args.desktop_parent or args.native_workspace_dialogs)
    server.workspace_save_lock=threading.Lock()
    server.workspace_files={}
    server.control_token=uuid.uuid4().hex
    write_json(DATA/'server.json',dict(pid=os.getpid(),port=server.server_port,token=server.control_token))
    url=f'http://127.0.0.1:{server.server_port}/'
    print(f'Salt and Pepper: {url}',flush=True)
    print('Local files and jobs: '+str(DATA),flush=True)
    if args.desktop_parent:
        def watch_parent():
            while True:
                time.sleep(1)
                try:alive=process_alive(args.desktop_parent)
                except PermissionError:continue
                if not alive:
                    workbench.stop();server.shutdown();return
        threading.Thread(target=watch_parent,daemon=True,name='desktop-parent-watch').start()
    if not args.no_browser:threading.Timer(.5,lambda:webbrowser.open(url)).start()
    try:server.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:pass
    finally:
        workbench.stop();server.server_close()
        control=read_json(DATA/'server.json',{})
        if control.get('pid')==os.getpid():(DATA/'server.json').unlink(missing_ok=True)

if __name__=='__main__':main()
