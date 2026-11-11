"""Mac V0.9 review prototype: native KiCad plots and named XAO handoff.

The original PCB is read-only. This module does not connect XAO to the FEM solver.
"""
from __future__ import annotations
import hashlib
import fnmatch
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

class Node:
    def __init__(self,start): self.start=start;self.end=None;self.items=[]
    @property
    def head(self): return self.items[0] if self.items and isinstance(self.items[0],str) else ''
    @property
    def args(self): return [x for x in self.items[1:] if isinstance(x,str)]
    def children(self,name=None): return [x for x in self.items if isinstance(x,Node) and (name is None or x.head==name)]
    def child(self,name): return next(iter(self.children(name)),None)
    def values(self,name,default=()):
        n=self.child(name);return n.args if n else default

def project_colours(board,project):
    """Read PCB net overrides and netclass colours from a companion .kicad_pro.

    KiCad stores these in net_settings, not the .kicad_pcb. Keep transparent
    defaults automatic. Only numeric RGB(A) values enter browser styles.
    """
    settings=project.get('net_settings')
    if not isinstance(settings,dict):raise ValueError('This project has no KiCad net settings.')
    def colour(value):
        if not isinstance(value,str):return None
        match=re.fullmatch(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?))?\s*\)',value)
        if not match:return None
        r,g,b=map(int,match.groups()[:3]);alpha=float(match.group(4) or 1)
        if max(r,g,b)>255 or alpha==0:return None
        return f'rgb({r}, {g}, {b})'
    raw_classes=settings.get('classes') or []
    if not isinstance(raw_classes,list):raise ValueError('Invalid KiCad netclasses.')
    classes={c['name']:c for c in raw_classes if isinstance(c,dict) and isinstance(c.get('name'),str)}
    if any(not isinstance(c.get('priority',2147483647),(int,float)) for c in classes.values()):raise ValueError('Invalid KiCad netclass priority.')
    assignments=settings.get('netclass_assignments') or {}
    overrides=settings.get('net_colors') or {}
    patterns=settings.get('netclass_patterns') or []
    if not isinstance(assignments,dict) or not isinstance(overrides,dict) or not isinstance(patterns,list):raise ValueError('Invalid KiCad net colour settings.')
    count=0
    for net in board['nets']:
        net.setdefault('automatic_colour',net['colour'])
        name=net['name'];chosen=colour(overrides.get(name));source='KiCad net override'
        if not chosen:
            names=assignments.get(name,[])
            names=[names] if isinstance(names,str) else list(names) if isinstance(names,list) else []
            names.extend(c['name'] for c in classes.values() if name in (c.get('nets') or []))
            names.extend(p['netclass'] for p in patterns if isinstance(p,dict) and isinstance(p.get('pattern'),str) and isinstance(p.get('netclass'),str) and fnmatch.fnmatchcase(name,p['pattern']))
            candidates=sorted((classes[n] for n in set(names) if n in classes),key=lambda c:(c.get('priority',2147483647),c['name']))
            candidates+=[classes['Default']] if 'Default' in classes else []
            for candidate in candidates:
                chosen=colour(candidate.get('pcb_color'))
                if chosen:source='KiCad netclass: '+candidate['name'];break
        net['colour']=chosen or net['automatic_colour'];net['colour_source']=source if chosen else 'Automatic'
        count+=bool(chosen)
    board['project_colours']=count
    return count

def parse(text):
    token=re.compile(r'\s+|;[^\n]*|\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+')
    stack=[];root=None;count=0
    for match in token.finditer(text):
        value=match.group()
        if value.isspace() or value.startswith(';'):continue
        count+=1
        if count>3_000_000:raise ValueError('Board is too large for this review prototype.')
        if value=='(':
            n=Node(match.start())
            if stack:stack[-1].items.append(n)
            elif root is not None:raise ValueError('Multiple board roots.')
            else:root=n
            stack.append(n)
            if len(stack)>128:raise ValueError('Board nesting is too deep.')
        elif value==')':
            if not stack:raise ValueError('Unbalanced board file.')
            stack.pop().end=match.end()
        else:
            if not stack:raise ValueError('Invalid board file.')
            try:decoded=json.loads(value) if value.startswith('"') else value
            except ValueError:raise ValueError('Invalid quoted string in board file.')
            stack[-1].items.append(decoded)
    if stack or root is None or root.head!='kicad_pcb':raise ValueError('Choose a valid .kicad_pcb board.')
    return root

