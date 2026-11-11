"""Targeted checks for real identities, coordinate transforms and read-only filtering."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pcb_simulator import kicad_preview as kc

BOARD='''(kicad_pcb (version 20241229) (generator "pcbnew")
 (general (thickness 1.6)) (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
 (net 0 "") (net 1 "/POWER/3V3") (net 2 "GND")
 (footprint "test" (layer "F.Cu") (at 10 20 90)
  (property "Reference" "U1")
  (pad "A2" smd rect (at 2 0 90) (size 1 2) (layers "F.Cu") (net 1 "/POWER/3V3") (uuid "input-id")))
 (footprint "test2" (layer "B.Cu") (at 20 20)
  (property "Reference" "J2")
  (pad "52" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu") (net 1 "/POWER/3V3") (uuid "output-id")))
 (footprint "test3" (layer "F.Cu") (at 30 20)
  (property "Reference" "C1")
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 2 "GND") (uuid "other-id")))
 (segment (start 10 18) (end 20 20) (width .3) (layer "F.Cu") (net 1))
 (via (at 15 19) (size .6) (drill .3) (layers "F.Cu" "B.Cu") (net 1))
 (zone (net 2) (net_name "GND") (layer "B.Cu") (polygon (pts (xy 1 1) (xy 3 1) (xy 3 3)))))'''

class KiCadPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.source=self.folder/'board.kicad_pcb';self.source.write_text(BOARD)

    def test_real_names_uuid_net_and_rotated_coordinates(self):
        board,*_=kc.inventory(self.source)
        source=next(p for p in board['pads'] if p['id']=='input-id')
        self.assertEqual(source['label'],'U1 · Pad A2')
        self.assertEqual(source['net'],'/POWER/3V3')
        self.assertAlmostEqual(source['x_mm'],10);self.assertAlmostEqual(source['y_mm'],18)
        self.assertEqual(source['angle_deg'],90)
        through=next(p for p in board['pads'] if p['id']=='output-id')
        self.assertEqual(through['sides'],['top','bottom'])
        net=next(n for n in board['nets'] if n['name']=='/POWER/3V3')
        self.assertEqual((net['pads'],net['tracks'],net['vias']),(2,1,1))

    def test_filter_preserves_original_and_drops_other_net_copper(self):
        before=hashlib.sha256(self.source.read_bytes()).hexdigest()
        filtered=self.folder/'filtered.kicad_pcb'
        pads=kc.filtered_board(self.source,filtered,'/POWER/3V3')
        self.assertEqual({p['id'] for p in pads},{'input-id','output-id'})
        result,*_=kc.inventory(filtered)
        self.assertEqual(len(result['pads']),2)
        self.assertNotIn('other-id',filtered.read_text())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),before)

    def test_invalid_or_unknown_boards_and_nets_are_rejected(self):
        for text in ['hello','(not_a_board)','(kicad_pcb','(kicad_pcb) trailing']:
            with self.assertRaises(ValueError):kc.parse(text)
        with self.assertRaises(ValueError):kc.filtered_board(self.source,self.folder/'out','BAD_NET')

    def test_terminal_validation_happens_before_cli_export(self):
        for inputs,outputs in [([],['output-id']),(['input-id'],['input-id']),(['other-id'],['output-id'])]:
            with patch.object(kc,'run_cli') as export:
                with self.assertRaises(ValueError):kc.prepare(self.source,self.folder/'out','/POWER/3V3',inputs,outputs,lambda *a,**k:None)
                export.assert_not_called()

    def test_unsupported_platform_status_is_explicit(self):
        with patch.object(kc.sys,'platform','linux'):
            result=kc.status()
            self.assertFalse(result['available']);self.assertIn('macOS and Windows',result['error'])

    def colour_board(self,*names):
        return {'nets':[{'name':name,'colour':f'hsl({index*60} 72% 55%)'} for index,name in enumerate(names)]}

    def test_project_net_override_takes_precedence_over_netclass(self):
        board=self.colour_board('VCC','GND')
        count=kc.project_colours(board,{'net_settings':{
            'classes':[{'name':'Power','pcb_color':'rgb(10, 20, 30)','priority':0}],
            'netclass_assignments':{'VCC':['Power'],'GND':'Power'},
            'net_colors':{'VCC':'rgba(255, 128, 0, 1.000)'}}})
        self.assertEqual(count,2)
        self.assertEqual(board['nets'][0]['colour'],'rgb(255, 128, 0)')
        self.assertEqual(board['nets'][0]['colour_source'],'KiCad net override')
        self.assertEqual(board['nets'][1]['colour'],'rgb(10, 20, 30)')
        self.assertEqual(board['nets'][1]['colour_source'],'KiCad netclass: Power')

    def test_transparent_project_defaults_preserve_automatic_colours_on_reimport(self):
        board=self.colour_board('VCC')
        automatic=board['nets'][0]['colour']
        kc.project_colours(board,{'net_settings':{'net_colors':{'VCC':'rgb(1, 2, 3)'}}})
        self.assertNotEqual(board['nets'][0]['colour'],automatic)
        count=kc.project_colours(board,{'net_settings':{
            'classes':[{'name':'Default','pcb_color':'rgba(0, 0, 0, 0.000)'}],
            'net_colors':{'VCC':'rgba(200, 100, 50, 0)'}}})
        self.assertEqual(count,0)
        self.assertEqual(board['nets'][0]['colour'],automatic)
        self.assertEqual(board['nets'][0]['colour_source'],'Automatic')

    def test_project_patterns_priority_legacy_assignments_and_default(self):
        board=self.colour_board('/USB_P','/USB_N','LEGACY','OTHER')
        count=kc.project_colours(board,{'net_settings':{
            'classes':[
                {'name':'Default','pcb_color':'rgb(40, 50, 60)'},
                {'name':'Bus','priority':10,'pcb_color':'rgb(70, 80, 90)'},
                {'name':'Specific','priority':0,'pcb_color':'rgb(100, 110, 120)'},
                {'name':'Legacy','nets':['LEGACY'],'pcb_color':'rgb(130, 140, 150)'}],
            'netclass_patterns':[
                {'pattern':'/USB_*','netclass':'Bus'},
                {'pattern':'/USB_?','netclass':'Specific'}]}})
        self.assertEqual(count,4)
        self.assertEqual([n['colour'] for n in board['nets']],
                         ['rgb(100, 110, 120)','rgb(100, 110, 120)','rgb(130, 140, 150)','rgb(40, 50, 60)'])

    def test_project_colour_rejects_non_numeric_css_and_out_of_range_rgb(self):
        for value in ['rgb(256, 0, 0)','rgb(-1, 0, 0)','red; background:url(https://example.invalid)',
                      'url(https://example.invalid)','rgb(1,2,3);color:red','rgba(1,2,3,2)',None]:
            with self.subTest(colour=value):
                board=self.colour_board('VCC');automatic=board['nets'][0]['colour']
                self.assertEqual(kc.project_colours(board,{'net_settings':{'net_colors':{'VCC':value}}}),0)
                self.assertEqual(board['nets'][0]['colour'],automatic)
        with self.assertRaises(ValueError):kc.project_colours(self.colour_board('VCC'),{})

    def test_geometry_preview_encodes_real_surfaces_and_named_terminal_overlays(self):
        import base64
        import json
        import gmsh
        import numpy as np
        gmsh.initialize()
        try:
            gmsh.option.setNumber('General.Terminal',0)
            volume=gmsh.model.occ.addBox(100,200,-1.6,2,1,.1)
            gmsh.model.occ.synchronize()
            faces=[tag for dim,tag in gmsh.model.getBoundary([(3,volume)],oriented=False) if dim==2]
            ordered=sorted(faces,key=lambda tag:gmsh.model.occ.getCenterOfMass(2,tag)[2])
            terminals=[dict(pad_id='U1-pad8',label='U1 · Pad 8',role='input',boundaries={'Pad_F_U1_8_VCC':{'faces':[ordered[-1]]}}),
                       dict(pad_id='JP1-pad1',label='JP1 · Pad 1',role='output',boundaries={'Pad_B_JP1_1_VCC':{'faces':[ordered[0]]}})]
            preview=kc._geometry_preview(gmsh,self.folder,'VCC',terminals,lambda *a,**k:None)
            self.assertTrue(preview['surface_preview_only'])
            self.assertEqual(preview['geometry_units'],'mm')
            self.assertTrue(np.allclose(preview['center'],[101,200.5,-1.55]))
            self.assertEqual([b['role'] for b in preview['bodies']],['copper','input','output'])
            self.assertEqual([b['tag'] for b in preview['bodies']],[volume,-1,-2])
            self.assertEqual(preview['bodies'][1]['name'],'U1 · Pad 8')
            self.assertEqual(preview['bodies'][2]['pad_id'],'JP1-pad1')
            for body in preview['bodies']:
                vertices=np.frombuffer(base64.b64decode(body['vertices_b64']),dtype='<f4').reshape(-1,3)
                triangles=np.frombuffer(base64.b64decode(body['triangles_b64']),dtype='<u4').reshape(-1,3)
                self.assertGreater(len(triangles),0)
                self.assertLess(int(triangles.max()),len(vertices))
                absolute=vertices+preview['center']
                self.assertTrue(np.allclose(absolute.min(axis=0),body['bounds_mm'][:3],atol=1e-6))
                self.assertTrue(np.allclose(absolute.max(axis=0),body['bounds_mm'][3:],atol=1e-6))
            self.assertEqual(preview['bodies'][1]['boundary_faces'],[ordered[-1]])
            self.assertEqual(preview['bodies'][2]['boundary_faces'],[ordered[0]])
            self.assertEqual(json.loads((self.folder/'preview.json').read_text())['terminals'],terminals)
        finally:gmsh.finalize()

if __name__=='__main__':unittest.main()
