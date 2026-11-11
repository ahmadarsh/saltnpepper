"""STEP import, exact CAD partitioning, conformal meshing and copper FEM.

Run in a dedicated worker process: Gmsh owns process-global state.
"""
import base64
import csv
import hashlib
import json
import math
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The bundled Gmsh SDK contains a Windows DLL; use native packages elsewhere.
if sys.platform == 'win32':
    sys.path.append(str(ROOT / '.python_deps'))
sys.path.insert(0, str(ROOT))
import numpy as np
import gmsh
from simulation.solve_3v3_thermal import solve_folder

DEFAULTS = dict(voltage_V=3.3, current_A=2., ambient_C=30., allowable_rise_C=45.,
    conductivity_20_S_m=58e6, alpha_per_K=.00393, thermal_k_W_mK=400.,
    convection_h_W_m2K=5., analysis_mode='electrothermal', mesh_size_mm=1.,
    refine=True, refinement_factor=.6, cooling_mode='outer_faces', outer_band_fraction=.05,
    input_face='auto', output_face='auto')


def _save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def _start(source):
    if not source.is_file():raise ValueError(f'STEP source does not exist: {source.name}')
    gmsh.initialize()
    gmsh.option.setNumber('General.Terminal', 0)
    gmsh.option.setNumber('General.NumThreads', 4)
    # STEP carries its own length unit. Normalize before CAD import so geometry,
    # mesh sizes, preview coordinates and the FEM mm-to-m conversion agree.
    gmsh.option.setString('Geometry.OCCTargetUnit', 'MM')
    gmsh.logger.start()
    gmsh.open(str(source))
    gmsh.model.occ.synchronize()
    if not gmsh.model.getEntities(3):
        raise ValueError('The STEP file has no solid volumes. Export solid copper bodies, including pad/via contacts.')


def _finish(folder):
    if gmsh.isInitialized():
        (folder/'gmsh.log').write_text('\n'.join(gmsh.logger.get()), encoding='utf-8')
        gmsh.logger.stop()
        gmsh.finalize()


def _bounds(volumes):
    bounds=np.array([gmsh.model.getBoundingBox(d,t) for d,t in volumes])
    return np.r_[bounds[:,:3].min(axis=0),bounds[:,3:].max(axis=0)]


def _inventory(source):
    volumes=gmsh.model.getEntities(3)
    labels=[gmsh.model.getEntityName(3,t) for _,t in volumes]
    bases=[s.rsplit('/',1)[-1].strip() or f'Solid_{t}' for s,(_,t) in zip(labels,volumes)]
    multiplicity=Counter(bases);used=set();reserved=set(bases);seen=Counter();solids=[]
    for (dim,tag),label,base in zip(volumes,labels,bases):
        count=seen[base];seen[base]+=1
        name=base if count==0 else f'{base}{count:03}'
        # Keep real unique STEP names even when they resemble generated suffixes.
        while name in used or (count and name in reserved):
            count+=1;name=f'{base}{count:03}'
        used.add(name)
        low=base.lower()
        kind='pad' if 'pad' in low else 'via' if 'via' in low else 'copper' if any(s in low for s in ('copper','track','zone','trace')) else 'solid'
        solids.append(dict(tag=int(tag),name=name,kind=kind,step_label=label,
            name_inferred=bool(multiplicity[base]>1 or not label),
            centroid_mm=list(gmsh.model.occ.getCenterOfMass(dim,tag)),bounds_mm=list(gmsh.model.getBoundingBox(dim,tag)),
            volume_mm3=float(gmsh.model.occ.getMass(dim,tag))))
    bounds=_bounds(volumes)
    return dict(source=source.name,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        solids=solids,counts=dict(Counter(s['kind'] for s in solids)),solid_count=len(solids),bounds_mm=bounds.tolist(),
        center=((bounds[:3]+bounds[3:])/2).tolist(),geometry_units='mm',
        naming_note='Unique STEP body names are preserved. Repeated names receive ordered 001, 002, ... suffixes; inferred names are marked. Solid tags are stable for this source import. STEP length units are converted to millimeters during import.')


