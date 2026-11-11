"""ODB++ standard symbol geometry for native copper previews.

SVG fragments use millimetres and ODB's y-up axes; the caller flips Y once at
layer level. Standard symbol dimensions are micrometres for MM feature files
and mils for INCH files. Corner numbers follow ODB: upper-right, upper-left,
lower-left, lower-right. Unsupported names are delegated to a custom-symbol
feature loader, never approximated by a bounding box.

Reference: Siemens ODB++ Design Format Specification 8.1, Appendix A.
"""
import math
import re

NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'


def _scale(units):
    if units.upper()=='MM':return .001
    if units.upper() in ('INCH','IN'):return .0254
    raise ValueError(f'Unsupported ODB symbol units: {units}')


def _number(value):
    value=float(value)
    if not math.isfinite(value):raise ValueError('Non-finite ODB symbol dimension.')
    return '0' if abs(value)<1e-14 else format(value,'.12g')


def _dimensions(values,scale):
    result=[float(value)*scale for value in values]
    if any(not math.isfinite(value) for value in result):raise ValueError('Non-finite ODB symbol dimension.')
    return result


def _positive(*values):
    if any(value<=0 for value in values):raise ValueError('ODB symbol width and height must be positive.')


def _corners(value):
    if value is None:return {1,2,3,4}
    if not value or any(c not in '1234' for c in value):raise ValueError('Invalid ODB rectangle corner numbers.')
    return {int(c) for c in value}


def _rectangle_path(width,height,radius=0,corners=None,chamfer=False):
    _positive(width,height)
    radius=max(0,min(radius,width/2,height/2));corners=corners or set()
    vertices=[(width/2,height/2),(-width/2,height/2),(-width/2,-height/2),(width/2,-height/2)]
    pairs=[]
    for index,(x,y) in enumerate(vertices):
        previous=vertices[(index-1)%4];following=vertices[(index+1)%4]
        amount=radius if index+1 in corners else 0
        def towards(point):
            dx,dy=point[0]-x,point[1]-y;length=math.hypot(dx,dy)
            return x+dx/length*amount,y+dy/length*amount
        pairs.append((towards(previous),towards(following),amount))
    parts=[]
    for index,(entry,exit,amount) in enumerate(pairs):
        parts.append(('M' if index==0 else 'L')+' '.join(map(_number,entry)))
        if amount and not chamfer:parts.append('A'+_number(amount)+' '+_number(amount)+' 0 0 1 '+' '.join(map(_number,exit)))
        else:parts.append('L'+' '.join(map(_number,exit)))
    return ' '.join(parts)+' Z'


def _circle_path(diameter):
    _positive(diameter);radius=diameter/2;r=_number(radius)
    return f'M {r} 0 A {r} {r} 0 1 1 -{r} 0 A {r} {r} 0 1 1 {r} 0 Z'


def _path(value):return f'<path d="{value}" fill-rule="evenodd"/>'


def symbol_svg(name,custom_loader=None,units='MM'):
    """Return exact supported standard geometry, or delegate a custom name.

    custom_loader(name) returns an SVG fragment rendered from symbols/name/features.
    The caller is responsible for rejecting custom-symbol reference cycles.
    """
    scale=_scale(units);n=NUMBER
    match=re.fullmatch(r'([rs])('+n+r')',name)
    if match:
        size=float(match[2])*scale;_positive(size)
        if match[1]=='r':return f'<circle cx="0" cy="0" r="{_number(size/2)}"/>'
        return _path(_rectangle_path(size,size))
    match=re.fullmatch(r'rect('+n+r')x('+n+r')(?:x([rc])('+n+r')(?:x([1-4]+))?)?',name)
    if match:
        width,height=_dimensions(match.group(1,2),scale)
        radius=float(match[4] or 0)*scale
        return _path(_rectangle_path(width,height,radius,_corners(match[5]),match[3]=='c'))
    match=re.fullmatch(r'(oval|di|diamond|oct)('+n+r')x('+n+r')(?:x('+n+r'))?',name)
    if match:
        width,height=_dimensions(match.group(2,3),scale);_positive(width,height)
        if match[1]=='oval':return f'<rect x="{_number(-width/2)}" y="{_number(-height/2)}" width="{_number(width)}" height="{_number(height)}" rx="{_number(min(width,height)/2)}"/>'
        if match[1] in ('di','diamond'):
            return _path('M '+_number(width/2)+' 0 L 0 '+_number(height/2)+' L '+_number(-width/2)+' 0 L 0 '+_number(-height/2)+' Z')
        if match[4] is None:raise ValueError('An ODB octagon requires a corner size.')
        return _path(_rectangle_path(width,height,float(match[4])*scale,{1,2,3,4},True))
    match=re.fullmatch(r'donut_(r|s|sr)('+n+r')x('+n+r')(?:xr('+n+r')(?:x([1-4]+))?)?',name)
    if match:
        outer,inner=_dimensions(match.group(2,3),scale);_positive(outer)
        radius=float(match[4] or 0)*scale;corners=_corners(match[5])
        outer_path=_circle_path(outer) if match[1]=='r' else _rectangle_path(outer,outer,radius,corners)
        # Some KiCad outline symbols have a nonpositive inner diameter. Their
        # contour has no aperture hole and is rendered as a filled outer shape.
        inner_path=''
        if inner>0:
            if inner>=outer:raise ValueError('ODB donut inner diameter must be smaller than its outer diameter.')
            inner_path=_circle_path(inner) if match[1] in ('r','sr') else _rectangle_path(inner,inner,max(0,radius-(outer-inner)/2),corners)
        return _path(outer_path+' '+inner_path)
    match=re.fullmatch(r'donut_rc('+n+r')x('+n+r')x('+n+r')(?:xr('+n+r')(?:x([1-4]+))?)?',name)
    if match:
        width,height,line=_dimensions(match.group(1,2,3),scale);_positive(width,height,line)
        radius=float(match[4] or 0)*scale;corners=_corners(match[5])
        outer=_rectangle_path(width,height,radius,corners)
        inner=_rectangle_path(width-2*line,height-2*line,max(0,radius-line),corners) if min(width,height)>2*line else ''
        return _path(outer+' '+inner)
    if custom_loader is not None:
        result=custom_loader(name)
        if isinstance(result,str) and result:return result
    raise ValueError(f'Unsupported ODB symbol: {name}')


def symbol_line_style(name,units='MM'):
    """Return width in mm and SVG cap style for round/square line apertures."""
    match=re.fullmatch(r'([rs])('+NUMBER+r')',name)
    if not match:raise ValueError(f'Unsupported nonuniform ODB line aperture: {name}')
    width=float(match[2])*_scale(units);_positive(width)
    return width,'round' if match[1]=='r' else 'square'


def symbol_width(name,units='MM'):
    return symbol_line_style(name,units)[0]