def cli_path():
    if sys.platform not in ('darwin','win32'):raise ValueError('KiCad import currently supports macOS and Windows.')
    installed=(['/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'] if sys.platform=='darwin' else
               [str(Path(os.environ.get('ProgramFiles','C:/Program Files'))/'KiCad'/'10.0'/'bin'/'kicad-cli.exe')])
    choices=[os.environ.get('SALT_PEPPER_KICAD_CLI'),shutil.which('kicad-cli'),*installed]
    p=next((str(Path(p).resolve()) for p in choices if p and Path(p).is_file()),None)
    if not p:raise ValueError('The KiCad runtime is unavailable. Reinstall the app, or install KiCad 10.')
    return p

def run_cli(args,folder):
    result=subprocess.run([cli_path(),*map(str,args)],capture_output=True,text=True,timeout=180)
    with (Path(folder)/'kicad-cli.log').open('a',encoding='utf-8') as log:
        log.write(' '.join(map(str,args))+'\n'+result.stdout+result.stderr+'\n')
    if result.returncode:raise ValueError('KiCad export failed: '+(result.stderr or result.stdout)[-1800:])
    return result.stdout.strip()

def status():
    try:
        path=cli_path()
        # macOS may audit bundled native libraries on their first launch.
        r=subprocess.run([path,'--version'],capture_output=True,text=True,timeout=180 if os.environ.get('SALT_PEPPER_KICAD_BUNDLED')=='1' else 10)
        return dict(available=r.returncode==0,version=r.stdout.strip(),platform='Windows' if sys.platform=='win32' else 'macOS',prototype='0.9',bundled=os.environ.get('SALT_PEPPER_KICAD_BUNDLED')=='1')
    except (OSError,ValueError,subprocess.TimeoutExpired) as e:return dict(available=False,error=str(e),prototype='0.9',bundled=False)

def net_of(node,nets):
    values=node.values('net')
    if not values:return ''
    return values[1] if len(values)>1 else nets.get(values[0],values[0] if not values[0].isdigit() else '')

def walk(node):
    yield node
    for child in node.children():yield from walk(child)