def _triangles(faces,tags):
    chunks=[]
    for face in faces:
        for typ,_,conn in zip(*gmsh.model.mesh.getElements(2,int(face))):
            if typ!=2:raise ValueError('Expected first-order triangular boundary elements')
            chunks.append(np.searchsorted(tags,conn).reshape(-1,3))
    return np.concatenate(chunks) if chunks else np.empty((0,3),dtype=np.int64)


def inspect_model(source, output_dir, emit):
    source=Path(source);folder=Path(output_dir);folder.mkdir(parents=True,exist_ok=True)
    emit('importing','Importing STEP solid bodies and names')
    try:
        _start(source);inventory=_inventory(source);_save(folder/'inventory.json',inventory)
        bounds=np.asarray(inventory['bounds_mm']);center=np.asarray(inventory['center'])
        # Use OCC's display triangulation instead of an isotropic FE surface
        # mesh: round barrel walls need angular resolution, not dense axial
        # subdivisions. Chord tolerance is absolute mm, independent of board
        # extent, so small holes stay smooth when imported with large copper.
        angular_deflection=math.pi/16  # about 64 segments per full circle
        linear_deflection=.002
        gmsh.option.setNumber('Mesh.StlAngularDeflection',angular_deflection)
        gmsh.option.setNumber('Mesh.StlLinearDeflectionRelative',0)
        gmsh.option.setNumber('Mesh.StlLinearDeflection',linear_deflection)
        gmsh.option.setNumber('Mesh.StlOneSolidPerSurface',2)
        gmsh.option.setNumber('Mesh.Binary',0)
        # These temporary display groups affect neither the source CAD file nor
        # later simulation meshing, which reimports it in a fresh Gmsh session.
        for dimension,tag in gmsh.model.getPhysicalGroups():
            name=gmsh.model.getPhysicalName(dimension,tag)
            if name:gmsh.model.removePhysicalName(name)
        gmsh.model.removePhysicalGroups()
        prefix='Salt_Pepper_Preview_Body_'
        for row in inventory['solids']:
            faces=[abs(t) for d,t in gmsh.model.getBoundary([(3,row['tag'])],oriented=False) if d==2]
            gmsh.model.addPhysicalGroup(2,faces,name=prefix+str(row['tag']))
        emit('importing',f'Tessellating {len(inventory["solids"])} solid bodies for selection')
        display_stl=folder/'preview-surfaces.stl'
        gmsh.write(str(display_stl))
        raw={row['tag']:[] for row in inventory['solids']};current=None
        try:
            with display_stl.open(encoding='ascii') as stream:
                for line in stream:
                    fields=line.split()
                    if not fields:continue
                    if fields[0]=='solid':
                        name=' '.join(fields[1:])
                        current=int(name[len(prefix):]) if name.startswith(prefix) else None
                        if current is not None and current not in raw:raise ValueError('Unexpected CAD preview body tag.')
                    elif fields[0]=='endsolid':current=None
                    elif fields[0]=='vertex' and current is not None:
                        if len(fields)!=4:raise ValueError('Malformed CAD preview triangle.')
                        raw[current].append(tuple(map(float,fields[1:])))
        finally:display_stl.unlink(missing_ok=True)
        bodies=[]
        for row in inventory['solids']:
            points=np.asarray(raw[row['tag']],dtype=float)
            if not len(points) or len(points)%3 or not np.all(np.isfinite(points)):
                raise ValueError('CAD preview contains missing or invalid surface triangles.')
            xyz,local=np.unique(points,axis=0,return_inverse=True)
            bodies.append(dict(tag=row['tag'],name=row['name'],kind=row['kind'],bounds_mm=row['bounds_mm'],
                vertices_b64=base64.b64encode(np.asarray(xyz-center,dtype='<f4').tobytes()).decode('ascii'),
                triangles_b64=base64.b64encode(np.asarray(local,dtype='<u4').tobytes()).decode('ascii')))
        _save(folder/'preview.json',dict(center=center.tolist(),bounds_mm=bounds.tolist(),bodies=bodies,
            tessellation=dict(method='OpenCASCADE display surfaces',angular_deflection_rad=angular_deflection,linear_deflection_mm=linear_deflection)))
        emit('importing','CAD inventory and selectable surface preview ready',solid_count=len(bodies))
        return inventory
    finally:_finish(folder)


