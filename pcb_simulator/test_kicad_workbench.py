"""CAD integration checks for preserving KiCad identities in Geometry mode."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import gmsh
from pcb_simulator.kicad_workbench import promote_to_workbench


class KiCadWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.source=self.folder/'copper.xao'
        self.board={'pads':[
            dict(id='u1-8',reference='U1',number='8',label='U1 · Pad 8',net='VCC'),
            dict(id='jp1-1',reference='JP1',number='1',label='JP1 · Pad 1',net='VCC')]}
        self.terminals=[dict(pad_id='u1-8',role='input'),dict(pad_id='jp1-1',role='output')]

    def source_cad(self,shared=False):
        gmsh.initialize()
        try:
            gmsh.option.setNumber('General.Terminal',0)
            tags=[gmsh.model.occ.addBox(10,20,0,1,1,.1)]
            if not shared:tags.append(gmsh.model.occ.addBox(12,20,0,1,1,.1))
            gmsh.model.occ.synchronize()
            faces=[]
            for tag in tags:
                faces.append([t for d,t in gmsh.model.getBoundary([(3,tag)],oriented=False) if d==2])
            groups=[(faces[0][-1],'Pad_F_U1_8_VCC'),(faces[0][-2] if shared else faces[1][-1],'Pad_B_JP1_1_VCC')]
            for face,name in groups:
                physical=gmsh.model.addPhysicalGroup(2,[face]);gmsh.model.setPhysicalName(2,physical,name)
            gmsh.write(str(self.source))
        finally:gmsh.finalize()

    def test_named_xao_preserves_pad_identity_and_selected_roles(self):
        self.source_cad();before=hashlib.sha256(self.source.read_bytes()).hexdigest()
        target=self.folder/'model'
        result=promote_to_workbench(self.source,target,self.board,'VCC',self.terminals,lambda *a,**k:None)
        self.assertEqual(hashlib.sha256((target/'source.xao').read_bytes()).hexdigest(),before)
        self.assertEqual(result['source'],'source.xao')
        self.assertEqual(result['source_kind'],'kicad_xao')
        self.assertEqual(result['counts'],{'pad':2})
        rows={r['name']:r for r in result['solids']}
        self.assertEqual(result['default_input_tags'],[rows['U1 · Pad 8']['tag']])
        self.assertEqual(result['default_output_tags'],[rows['JP1 · Pad 1']['tag']])
        self.assertEqual(rows['U1 · Pad 8']['kicad_pad_id'],'u1-8')
        self.assertEqual(rows['JP1 · Pad 1']['net'],'VCC')
        self.assertEqual(len(rows['U1 · Pad 8']['electrode_faces']),1)
        self.assertIn('Pad_B_JP1_1_VCC',result['kicad_pad_map']['jp1-1']['boundaries'])
        preview=json.loads((target/'preview.json').read_text())
        self.assertEqual({b['name'] for b in preview['bodies']},set(rows))
        self.assertTrue(all(b['kind']=='pad' for b in preview['bodies']))
        self.assertEqual(json.loads((target/'inventory.json').read_text())['default_output_tags'],result['default_output_tags'])

    def test_shared_pad_volume_is_rejected_instead_of_guessing(self):
        self.source_cad(shared=True)
        with self.assertRaisesRegex(ValueError,'share a copper solid'):
            promote_to_workbench(self.source,self.folder/'model',self.board,'VCC',self.terminals,lambda *a,**k:None)

    def test_missing_named_pad_surface_is_rejected(self):
        self.source_cad();self.board['pads'][0]['number']='99'
        with self.assertRaisesRegex(ValueError,'No named XAO electrode surfaces'):
            promote_to_workbench(self.source,self.folder/'model',self.board,'VCC',self.terminals,lambda *a,**k:None)


if __name__=='__main__':unittest.main()