def inventory(source):
    from pcb_simulator.kicad_details import board_details
    text=Path(source).read_text(encoding='utf-8-sig');tree=parse(text)
    nets={n.args[0]:n.args[1] for n in tree.children('net') if len(n.args)>1}
    pads=[];counts={name:dict(pads=0,tracks=0,vias=0,zones=0) for name in nets.values() if name}
    points=[]
    for footprint in tree.children('footprint')+tree.children('module'):
        reference=next((n.args[1] for n in footprint.children('property') if len(n.args)>1 and n.args[0]=='Reference'),None)
        if reference is None:reference=next((n.args[1] for n in footprint.children('fp_text') if len(n.args)>1 and n.args[0]=='reference'),'Unknown')
        at=footprint.values('at',('0','0'));fx,fy=map(float,at[:2]);rotation=float(at[2]) if len(at)>2 else 0
        theta=math.radians(rotation)
        for index,p in enumerate(footprint.children('pad')):
            args=p.args
            if len(args)<3:continue
            number,kind,shape=args[:3];a=p.values('at',('0','0'));dx,dy=map(float,a[:2]);size=list(map(float,p.values('size',('1','1'))[:2]))
            x=fx+math.cos(theta)*dx+math.sin(theta)*dy;y=fy-math.sin(theta)*dx+math.cos(theta)*dy
            layers=list(p.values('layers'));net=net_of(p,nets)
            uid=next(iter(p.values('uuid') or p.values('tstamp')),None)
            uid=uid or hashlib.sha256((reference+str(index)+text[p.start:p.end]).encode()).hexdigest()[:32]
            sides=[s for s,l in [('top','F.Cu'),('bottom','B.Cu')] if l in layers or '*.Cu' in layers or 'F&B.Cu' in layers]
            if not sides:continue
            pads.append(dict(id=uid,reference=reference,number=number,label=f'{reference} · Pad {number}',net=net,x_mm=x,y_mm=y,angle_deg=float(a[2]) if len(a)>2 else 0.,size_mm=size,shape=shape,type=kind,sides=sides,layers=layers))
            points.extend([(x-size[0]/2,y-size[1]/2),(x+size[0]/2,y+size[1]/2)])
            if net:counts.setdefault(net,dict(pads=0,tracks=0,vias=0,zones=0))['pads']+=1
    for node in tree.children():
        category={'segment':'tracks','arc':'tracks','via':'vias','zone':'zones'}.get(node.head)
        net=net_of(node,nets)
        if category and net:counts.setdefault(net,dict(pads=0,tracks=0,vias=0,zones=0))[category]+=1
        if node.head.startswith('gr_') and node.values('layer')==['Edge.Cuts']:
            for child in walk(node):
                if child.head in ['start','end','mid','center','xy'] and len(child.args)>=2:points.append(tuple(map(float,child.args[:2])))
    if not pads:raise ValueError('No copper pads were found in this board.')
    low=[min(p[i] for p in points)-2 for i in [0,1]];high=[max(p[i] for p in points)+2 for i in [0,1]]
    return dict(filename=Path(source).name,sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),pads=pads,nets=[dict(name=name,**values) for name,values in sorted(counts.items(),key=lambda p:p[0].casefold())],bounds_mm=low+high,details=board_details(tree),units='mm',prototype=True),tree,text,nets

def plots(source,folder,outline=True):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    run_cli(['pcb','export','svg','--layers','F.Cu,B.Cu',*(['--common-layers','Edge.Cuts'] if outline else []),'--mode-multi','--page-size-mode','1','--exclude-drawing-sheet','--output',folder,source],folder)
    result={}
    for side,suffix in [('top','F_Cu'),('bottom','B_Cu')]:
        candidates=list(folder.glob('*-'+suffix+'.svg'))
        if len(candidates)!=1:raise ValueError('KiCad did not produce both copper-layer plots.')
        destination=folder/(side+'.svg');candidates[0].replace(destination)
        root=ET.parse(destination).getroot();box=list(map(float,root.attrib['viewBox'].split()))
        result[side]=dict(file=destination.name,viewbox=box)
    return result

def inspect_board(source,folder,emit):
    from pcb_simulator.odb_preview import write_net_plots
    started=time.perf_counter()
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    emit('reading','Reading real net names, references, pad numbers and identities.')
    board,_,_,_=inventory(source)
    metadata_done=time.perf_counter()
    emit('plotting','Exporting all board copper and net identities in one KiCad pass.')
    run_cli(['pcb','export','odb','--compression','none','--precision','6','--units','mm','--output',folder/'odb',source],folder)
    export_done=time.perf_counter()
    emit('colouring',f"Preparing both copper views for all {len(board['nets'])} nets together.")
    write_net_plots(folder/'odb',folder,board)
    finished=time.perf_counter()
    board['import_timings']=dict(metadata_seconds=round(metadata_done-started,3),export_seconds=round(export_done-metadata_done,3),colour_seconds=round(finished-export_done,3),total_seconds=round(finished-started,3),kicad_exports=1)
    (folder/'board.json').write_text(json.dumps(board,indent=2),encoding='utf-8')
    return dict(board_file='board.json')