def _parameters(parameters):
    p=dict(DEFAULTS);p.update(parameters)
    for key in ('voltage_V','current_A','ambient_C','allowable_rise_C','conductivity_20_S_m','alpha_per_K',
                'thermal_k_W_mK','convection_h_W_m2K','mesh_size_mm','refinement_factor','outer_band_fraction'):
        p[key]=float(p[key])
        if not math.isfinite(p[key]):raise ValueError(f'{key} must be finite')
    for key in ('current_A','conductivity_20_S_m','thermal_k_W_mK','convection_h_W_m2K','mesh_size_mm'):
        if p[key]<=0:raise ValueError(f'{key} must be greater than zero')
    if p['allowable_rise_C']<0 or p['alpha_per_K']<0:raise ValueError('Allowable rise and temperature coefficient cannot be negative')
    if not 0<p['refinement_factor']<1:raise ValueError('refinement_factor must be between zero and one')
    if not 0<p['outer_band_fraction']<=.5:raise ValueError('outer_band_fraction must be between zero and 0.5')
    for key,allowed in [('analysis_mode',('electrothermal','electrical')),('cooling_mode',('outer_faces','all_exterior')),
                        ('input_face',('auto','top','bottom')),('output_face',('auto','top','bottom'))]:
        if p[key] not in allowed:raise ValueError(f'Invalid {key}: {p[key]}')
    return p


