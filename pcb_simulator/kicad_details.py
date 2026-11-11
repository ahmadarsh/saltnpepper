"""Read the physical stackup recorded in a KiCad PCB without inventing defaults."""
import math

MM_PER_MIL = 0.0254


def _number(values):
    try:
        value = float(values[0])
    except (IndexError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _mils(value):
    return value / MM_PER_MIL if value is not None else None


def _properties(nodes):
    fields = {node.head: node.args for node in nodes}
    thickness = _number(fields.get('thickness', []))
    return dict(
        thickness_mm=thickness, thickness_mils=_mils(thickness),
        thickness_locked='locked' in fields.get('thickness', []),
        material=next(iter(fields.get('material', [])), None),
        epsilon_r=_number(fields.get('epsilon_r', [])),
        loss_tangent=_number(fields.get('loss_tangent', [])),
        colour=next(iter(fields.get('color', [])), None))


def board_details(tree):
    """Return ordered stackup layers and explicit thicknesses in mm and mils.

    The caller supplies the existing S-expression tree. Each physical layer has
    a ``sublayers`` list; KiCad's bare ``addsublayer`` separators retain separate
    dielectric material records. Unspecified values remain None, including the
    total layer thickness when any of its dielectric plies omit a thickness.
    """
    general = tree.child('general')
    thickness = _number(general.values('thickness')) if general else None
    layer_table = tree.child('layers')
    copper_layers = [node.args[0] for node in layer_table.children()
                     if node.args and node.args[0].endswith('.Cu')] if layer_table else []
    display_names = {node.args[0]:node.args[2] if len(node.args)>2 else node.args[0]
                     for node in layer_table.children() if node.args} if layer_table else {}
    setup = tree.child('setup')
    stack = setup.child('stackup') if setup else None
    rows = []
    if stack:
        for layer in stack.children('layer'):
            groups = [[]]
            for item in layer.items[2:]:
                if isinstance(item, str):
                    if item == 'addsublayer':
                        groups.append([])
                elif item.head in ('addsublayer', 'add_dielectric'):
                    groups.append(item.children())
                else:
                    groups[-1].append(item)
            sublayers = [_properties(group) for group in groups]
            first = sublayers[0]
            layer_thickness = (sum(s['thickness_mm'] for s in sublayers)
                               if all(s['thickness_mm'] is not None for s in sublayers) else None)
            kind = next(iter(layer.values('type')), None)
            name=layer.args[0] if layer.args else ''
            rows.append(dict(name=name, display_name=display_names.get(name,name), type=kind,
                             material=first['material'], epsilon_r=first['epsilon_r'],
                             loss_tangent=first['loss_tangent'], colour=first['colour'],
                             thickness_mm=layer_thickness, thickness_mils=_mils(layer_thickness),
                             sublayers=sublayers))
    specified = [sub['thickness_mm'] for row in rows for sub in row['sublayers']
                 if sub['thickness_mm'] is not None]
    total = sum(specified) if specified else None
    return dict(
        stackup=rows, has_stackup=stack is not None,
        copper_layers=copper_layers, copper_layer_count=len(copper_layers),
        layer_display_names=display_names,
        board_thickness_mm=thickness, board_thickness_mils=_mils(thickness),
        specified_stackup_thickness_mm=total, specified_stackup_thickness_mils=_mils(total),
        copper_finish=next(iter(stack.values('copper_finish')), None) if stack else None,
        dielectric_constraints=next(iter(stack.values('dielectric_constraints')), None) if stack else None,
        edge_connector=next(iter(stack.values('edge_connector')), None) if stack else None,
        castellated_pads=next(iter(stack.values('castellated_pads')), None) if stack else None,
        edge_plating=next(iter(stack.values('edge_plating')), None) if stack else None,
        thickness_units='mm', display_units=['mm', 'mils'])