def filtered_board(source,target,net):
    board,tree,text,nets=inventory(source)
    if net not in {n['name'] for n in board['nets']}:raise ValueError('Choose a net from this board.')
    cuts=[]
    def scan(node):
        for child in node.children():
            is_copper_graphic=child.head.startswith(('gr_','fp_')) and any(v.endswith('.Cu') for v in child.values('layer'))
            copper=child.head in ['pad','segment','arc','via','zone'] or is_copper_graphic
            if copper and net_of(child,nets)!=net:cuts.append((child.start,child.end))
            else:scan(child)
    scan(tree)
    for start,end in sorted(cuts,reverse=True):text=text[:start]+text[end:]
    Path(target).write_text(text,encoding='utf-8')
    return [p for p in board['pads'] if p['net']==net]

def select_net(source,folder,net,emit):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    pads=filtered_board(source,folder/'selected.kicad_pcb',net)
    emit('highlighting',f'Plotting selected net {net} on both sides.')
    key=hashlib.sha256(net.encode()).hexdigest()[:32]
    cached=Path(source).parent/'nets'/key
    if (cached/'top.svg').exists() and (cached/'bottom.svg').exists():
        shutil.copytree(cached,folder/'highlight',dirs_exist_ok=True)
        plot_info={side:dict(file=side+'.svg',viewbox=list(map(float,ET.parse(cached/(side+'.svg')).getroot().attrib['viewBox'].split()))) for side in ['top','bottom']}
    else:plot_info=plots(folder/'selected.kicad_pcb',folder/'highlight')
    result=dict(net=net,pads=pads,plots=plot_info)
    (folder/'selection.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

def _geometry_preview(gmsh,folder,net,terminals,emit):
    """Tessellate the imported XAO, retaining named electrode faces as overlays.

    Coordinates use the existing preview encoding: little-endian float32 XYZ,
    centered in millimetres, and little-endian uint32 local triangle indices.
    This is a surface display mesh, not a simulation volume mesh.
    """
    import base64
    import numpy as np
    volumes=gmsh.model.getEntities(3)
    if not volumes:raise ValueError('KiCad exported no solid copper volumes for this net.')
    boxes=np.asarray([gmsh.model.getBoundingBox(d,t) for d,t in volumes],dtype=float)
    bounds=np.r_[boxes[:,:3].min(axis=0),boxes[:,3:].max(axis=0)]
    center=(bounds[:3]+bounds[3:])/2
    size=max(float(np.max(bounds[3:]-bounds[:3]))/30,.05)
    gmsh.option.setNumber('Mesh.MeshSizeMax',size)
    gmsh.option.setNumber('Mesh.MeshSizeMin',.05)
    gmsh.option.setNumber('Mesh.MeshSizeFromCurvature',12)
    gmsh.option.setNumber('Mesh.MeshSizeFromPoints',0)
    gmsh.option.setNumber('Mesh.MeshSizeExtendFromBoundary',0)
    gmsh.option.setNumber('Mesh.ElementOrder',1)
    gmsh.option.setNumber('Mesh.RecombineAll',0)
    emit('previewing',f'Tessellating {len(volumes)} copper solids and {len(terminals)} named terminals for 3D review.')
    gmsh.model.mesh.generate(2)
    tags,xyz,_=gmsh.model.mesh.getNodes()
    order=np.argsort(tags);tags=np.asarray(tags)[order];xyz=np.asarray(xyz).reshape(-1,3)[order]
    def body(faces,**metadata):
        chunks=[]
        for face in sorted(set(map(int,faces))):
            for typ,_,conn in zip(*gmsh.model.mesh.getElements(2,face)):
                if typ!=2:raise ValueError('Expected first-order triangular preview surfaces.')
                chunks.append(np.asarray(conn,dtype=np.uint64).reshape(-1,3))
        if not chunks:raise ValueError('An exported copper surface has no preview triangles.')
        node_tags=np.concatenate(chunks)
        nodes,local=np.unique(node_tags,return_inverse=True)
        indices=np.searchsorted(tags,nodes)
        if np.any(indices>=len(tags)) or not np.array_equal(tags[indices],nodes):raise ValueError('Preview surface refers to missing mesh nodes.')
        points=xyz[indices]
        return dict(**metadata,boundary_faces=sorted(set(map(int,faces))),
                    bounds_mm=np.r_[points.min(axis=0),points.max(axis=0)].tolist(),
                    vertices_b64=base64.b64encode(np.asarray(points-center,dtype='<f4').tobytes()).decode('ascii'),
                    triangles_b64=base64.b64encode(np.asarray(local,dtype='<u4').tobytes()).decode('ascii'))
    bodies=[]
    for _,tag in volumes:
        faces=[abs(t) for d,t in gmsh.model.getBoundary([(3,tag)],oriented=False) if d==2]
        name=gmsh.model.getEntityName(3,tag) or f'{net} · Copper {tag}'
        bodies.append(body(faces,tag=int(tag),name=name,kind='copper',role='copper'))
    for index,terminal in enumerate(terminals):
        faces=[face for boundary in terminal['boundaries'].values() for face in boundary['faces']]
        bodies.append(body(faces,tag=-(index+1),name=terminal['label'],kind='electrode',role=terminal['role'],pad_id=terminal['pad_id']))
    result=dict(kind='kicad_geometry',net=net,center=center.tolist(),bounds_mm=bounds.tolist(),
                geometry_units='mm',surface_preview_only=True,bodies=bodies,terminals=terminals)
    (Path(folder)/'preview.json').write_text(json.dumps(result,separators=(',',':')),encoding='utf-8')
    return result

def prepare(source,folder,net,input_ids,output_ids,emit):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    board,_,_,_=inventory(source)
    pads={p['id']:p for p in board['pads'] if p['net']==net}
    if not input_ids or not output_ids:raise ValueError('Select an input pad and an output pad.')
    if set(input_ids)&set(output_ids):raise ValueError('One pad cannot be both input and output.')
    if not (set(input_ids)|set(output_ids))<=set(pads):raise ValueError('A selected terminal does not belong to this net.')
    filtered_board(source,folder/'selected.kicad_pcb',net)
    emit('exporting','Exporting selected copper, inner layers and vias to named XAO geometry.')
    geometry=folder/'copper.xao'
    run_cli(['pcb','export','xao','--force','--no-board-body','--no-components','--include-pads','--include-tracks','--include-zones','--include-inner-copper','--output',geometry,folder/'selected.kicad_pcb'],folder)
    import gmsh
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal',0)
        gmsh.option.setString('Geometry.OCCTargetUnit','MM')
        gmsh.open(str(geometry))
        groups={gmsh.model.getPhysicalName(d,t):dict(dimension=d,tag=t,faces=list(map(int,gmsh.model.getEntitiesForPhysicalGroup(d,t)))) for d,t in gmsh.model.getPhysicalGroups(2)}
        terminals=[]
        for role,ids in [('input',input_ids),('output',output_ids)]:
            for uid in ids:
                p=pads[uid]
                if sum(q['reference']==p['reference'] and q['number']==p['number'] for q in pads.values())!=1:raise ValueError('Repeated pad number in one footprint needs mapping validation in the full integration.')
                names=[f'Pad_{side}_{p["reference"]}_{p["number"]}_{net.rsplit("/",1)[-1]}' for side in ['F','B']]
                found={name:groups[name] for name in names if name in groups}
                if not found:raise ValueError(f'KiCad exported no named electrode for {p["label"]}.')
                terminals.append(dict(pad_id=uid,label=p['label'],reference=p['reference'],number=p['number'],role=role,net=net,boundaries=found))
        _geometry_preview(gmsh,folder,net,terminals,emit)
        result=dict(stage='geometry_ready',prototype=True,solver_connected=False,net=net,source_sha256=board['sha256'],volumes=len(gmsh.model.getEntities(3)),named_surface_groups=len(groups),terminals=terminals,geometry='copper.xao',preview='preview.json',message='Real net geometry, 3D surface preview and named electrode surfaces prepared. FEM launch is the next integration stage.')
    finally:gmsh.finalize()
    (folder/'handoff.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