def _prepare(inventory, input_tags, output_tags, p, folder, emit):
    rows=inventory['solids'];by_tag={int(r['tag']):r for r in rows}
    selected=set(input_tags+output_tags)
    if not input_tags or not output_tags:raise ValueError('Choose at least one input and one output pad')
    if set(input_tags)&set(output_tags):raise ValueError('Input and output pad selections must be disjoint')
    if not selected<=set(by_tag):raise ValueError('Selected solid tags do not belong to this STEP inventory; import it again')
    source_volumes=gmsh.model.getEntities(3);bounds=_bounds(source_volumes)
    input_tags=sorted({by_tag[t].get('kicad_pad_tag',t) for t in input_tags})
    output_tags=sorted({by_tag[t].get('kicad_pad_tag',t) for t in output_tags})
    if set(input_tags)&set(output_tags):raise ValueError('Input and output selections refer to the same pad')
    selected=set(input_tags+output_tags)
    pad_rows=[r for r in rows if r['tag'] in selected]
    members=[list(r.get('pad_volume_tags',[r['tag']])) for r in pad_rows]
    selected_volumes={tag for group in members for tag in group}
    if not selected_volumes<=set(by_tag):raise ValueError('A selected pad refers to missing copper solids; import it again')
    if sum(map(len,members))!=len(selected_volumes):raise ValueError('Selected pads share copper solids')
    nonports=[(3,r['tag']) for r in rows if r['tag'] not in selected_volumes]
    pads=[(3,tag) for group in members for tag in group]
    emit('fusing',f'Uniting {len(nonports)} conductor solids while preserving {len(pad_rows)} selected pads ({len(pads)} copper pieces)')
    if len(nonports)>1:conductor,_=gmsh.model.occ.fuse(nonports[:1],nonports[1:])
    else:conductor=nonports
    gmsh.model.occ.synchronize()
    if conductor:
        _,mapping=gmsh.model.occ.fragment(conductor,pads)
        pad_mapping=mapping[len(conductor):]
    elif len(pads)>1:
        _,pad_mapping=gmsh.model.occ.fragment(pads[:1],pads[1:])
    else:raise ValueError('There are too few disjoint solids for the requested electrodes')
    gmsh.model.occ.synchronize()
    allvols=gmsh.model.getEntities(3)
    external=gmsh.model.getBoundary(allvols,combined=True,oriented=True)
    external_faces={abs(t) for d,t in external if d==2}
    board_mid=(bounds[2]+bounds[5])/2;ports=[]
    tolerance=max(1e-5,float(np.max(bounds[3:]-bounds[:3]))*1e-8)
    # Boolean maps are per physical solid; reassemble them into logical pads.
    offset=0;logical_mapping=[]
    for group in members:
        logical_mapping.append([child for result in pad_mapping[offset:offset+len(group)] for child in result])
        offset+=len(group)
    for row,children in zip(pad_rows,logical_mapping):
        volume_tags=sorted({t for d,t in children if d==3})
        role='input' if row['tag'] in input_tags else 'output'
        pad_bounds=row.get('pad_bounds_mm',row['bounds_mm'])
        pad_centroid=row.get('pad_centroid_mm',row['centroid_mm'])
        side=p[role+'_face']
        if side=='auto':side='top' if pad_centroid[2]>=board_mid else 'bottom'
        target=pad_bounds[5 if side=='top' else 2]
        faces=[]
        for dim,face in gmsh.model.getBoundary([(3,t) for t in volume_tags],combined=True,oriented=False):
            face=abs(face);bb=gmsh.model.getBoundingBox(2,face)
            if face in external_faces and abs(bb[2]-target)<tolerance and abs(bb[5]-bb[2])<tolerance:faces.append(face)
        if not faces:raise ValueError(f'Pad {row["name"]} has no exposed planar {side} electrode face. Try the other face or select another pad; model orientation must use Z through the board.')
        ports.append(dict(name=row['name'],role=role,original_solid=row['tag'],original_solids=list(row.get('pad_volume_tags',[row['tag']])),bounds_mm=pad_bounds,
            centroid_mm=pad_centroid,face=side,volume_tags=volume_tags,surface_tags=sorted(set(faces))))
    pad_volume_tags={tag for port in ports for tag in port['volume_tags']}
    conductor_tags=[t for _,t in allvols if t not in pad_volume_tags]
    if conductor_tags:gmsh.model.addPhysicalGroup(3,conductor_tags,1,'Copper_Conductor')
    for i,port in enumerate(ports):
        port['volume_group']=1000+i;port['boundary_group']=2000+i
        gmsh.model.addPhysicalGroup(3,port['volume_tags'],port['volume_group'],port['name'])
        gmsh.model.addPhysicalGroup(2,port['surface_tags'],port['boundary_group'],port['name']+'_Electrode')
    for role,name,tag in [('input','In_Port',101),('output','Out_Port',102)]:
        gmsh.model.addPhysicalGroup(2,sorted({f for port in ports if port['role']==role for f in port['surface_tags']}),tag,name)
    cooling=[];zband=(bounds[5]-bounds[2])*p['outer_band_fraction']
    for dim,signed in external:
        if dim!=2:continue
        face=abs(signed)
        if p['cooling_mode']=='all_exterior':cooling.append(face);continue
        center=gmsh.model.occ.getCenterOfMass(2,face)
        low,high=gmsh.model.getParametrizationBounds(2,face)
        # Gmsh's OCC getNormal already applies the oriented CAD face normal.
        # Multiplying by getBoundary's signed tag flips bottom faces inward.
        normal=np.asarray(gmsh.model.getNormal(face,(np.asarray(low)+np.asarray(high))/2))
        if (normal[2]>.8 and center[2]>=bounds[5]-zband-tolerance) or (normal[2]<-.8 and center[2]<=bounds[2]+zband+tolerance):cooling.append(face)
    gmsh.model.addPhysicalGroup(2,sorted(external_faces),103,'Exterior_Copper_Surface')
    if cooling:gmsh.model.addPhysicalGroup(2,sorted(set(cooling)),104,'Approximate_Convection')
    definition=dict(ports=ports,external_surface_tags=sorted(external_faces),convection_surface_tags=sorted(set(cooling)),
        source_solid_count=len(rows),final_partition_volumes=len(allvols),bounds_mm=bounds.tolist(),
        sum_source_volume_mm3=sum(r['volume_mm3'] for r in rows),union_partition_volume_mm3=sum(gmsh.model.occ.getMass(d,t) for d,t in allvols),
        geometry_note='Exact 3D Boolean union and fragmentation. No flattening, resizing or artificial gap bridges.',
        cooling_note='Approximate convection using exposed outward Z faces near total Z extrema.' if p['cooling_mode']=='outer_faces' else 'Approximation: all exterior copper receives convection, including surfaces that may be buried in a real PCB.',parameters=p)
    _save(folder/'model_definition.json',definition)
    _save(folder/'ports.json',dict(ports=ports,units='mm'))
    gmsh.write(str(folder/'fused.step'))
    return definition


