"""A through-hole pad remains one terminal across rings and plated barrel.

Synthetic XAO mirrors KiCad's physical groups: each named F/B boundary contains
both the corresponding ring face and the barrel end face. No private board or
installed KiCad is required for the regression tests.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gmsh
import numpy as np
from pcb_simulator.engine import run_simulation
from pcb_simulator import engine
from pcb_simulator.kicad_workbench import promote_to_workbench
from pcb_simulator.server import validate_selection


def emit(*args,**kwargs):pass


def make_through_hole_fixture(path):
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal',0)
        gmsh.model.add('Through-hole pad with three physical copper volumes')
        def ring(z,height,outer,inner):
            outside=gmsh.model.occ.addCylinder(0,0,z,0,0,height,outer)
            inside=gmsh.model.occ.addCylinder(0,0,z,0,0,height,inner)
            result,_=gmsh.model.occ.cut([(3,outside)],[(3,inside)])
            return result[0][1]
        top=ring(.9,.1,1,.6);bottom=ring(0,.1,1,.6);barrel=ring(0,1,.6,.5)
        gmsh.model.occ.addBox(.75,-.2,.9,3.5,.4,.1)
        output=gmsh.model.occ.addBox(4,-.5,.9,1,1,.1)
        gmsh.model.occ.synchronize()
        def planar_face(volume,z):
            faces=[]
            for dimension,tag in gmsh.model.getBoundary([(3,volume)],oriented=False):
                bounds=gmsh.model.getBoundingBox(dimension,tag)
                if dimension==2 and abs(bounds[2]-z)<1e-5 and abs(bounds[5]-z)<1e-5:faces.append(tag)
            if len(faces)!=1:raise AssertionError(f'Expected one planar end face, got {faces}')
            return faces[0]
        groups={
            'Pad_F_J1_1_POWER':[planar_face(top,1),planar_face(barrel,1)],
            'Pad_B_J1_1_POWER':[planar_face(bottom,0),planar_face(barrel,0)],
            'Pad_F_J2_1_POWER':[planar_face(output,1)]}
        for name,faces in groups.items():
            physical=gmsh.model.addPhysicalGroup(2,faces);gmsh.model.setPhysicalName(2,physical,name)
        gmsh.write(str(path))
        return dict(input_volumes=sorted([top,bottom,barrel]),output_volume=output)
    finally:gmsh.finalize()


class ThroughHolePadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='salt-pepper-through-hole-');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.source=self.folder/'copper.xao'
        self.expected=make_through_hole_fixture(self.source)
        self.board={'pads':[
            dict(id='logical-tht-pad',reference='J1',number='1',label='J1 · Pad 1',net='POWER',type='thru_hole'),
            dict(id='logical-smd-pad',reference='J2',number='1',label='J2 · Pad 1',net='POWER',type='smd')]}
        self.terminals=[dict(pad_id='logical-tht-pad',role='input'),dict(pad_id='logical-smd-pad',role='output')]

    def promote(self):
        return promote_to_workbench(self.source,self.folder/'model',self.board,'POWER',self.terminals,emit)

    def test_one_logical_pad_maps_all_three_physical_copper_volumes(self):
        inventory=self.promote();pad=inventory['kicad_pad_map']['logical-tht-pad']
        self.assertEqual(pad['volume_tags'],self.expected['input_volumes'])
        representative=pad['tag'];self.assertIn(representative,pad['volume_tags'])
        self.assertEqual(inventory['default_input_tags'],[representative])
        self.assertEqual(inventory['default_output_tags'],[self.expected['output_volume']])
        rows={row['tag']:row for row in inventory['solids']}
        self.assertEqual(len(rows),5,'Keep every actual source volume for exact reimport and meshing.')
        self.assertEqual(rows[representative]['pad_volume_tags'],pad['volume_tags'])
        self.assertTrue(np.allclose(rows[representative]['pad_bounds_mm'],[-1,-1,0,1,1,1],atol=2e-6))
        self.assertTrue(np.allclose(rows[representative]['pad_centroid_mm'],[0,0,.5],atol=2e-6))
        for tag in pad['volume_tags']:
            self.assertEqual(rows[tag]['kicad_pad_tag'],representative)
            if tag!=representative:self.assertTrue(rows[tag]['kicad_pad_member'])
        selectable=[row for row in rows.values() if row['kind']=='pad' and not row.get('kicad_pad_member')]
        self.assertEqual({row['name'] for row in selectable},{'J1 · Pad 1','J2 · Pad 1'})
        preview=json.loads((self.folder/'model'/'preview.json').read_text())
        parts=[body for body in preview['bodies'] if body.get('kicad_pad_id')=='logical-tht-pad']
        self.assertEqual(len(parts),3)
        self.assertEqual({body['tag'] for body in parts},{representative},'Every visible part must select the same logical pad.')

    def test_single_through_hole_terminal_has_one_solver_entry_and_conserves_current(self):
        inventory=self.promote()
        original_mesh=engine._mesh;port_masses=[]
        def record_partition(definition,*args):
            port=next(port for port in definition['ports'] if port['role']=='input')
            port_masses.append(sum(gmsh.model.occ.getMass(3,tag) for tag in port['volume_tags']))
            return original_mesh(definition,*args)
        with patch.object(engine,'_mesh',side_effect=record_partition):
            result=run_simulation(self.folder/'model'/'source.xao',inventory,self.folder/'simulation',
                                  inventory['default_input_tags'],inventory['default_output_tags'],
                                  dict(analysis_mode='electrical',current_A=1,voltage_V=3.3,ambient_C=20,
                                       mesh_size_mm=.3,refine=False,input_face='top',output_face='top'),emit)
        self.assertEqual(len(result['model']['ports']),2)
        self.assertEqual(len(result['per_pad']),2)
        inputs=[pad for pad in result['per_pad'] if pad['role']=='input']
        outputs=[pad for pad in result['per_pad'] if pad['role']=='output']
        self.assertEqual([pad['name'] for pad in inputs],['J1 · Pad 1'])
        self.assertEqual([pad['name'] for pad in outputs],['J2 · Pad 1'])
        self.assertAlmostEqual(abs(inputs[0]['current_A']),1,places=6)
        self.assertAlmostEqual(abs(outputs[0]['current_A']),1,places=6)
        self.assertAlmostEqual(inputs[0]['current_A']+outputs[0]['current_A'],0,places=8)
        self.assertGreater(result['resistance_ohm'],0)
        input_port=next(port for port in result['model']['ports'] if port['role']=='input')
        self.assertEqual(sorted(input_port['original_solids']),self.expected['input_volumes'])
        # Fragment child count may vary by OCC version, but no ring/barrel
        # copper may disappear from the one grouped terminal volume.
        expected_volume=2*np.pi*(1-.6**2)*.1+np.pi*(.6**2-.5**2)
        self.assertEqual(len(port_masses),1)
        self.assertAlmostEqual(port_masses[0],expected_volume,places=7)
        self.assertEqual(input_port['face'],'top')


class ThroughHoleSelectionTests(unittest.TestCase):
    def setUp(self):
        self.inventory={'solids':[
            dict(tag=4,kicad_pad_tag=4),
            dict(tag=5,kicad_pad_tag=4,kicad_pad_member=True),
            dict(tag=6,kicad_pad_tag=4,kicad_pad_member=True),
            dict(tag=7,kicad_pad_tag=7)]}

    def test_different_physical_parts_of_one_pad_cannot_have_opposite_roles(self):
        with self.assertRaisesRegex(ValueError,'same pad cannot be both input and output'):
            validate_selection(dict(input_tags=[4],output_tags=[5]),self.inventory)

    def test_selected_member_parts_collapse_to_one_logical_pad(self):
        inputs,outputs=validate_selection(dict(input_tags=[5,6,4,5],output_tags=[7]),self.inventory)
        self.assertEqual(inputs,[4])
        self.assertEqual(outputs,[7])


if __name__=='__main__':unittest.main()
