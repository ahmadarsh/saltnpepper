"""Render net-coloured previews from one native KiCad ODB++ export.

Connectivity comes only from eda/data's zero-based LYR/FID C references.
Coordinates remain in the native step coordinate system, then Y is reversed
for KiCad's 2D board view. No geometric proximity/net guessing is performed.
Supported ODB++ feature records: P, L, A, S (OB/OS/OC/OE/SE contours).

Format reference: Siemens ODB++Design Format Specification 8.1 Update 4,
https://odbplusplus.com/wp-content/uploads/sites/2/2024/08/odb_spec_user.pdf
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from html import escape
import math
from pathlib import Path
import re

from .odb_symbols import symbol_svg, symbol_line_style


@dataclass
class Feature:
    polarity: str
    svg: str


def _number(value):
    result=float(value)
    if not math.isfinite(result):raise ValueError('ODB++ contains a non-finite coordinate.')
    return result


def _fmt(value):
    return format(value,'.10g')


def _units(text):
    match=re.search(r'^UNITS\s*=\s*(\w+)',text,re.M)
    units=match.group(1).upper() if match else 'MM'
    if units not in ('MM','INCH'):raise ValueError('Unsupported ODB++ units: '+units)
    return units,25.4 if units=='INCH' else 1.


def _arc(start,end,center,clockwise):
    if clockwise not in ('Y','N'):raise ValueError('Invalid ODB++ arc direction.')
    sx,sy=start;ex,ey=end;cx,cy=center
    radius=math.hypot(sx-cx,sy-cy)
    if radius<=0:raise ValueError('ODB++ arc has zero radius.')
    # Native exporters round centers independently from endpoints. Reject grossly
    # inconsistent arcs; retain the native start/end points and circular radius.
    if abs(radius-math.hypot(ex-cx,ey-cy))>max(.0003,radius*1e-4):
        raise ValueError('ODB++ arc endpoints do not share a circle.')
    sweep=0 if clockwise=='Y' else 1
    if math.hypot(ex-sx,ey-sy)<1e-10:
        opposite=(2*cx-sx,2*cy-sy)
        return f'A {_fmt(radius)} {_fmt(radius)} 0 0 {sweep} {_fmt(opposite[0])} {_fmt(opposite[1])} A {_fmt(radius)} {_fmt(radius)} 0 0 {sweep} {_fmt(ex)} {_fmt(ey)}'
    start_angle=math.atan2(sy-cy,sx-cx);end_angle=math.atan2(ey-cy,ex-cx)
    span=((start_angle-end_angle) if clockwise=='Y' else (end_angle-start_angle))%(2*math.pi)
    return f'A {_fmt(radius)} {_fmt(radius)} 0 {int(span>math.pi)} {sweep} {_fmt(ex)} {_fmt(ey)}'


def _orientation(tokens):
    mode=int(tokens[0])
    if mode in range(8):return (mode%4)*90,mode>=4
    if mode in (8,9) and len(tokens)>=2:return _number(tokens[1]),mode==9
    raise ValueError('Unsupported ODB++ pad orientation.')


def parse_features(text,custom_loader=None):
    """Return features in exact file order, preserving native zero-based IDs.

    Standard symbol dimensions are micrometres for MM feature files and mils
    for INCH files. Coordinates are converted to millimetres here.
    """
    units,factor=_units(text)
    symbols={}
    for raw in text.splitlines():
        line=raw.split(';',1)[0].strip()
        if line.startswith('$'):
            parts=line.split()
            if len(parts)!=2:raise ValueError('Invalid ODB++ symbol lookup record.')
            symbols[int(parts[0][1:])]=parts[1]
    records=[];contours=None;polygon=None;previous=None;declared=None;surface_polarity=None
    def xy(tokens):return tuple(_number(x)*factor for x in tokens)
    def symbol(index):
        try:return symbols[int(index)]
        except KeyError:raise ValueError('ODB++ feature refers to an undefined symbol.')
    for raw in text.splitlines():
        line=raw.split(';',1)[0].strip()
        if not line or line[0] in '#$@&' or line.startswith('UNITS'):continue
        fields=line.split();kind=fields[0]
        if kind=='F':declared=int(fields[1]);continue
        if kind=='S':
            if contours is not None:raise ValueError('Nested ODB++ surfaces are not supported.')
            contours=[];surface_polarity=fields[1];continue
        if kind=='OB':
            if contours is None or polygon is not None or fields[3] not in ('I','H'):raise ValueError('Invalid ODB++ surface contour.')
            previous=xy(fields[1:3]);polygon=[f'M {_fmt(previous[0])} {_fmt(previous[1])}'];continue
        if kind in ('OS','OC'):
            if polygon is None:raise ValueError('ODB++ contour segment outside a polygon.')
            end=xy(fields[1:3])
            polygon.append(f'L {_fmt(end[0])} {_fmt(end[1])}' if kind=='OS' else _arc(previous,end,xy(fields[3:5]),fields[5]))
            previous=end;continue
        if kind=='OE':
            if polygon is None:raise ValueError('Unbalanced ODB++ contour end.')
            contours.append(' '.join(polygon)+' Z');polygon=None;previous=None;continue
        if kind=='SE':
            if contours is None or polygon is not None:raise ValueError('Unbalanced ODB++ surface end.')
            records.append(Feature(surface_polarity,f'<path d="{" ".join(contours)}" fill="currentColor" fill-rule="evenodd" stroke="none"/>'))
            contours=None;continue
        if contours is not None:raise ValueError('Unexpected record inside an ODB++ surface: '+kind)
        if kind=='P':
            x,y=xy(fields[1:3]);name=symbol(fields[3]);polarity=fields[4];rotation,mirrored=_orientation(fields[6:])
            shape=symbol_svg(name,custom_loader=custom_loader,units=units)
            transform=f'translate({_fmt(x)} {_fmt(y)})'+(' scale(1 -1)' if mirrored else '')+f' rotate({_fmt(-rotation)})'
            records.append(Feature(polarity,f'<g transform="{transform}">{shape}</g>'))
        elif kind in ('L','A'):
            start,end=xy(fields[1:3]),xy(fields[3:5]);index=5 if kind=='L' else 7
            width,cap=symbol_line_style(symbol(fields[index]),units=units);polarity=fields[index+1]
            path=f'M {_fmt(start[0])} {_fmt(start[1])} '
            path+=f'L {_fmt(end[0])} {_fmt(end[1])}' if kind=='L' else _arc(start,end,xy(fields[5:7]),fields[10])
            records.append(Feature(polarity,f'<path d="{path}" fill="none" stroke="currentColor" stroke-width="{_fmt(width)}" stroke-linecap="{cap}"/>'))
        else:raise ValueError('Unsupported ODB++ feature record: '+kind)
    if contours is not None or polygon is not None:raise ValueError('Unclosed ODB++ surface.')
    if declared is not None and declared!=len(records):raise ValueError('ODB++ feature count does not match native feature IDs.')
    if any(record.polarity not in ('P','N') for record in records):raise ValueError('Invalid ODB++ feature polarity.')
    return records


def eda_mapping(text):
    """Map (native layer name, feature ID) to exact exported net name."""
    layers=None;net=None;mapping={}
    for raw in text.splitlines():
        line=raw.strip()
        if line.startswith('LYR '):layers=line.split()[1:]
        elif line.startswith('NET '):net=line[4:].split(';',1)[0].strip()
        elif line.startswith('FID '):
            fields=line.split()
            if len(fields)!=4:raise ValueError('Invalid ODB++ connectivity feature reference.')
            if fields[1]!='C':continue
            if layers is None or net is None:raise ValueError('ODB++ connectivity precedes its layer/net definition.')
            layer_id,feature_id=map(int,fields[2:4])
            if not 0<=layer_id<len(layers) or feature_id<0:raise ValueError('Invalid ODB++ connectivity feature ID.')
            key=(layers[layer_id].casefold(),feature_id)
            if key in mapping and mapping[key]!=net:raise ValueError('One ODB++ copper feature is assigned to multiple nets.')
            mapping[key]=net
    if layers is None:raise ValueError('ODB++ EDA layer table is missing.')
    return mapping


def _matrix(text):
    rows=[]
    for block in re.findall(r'LAYER\s*\{([^}]*)\}',text,re.S):
        row={}
        for line in block.splitlines():
            if '=' in line:
                key,value=line.strip().split('=',1);row[key.strip()]=value.strip()
        if row:rows.append(row)
    return rows


def outer_copper_layers(matrix,layers):
    """Use physical matrix order/type, never a user-editable layer name.

    ODB++ ROW is the stack order. KiCad can export custom names instead of
    f.cu/b.cu. Keep the exact exported names for EDA feature/drill lookup.
    """
    copper=[row for row in matrix if row.get('CONTEXT','BOARD').upper()=='BOARD'
            and row.get('TYPE','').upper() in ('SIGNAL','POWER_GROUND','MIXED')]
    if copper:
        try:
            copper=sorted(copper,key=lambda row:int(row['ROW']))
        except (KeyError,ValueError):
            raise ValueError('ODB++ copper matrix has missing or invalid stack-order ROW values.')
        names=[row.get('NAME','').casefold() for row in copper]
        if len(set(names))!=len(names) or len({row['ROW'] for row in copper})!=len(copper):
            raise ValueError('ODB++ copper matrix has ambiguous layer names or stack order.')
        if len(names)<2:raise ValueError('Expected top and bottom copper in the native ODB++ stack.')
        if any(name not in layers for name in names):
            raise ValueError('Native ODB++ copper matrix refers to a missing layer directory.')
        return {'top':names[0],'bottom':names[-1]}
    # Compatibility with older minimal exports containing no copper matrix rows.
    if all(name in layers for name in ('f.cu','b.cu')):
        return {'top':'f.cu','bottom':'b.cu'}
    raise ValueError('Cannot identify outer copper: native ODB++ matrix has no copper stack metadata.')


def _mask(identifier,holes,box):
    if not holes:return ''
    x,y,w,h=box
    return f'<mask id="{identifier}" maskUnits="userSpaceOnUse" x="{_fmt(x)}" y="{_fmt(-y-h)}" width="{_fmt(w)}" height="{_fmt(h)}" style="mask-type:luminance"><rect x="{_fmt(x)}" y="{_fmt(-y-h)}" width="{_fmt(w)}" height="{_fmt(h)}" fill="white"/><g color="black" fill="currentColor">{"".join(holes)}</g></mask>'


def write_net_plots(odb_folder,output_folder,board):
    """Write two combined net SVGs and neutral previews, mutating board metadata.

    There is one path group per real net, not one resource request per net.
    Unsupported records fail explicitly so the app never presents guessed copper.
    """
    root=Path(odb_folder);output=Path(output_folder)
    steps=[p for p in (root/'steps').iterdir() if p.is_dir()]
    if len(steps)!=1:raise ValueError('Expected one native KiCad ODB++ board step.')
    step=steps[0];header=(step/'stephdr').read_text()
    for key in ('X_ORIGIN','Y_ORIGIN','X_DATUM','Y_DATUM'):
        match=re.search(r'^'+key+r'\s*=\s*(\S+)',header,re.M)
        if match and _number(match.group(1))!=0:raise ValueError('Nonzero ODB++ step transforms are not supported for board selection.')
    mapping=eda_mapping((step/'eda'/'data').read_text())
    matrix=_matrix((root/'matrix'/'matrix').read_text())
    layers={p.name.casefold():p for p in (step/'layers').iterdir() if p.is_dir()}
    custom_cache={};custom_active=set()
    def custom(name):
        if name in custom_cache:return custom_cache[name]
        if not re.fullmatch(r'[A-Za-z0-9_.+\-]+',name):raise ValueError('Invalid custom ODB++ symbol name.')
        if name in custom_active or len(custom_active)>=32:raise ValueError('Recursive ODB++ custom symbol.')
        path=root/'symbols'/name/'features'
        if not path.is_file():raise ValueError('Unsupported ODB++ symbol: '+name)
        custom_active.add(name)
        try:
            records=parse_features(path.read_text(),custom)
            # A custom symbol is local aperture geometry; negative geometry must
            # cut that aperture only, rather than any neighbouring copper.
            positive=''.join(f.svg for f in records if f.polarity=='P')
            negative=[f.svg for f in records if f.polarity=='N']
            if negative:
                identifier='symbol-'+hashlib.sha256(name.encode()).hexdigest()[:16]
                mask=f'<mask id="{identifier}" maskUnits="objectBoundingBox" maskContentUnits="userSpaceOnUse" x="0" y="0" width="1" height="1" style="mask-type:luminance"><rect x="-100000" y="-100000" width="200000" height="200000" fill="white"/><g color="black" fill="currentColor">{"".join(negative)}</g></mask>'
                positive=f'<defs>{mask}</defs><g mask="url(#{identifier})">{positive}</g>'
            custom_cache[name]=positive;return positive
        finally:custom_active.remove(name)
    nets={n['name']:n for n in board['nets']}
    for index,net in enumerate(board['nets']):
        net['plot_key']=hashlib.sha256(net['name'].encode()).hexdigest()[:32]
        net.setdefault('colour',f'hsl({(index*137.508)%360:.3f} 72% 55%)')
    bounds=board['bounds_mm'];box=[bounds[0],bounds[1],bounds[2]-bounds[0],bounds[3]-bounds[1]]
    if box[2]<=0 or box[3]<=0:raise ValueError('Invalid board preview bounds.')
    viewbox=' '.join(_fmt(v) for v in box)
    profile=parse_features((step/'profile').read_text(),custom)
    profile_svg=''.join(f.svg.replace('fill="currentColor"','fill="none"').replace('stroke="none"','stroke="currentColor" stroke-width=".05"') for f in profile if f.polarity=='P')
    board['plots']={};board['colour_layers']={}
    for side,layer_name in outer_copper_layers(matrix,layers).items():
        if layer_name not in layers:raise ValueError('Native ODB++ export is missing '+layer_name)
        layer=layers[layer_name];features=parse_features((layer/'features').read_text(),custom)
        for (mapped_layer,index),net_name in mapping.items():
            if mapped_layer==layer_name and index>=len(features):raise ValueError('ODB++ connectivity refers past the native copper feature table.')
        grouped={name:[] for name in nets};unassigned=[];negative=[]
        for index,feature in enumerate(features):
            if feature.polarity=='N':negative.append(feature.svg);continue
            name=mapping.get((layer_name,index),'$NONE$')
            if name in grouped:grouped[name].append(feature.svg)
            elif name=='$NONE$':unassigned.append(feature.svg)
            else:raise ValueError('ODB++ copper net does not match the original board: '+name)
        # Through/blind/buried drill applicability is declared by matrix spans.
        for row in matrix:
            if row.get('TYPE')!='DRILL' or layer_name not in [row.get('START_NAME','').casefold(),row.get('END_NAME','').casefold()]:continue
            name=row.get('NAME','').casefold()
            if name not in layers:raise ValueError('ODB++ drill layer is missing.')
            drill=parse_features((layers[name]/'features').read_text(),custom)
            if any(f.polarity!='P' for f in drill):raise ValueError('Negative ODB++ drill geometry is not supported.')
            negative.extend(f.svg for f in drill)
        identifier='copper-holes-'+side;mask=_mask(identifier,negative,box)
        mask_ref=f' mask="url(#{identifier})"' if negative else ''
        groups=''.join(f'<g data-net-key="{nets[name]["plot_key"]}" data-net-name="{escape(name,quote=True)}" color="{escape(nets[name]["colour"],quote=True)}" fill="currentColor" stroke="none">{"".join(shapes)}</g>' for name,shapes in grouped.items())
        neutral=''.join(f.svg for f in features if f.polarity=='P')
        common=f'<defs>{mask}</defs>' if mask else ''
        coloured=f'{common}<g transform="scale(1 -1)"{mask_ref}>{groups}</g>'
        background=f'{common}<g transform="scale(1 -1)" color="#888888" fill="currentColor" stroke="none"{mask_ref}>{neutral}</g><g transform="scale(1 -1)" color="#888888">{profile_svg}</g>'
        for folder,content in [('full',background),('coloured',coloured)]:
            destination=output/folder;destination.mkdir(parents=True,exist_ok=True)
            (destination/(side+'.svg')).write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">{content}</svg>',encoding='utf-8')
        board['plots'][side]=dict(file=side+'.svg',viewbox=box)
        board['colour_layers'][side]=dict(file=side+'.svg',layer_name=layer.name,viewbox=box,net_groups=len(grouped),feature_count=len(features),unassigned_features=len(unassigned))
    board['preview_source']='native_odb_connectivity'
    return board['colour_layers']