def _mesh(definition,size,folder,p,emit):
    folder.mkdir(parents=True,exist_ok=True)
    # Preserve geometric port definitions before attempting a possibly failing mesh.
    _save(folder/'ports.json',dict(ports=definition['ports'],units='mm',mesh_status='pending'))
    gmsh.model.mesh.clear()
    for key,value in {'Mesh.MeshSizeMax':size,'Mesh.MeshSizeMin':size/40,'Mesh.MeshSizeFromCurvature':24,
        'Mesh.Algorithm3D':1,'Mesh.AngleToleranceFacetOverlap':.001,'Mesh.Optimize':1,'Mesh.ElementOrder':1,
        'Mesh.MshFileVersion':4.1,'Mesh.Binary':1,'Mesh.SaveAll':1}.items():gmsh.option.setNumber(key,value)
    emit('meshing',f'Generating surface and tetrahedral meshes at {size:g} mm')
    gmsh.model.mesh.generate(2);gmsh.write(str(folder/'surface.msh'))
    gmsh.model.mesh.generate(3);gmsh.write(str(folder/'volume.msh'))
    tags,xyz,_=gmsh.model.mesh.getNodes();order=np.argsort(tags);tags=tags[order];xyz=xyz.reshape(-1,3)[order]
    tets=[];tet_tags=[];regions=[]
    for _,v in gmsh.model.getEntities(3):
        for typ,ids,conn in zip(*gmsh.model.mesh.getElements(3,v)):
            if typ!=4:raise ValueError('Expected first-order tetrahedra')
            tets.append(np.searchsorted(tags,conn).reshape(-1,4));tet_tags.extend(ids);regions.extend([v]*len(ids))
    if not tets:raise ValueError('No tetrahedral elements generated; check that the STEP contains valid closed solids')
    tets=np.concatenate(tets);ports=[]
    for i,port in enumerate(definition['ports']):
        entry=dict(port);ids,_=gmsh.model.mesh.getNodesForPhysicalGroup(2,port['boundary_group'])
        entry['node_tags']=sorted(map(int,ids));entry['node_indices']=np.searchsorted(tags,entry['node_tags']).tolist();ports.append(entry)
        safe=re.sub(r'[^A-Za-z0-9_.-]','_',port['name'])[:100]
        np.savetxt(folder/f'port_{i+1:03}_{safe}_nodes.csv',np.column_stack([entry['node_tags'],xyz[entry['node_indices']]]),
            delimiter=',',header='gmsh_node_tag,x_mm,y_mm,z_mm',comments='',fmt=['%d','%.12g','%.12g','%.12g'])
    _save(folder/'ports.json',dict(ports=ports,units='mm',input_voltage_V=p['voltage_V'],total_output_current_A=p['current_A'],mesh_status='complete'))
    surface=_triangles(definition['external_surface_tags'],tags);convection=_triangles(definition['convection_surface_tags'],tags)
    src=np.unique(np.concatenate([port['node_indices'] for port in ports if port['role']=='input'])).astype(np.int64)
    sink=np.unique(np.concatenate([port['node_indices'] for port in ports if port['role']=='output'])).astype(np.int64)
    np.savez_compressed(folder/'solver_mesh.npz',node_tags=tags,nodes_mm=xyz,tetrahedra=tets,tetrahedron_tags=np.asarray(tet_tags),
        region_tags=np.asarray(regions),external_triangles=surface,convection_triangles=convection,input_nodes=src,output_nodes=sink)
    quality=gmsh.model.mesh.getElementQualities(tet_tags,'minSICN')
    result=dict(nodes=len(tags),tetrahedra=len(tets),external_triangles=len(surface),convection_triangles=len(convection),
        target_max_size_mm=size,minimum_scaled_jacobian=float(np.min(quality)),nonpositive_quality_elements=int(np.sum(quality<=0)),
        input_nodes=len(src),output_nodes=len(sink))
    _save(folder/'mesh_report.json',result)
    if result['nonpositive_quality_elements']:raise ValueError('Mesh contains invalid tetrahedra; choose another mesh size or repair the CAD')
    return result


