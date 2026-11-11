"""Promote named KiCad XAO copper into the existing Geometry workbench.

Pad identity is established solely by named XAO faces and their CAD volume
adjacency. A through-hole pad can own several solids; shared ownership between
different pads is rejected instead of guessed.
"""
from collections import Counter
import json
from pathlib import Path
import shutil


def promote_to_workbench(source,folder,board,net,terminals,emit):
    from pcb_simulator import engine
    import gmsh
    source=Path(source);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    destination=folder/'source.xao'
    if source.resolve()!=destination.resolve():shutil.copyfile(source,destination)
    pads=[p for p in board['pads'] if p['net']==net]
    if not pads:raise ValueError('The selected net has no named copper pads.')
    identities=[(p['reference'],p['number']) for p in pads]
    if len(set(identities))!=len(identities):raise ValueError('Repeated pad numbers in a footprint cannot be mapped uniquely to Geometry mode.')
    inventory=engine.inspect_model(destination,folder,emit)
    emit('mapping','Mapping real KiCad pad names to copper solids using named surface adjacency.')
    gmsh.initialize()
    mapping={};owners={}
    try:
        gmsh.option.setNumber('General.Terminal',0)
        gmsh.option.setString('Geometry.OCCTargetUnit','MM')
        gmsh.open(str(destination));gmsh.model.occ.synchronize()
        groups={gmsh.model.getPhysicalName(d,t):dict(dimension=int(d),tag=int(t),faces=list(map(int,gmsh.model.getEntitiesForPhysicalGroup(d,t)))) for d,t in gmsh.model.getPhysicalGroups(2)}
        for pad in pads:
            names=[f'Pad_{side}_{pad["reference"]}_{pad["number"]}_{net.rsplit("/",1)[-1]}' for side in ['F','B']]
            boundaries={name:groups[name] for name in names if name in groups}
            if not boundaries:raise ValueError(f'No named XAO electrode surfaces were found for {pad["label"]}.')
            faces=sorted({face for group in boundaries.values() for face in group['faces']})
            volumes=set()
            for face in faces:
                adjacent=list(map(int,gmsh.model.getAdjacencies(2,face)[0]))
                if len(adjacent)!=1:raise ValueError(f'{pad["label"]} has a named surface touching {len(adjacent)} solids; a unique pad volume is required.')
                volumes.update(adjacent)
            if not volumes:raise ValueError(f'No copper solids were found for {pad["label"]}.')
            volume_tags=sorted(volumes);tag=volume_tags[0]
            for member in volume_tags:
                if member in owners:raise ValueError(f'{pad["label"]} and {owners[member]} share a copper solid; pad boundaries cannot be assigned independently.')
                owners[member]=pad['label']
            mapping[pad['id']]=dict(tag=tag,volume_tags=volume_tags,pad_id=pad['id'],name=pad['label'],reference=pad['reference'],number=pad['number'],net=net,boundaries=boundaries,electrode_faces=faces)
    finally:gmsh.finalize()
    by_tag={tag:pad for pad in mapping.values() for tag in pad['volume_tags']}
    solid_tags={row['tag'] for row in inventory['solids']}
    if not set(by_tag)<=solid_tags:raise ValueError('Named KiCad pad solids changed identity while preparing the workbench.')
    defaults={'input':[],'output':[]};seen=set()
    for terminal in terminals:
        uid=terminal.get('pad_id');role=terminal.get('role')
        if uid not in mapping or role not in defaults:raise ValueError('A selected terminal has no matching KiCad pad solid.')
        if uid in seen:raise ValueError('A pad cannot be assigned as more than one terminal.')
        seen.add(uid);defaults[role].append(mapping[uid]['tag'])
    if not defaults['input'] or not defaults['output']:raise ValueError('Choose an input and output before opening Geometry mode.')
    physical_rows={row['tag']:row for row in inventory['solids']}
    for pad in mapping.values():
        members=[physical_rows[tag] for tag in pad['volume_tags']]
        pad['bounds_mm']=[min(row['bounds_mm'][axis] for row in members) for axis in range(3)]+[max(row['bounds_mm'][axis] for row in members) for axis in range(3,6)]
        mass=sum(row['volume_mm3'] for row in members)
        pad['centroid_mm']=[sum(row['centroid_mm'][axis]*row['volume_mm3'] for row in members)/mass for axis in range(3)]
    for row in inventory['solids']:
        if row['tag'] in by_tag:
            pad=by_tag[row['tag']]
            row.update(name=pad['name'],kind='pad',name_inferred=False,kicad_pad_id=pad['pad_id'],reference=pad['reference'],pad_number=pad['number'],net=net,electrode_faces=pad['electrode_faces'],electrode_boundaries=pad['boundaries'],
                       kicad_pad_tag=pad['tag'],kicad_pad_member=row['tag']!=pad['tag'],pad_volume_tags=pad['volume_tags'],pad_bounds_mm=pad['bounds_mm'],pad_centroid_mm=pad['centroid_mm'])
        else:row.update(net=net)
    inventory.update(source_kind='kicad_xao',net=net,kicad_pad_map=mapping,
                     naming_note='Real KiCad pad names are preserved using named XAO surfaces and exact CAD volume adjacency. Through-hole copper pieces are selected together as one pad. Copper geometry is retained in millimetres.',
                     pad_count=len(mapping),
                     default_input_tags=defaults['input'],default_output_tags=defaults['output'],
                     counts=dict(Counter(row['kind'] for row in inventory['solids'])))
    preview_path=folder/'preview.json';preview=json.loads(preview_path.read_text(encoding='utf-8'))
    rows={row['tag']:row for row in inventory['solids']}
    for body in preview['bodies']:
        row=rows[body['tag']];body.update(name=row['name'],kind=row['kind'],net=net)
        if body['tag'] in by_tag:
            pad=by_tag[body['tag']]
            body.update(source_volume_tag=body['tag'],tag=pad['tag'],kicad_pad_id=pad['pad_id'])
    preview.update(source_kind='kicad_xao',net=net)
    for path,value in [(folder/'inventory.json',inventory),(preview_path,preview)]:
        path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    emit('mapping','Named KiCad copper is ready in the Geometry workbench.',solid_count=inventory['solid_count'])
    return inventory