def run_simulation(source, inventory, output_dir, input_tags, output_tags, parameters, emit):
    source=Path(source);folder=Path(output_dir);folder.mkdir(parents=True,exist_ok=True)
    p=_parameters(parameters);input_tags=sorted(set(map(int,input_tags)));output_tags=sorted(set(map(int,output_tags)))
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if inventory.get('source_sha256') and digest!=inventory['source_sha256']:raise ValueError('STEP source changed since inspection. Import it again before selecting ports.')
    copied=folder/('source.xao' if source.suffix.lower()=='.xao' else 'source.step')
    if source.resolve()!=copied.resolve():shutil.copy2(source,copied)
    _save(folder/'config.json',dict(source=source.name,source_sha256=digest,input_tags=input_tags,output_tags=output_tags,parameters=p))
    _save(folder/'inventory.json',inventory)
    try:
        emit('importing','Reimporting the saved source for physical 3D analysis');_start(source)
        actual={t for _,t in gmsh.model.getEntities(3)}
        if actual!={r['tag'] for r in inventory['solids']}:raise ValueError('Inventory does not match imported solid tags; inspect this file again')
        imported_bounds=_bounds(gmsh.model.getEntities(3))
        if not np.allclose(imported_bounds,inventory['bounds_mm'],rtol=1e-8,atol=1e-5):
            raise ValueError('The imported dimensions differ from the saved inventory, possibly due to STEP unit normalization. Import the model again before selecting ports.')
        definition=_prepare(inventory,input_tags,output_tags,p,folder,emit)
        sizes=[p['mesh_size_mm']]
        if p['refine']:sizes.append(sizes[0]*p['refinement_factor'])
        runs=[];report=None
        for i,size in enumerate(sizes):
            meshfolder=folder/f'mesh_{i+1:02}_{size:.6g}mm'
            try:
                mesh_info=_mesh(definition,size,meshfolder,p,emit)
                emit('solving',f'Solving mesh {i+1}/{len(sizes)}: {mesh_info["tetrahedra"]:,} tetrahedra')
                report=solve_folder(meshfolder,p,emit)
                report['mesh']=mesh_info;report['source']=source.name;report['source_sha256']=digest
                report['model']=definition
                _save(meshfolder/'report.json',report)
                runs.append(dict(folder=meshfolder.name,status='solved',mesh=mesh_info,resistance_ohm=report['resistance_ohm'],
                    maximum_temperature_C=report['maximum_temperature_C'],total_joule_power_W=report['total_joule_power_W']))
            except Exception as exc:
                _save(meshfolder/'failure.json',dict(error=str(exc),target_max_size_mm=size))
                runs.append(dict(folder=meshfolder.name,status='failed',error=str(exc)))
                _save(folder/'refinement.json',dict(runs=runs))
                raise
        refinement=dict(enabled=bool(p['refine']),runs=runs,relative_resistance_change=None,maximum_temperature_change_C=None,
            note='Two mesh sizes are a sensitivity check; they do not prove mesh convergence or accuracy of sharp-corner peaks.')
        if len(runs)>1:
            refinement['relative_resistance_change']=abs(runs[-1]['resistance_ohm']-runs[-2]['resistance_ohm'])/runs[-1]['resistance_ohm']
            if p['analysis_mode']=='electrothermal':refinement['maximum_temperature_change_C']=abs(runs[-1]['maximum_temperature_C']-runs[-2]['maximum_temperature_C'])
        report['refinement']=refinement;report['parameters']=p
        report['artifacts']=dict(fields='fields.npz',fused_step='fused.step',source_step=copied.name,latest_mesh=meshfolder.name,
            ports=f'{meshfolder.name}/ports.json',volume_mesh=f'{meshfolder.name}/volume.msh',surface_mesh=f'{meshfolder.name}/surface.msh')
        emit('postprocessing','Saving final fields, conservation checks and refinement comparison')
        shutil.copy2(meshfolder/'fields.npz',folder/'fields.npz')
        shutil.copy2(meshfolder/'ports.json',folder/'ports.json')
        _save(folder/'refinement.json',refinement);_save(folder/'report.json',report)
        return report
    finally:_finish(folder)
