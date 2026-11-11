"""Exact ODB++ feature IDs, native coordinate geometry and combined net previews."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from pcb_simulator.odb_preview import eda_mapping, parse_features, write_net_plots, outer_copper_layers

SVG='{http://www.w3.org/2000/svg}'


class OdbPreviewTests(unittest.TestCase):
    def test_custom_copper_names_use_physical_order_not_names_or_eda_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root,board=self.fixture(Path(temp)/'odb')
            step=root/'steps/pcb'
            (step/'layers/f.cu').rename(step/'layers/component_side')
            (step/'layers/b.cu').rename(step/'layers/solder_side')
            eda=step/'eda/data'
            eda.write_text(eda.read_text().replace('f.cu','component_side').replace('b.cu','solder_side'))
            # Deliberately shuffled records; ROW, not file or EDA order, wins.
            (root/'matrix/matrix').write_text('''LAYER {
ROW=8
CONTEXT=BOARD
TYPE=SIGNAL
NAME=SOLDER_SIDE
}
LAYER {
ROW=4
CONTEXT=BOARD
TYPE=SIGNAL
NAME=COMPONENT_SIDE
}
LAYER {
ROW=10
TYPE=DRILL
NAME=DRILL
START_NAME=COMPONENT_SIDE
END_NAME=SOLDER_SIDE
}
''')
            output=Path(temp)/'preview';write_net_plots(root,output,board)
            self.assertEqual(board['colour_layers']['top']['layer_name'],'component_side')
            self.assertEqual(board['colour_layers']['top']['feature_count'],6)
            self.assertEqual(board['colour_layers']['bottom']['feature_count'],1)
            text=(output/'coloured/top.svg').read_text()
            self.assertIn('data-net-name="POWER"',text)
            self.assertIn('translate(10 -10)',text) # drill mask still follows renamed span

    def test_invalid_copper_stack_is_not_guessed(self):
        for rows in [
            [dict(TYPE='SIGNAL',ROW='1',NAME='top')],
            [dict(TYPE='SIGNAL',ROW='1',NAME='top'),dict(TYPE='SIGNAL',ROW='1',NAME='bottom')],
            [dict(TYPE='SIGNAL',ROW='1',NAME='top'),dict(TYPE='SIGNAL',ROW='2',NAME='missing')],
            [dict(TYPE='SIGNAL',NAME='top'),dict(TYPE='SIGNAL',ROW='2',NAME='bottom')],
        ]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                outer_copper_layers(rows,{'top':None,'bottom':None})

    def test_connectivity_uses_native_layer_order_and_feature_ids(self):
        mapping=eda_mapping('LYR b.cu f.cu drill\nNET /POWER/3V3\nFID C 1 12\nFID H 2 3\nNET GND\nFID C 0 8\n')
        self.assertEqual(mapping,{('f.cu',12):'/POWER/3V3',('b.cu',8):'GND'})
        with self.assertRaises(ValueError):eda_mapping('LYR f.cu\nNET A\nFID C 0 3\nNET B\nFID C 0 3\n')
        with self.assertRaises(ValueError):eda_mapping('LYR f.cu\nNET A\nFID C 1 0\n')

    def test_pad_geometry_uses_clockwise_rotation_then_mirror_in_native_y_up(self):
        feature=parse_features('UNITS=MM\nF 1\n$0 rect2000x1000\nP 1 -2 0 P 0 9 90\n')[0]
        root=ET.fromstring(feature.svg)
        self.assertEqual(root.attrib['transform'],'translate(1 -2) scale(1 -1) rotate(-90)')
        path=root.find('path')
        self.assertIsNotNone(path)
        self.assertIn('L-1 -0.5',path.attrib['d'])
        self.assertIn('L1 0.5',path.attrib['d'])

    def test_line_arc_and_surface_keep_feature_ids_and_holes(self):
        records=parse_features('''UNITS=MM
F 3
$0 r200
L 1 -2 3 -4 0 P 0
A 1 0 0 -1 0 0 0 P 0 Y
S P 0
OB 0 0 I
OS 4 0
OS 4 -4
OS 0 -4
OE
OB 1 -1 H
OS 2 -1
OS 2 -2
OS 1 -2
OE
SE
''')
        self.assertEqual(len(records),3)
        line=ET.fromstring(records[0].svg)
        self.assertEqual(line.attrib['stroke-width'],'0.2')
        self.assertEqual(line.attrib['stroke-linecap'],'round')
        self.assertIn('A 1 1 0 0 0 0 -1',records[1].svg)
        surface=ET.fromstring(records[2].svg)
        self.assertEqual(surface.attrib['fill-rule'],'evenodd')
        self.assertEqual(surface.attrib['d'].count(' Z'),2)

    def test_surface_arcs_and_full_circle_retain_native_endpoints(self):
        records=parse_features('''F 1
S P 0
OB 1 0 I
OC 1 0 0 0 N
OE
SE
''')
        path=ET.fromstring(records[0].svg).attrib['d']
        self.assertEqual(path.count('A 1 1'),2)
        self.assertIn('-1 0',path)

    def test_units_convert_native_coordinates_and_standard_symbol_sizes(self):
        feature=parse_features('UNITS=INCH\nF 1\n$0 r100\nP 1 -2 0 P 0 0\n')[0]
        self.assertIn('translate(25.4 -50.8)',feature.svg)
        circle=ET.fromstring(feature.svg).find('circle')
        self.assertAlmostEqual(float(circle.attrib['r']),1.27)

    def test_unsupported_or_inconsistent_geometry_fails_explicitly(self):
        for text in ['F 2\n$0 r200\nP 0 0 0 P 0 0\n',
                     'F 1\nT 0 0 standard P 0 1 1 1 text\n',
                     'F 1\n$0 r200\nP nan 0 0 P 0 0\n',
                     'F 1\nS P 0\nOB 0 0 I\n',
                     'F 1\n$0 r200\nA 1 0 0 2 0 0 0 P 0 Y\n']:
            with self.subTest(source=text):
                with self.assertRaises(ValueError):parse_features(text)

    def fixture(self,folder):
        root=Path(folder);step=root/'steps'/'pcb'
        def write(relative,text):
            destination=root/relative;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(text)
        write('steps/pcb/stephdr','UNITS=MM\nX_ORIGIN=0\nY_ORIGIN=0\nX_DATUM=0\nY_DATUM=0\n')
        write('steps/pcb/eda/data','LYR b.cu f.cu drill\nNET POWER\nFID C 1 0\nFID C 1 1\nFID C 1 5\nFID C 0 0\nNET GND\nFID C 1 2\nFID C 1 3\nNET $NONE$\nFID C 1 4\n')
        write('steps/pcb/profile','F 1\nS P 0\nOB 0 0 I\nOS 20 0\nOS 20 -20\nOS 0 -20\nOE\nSE\n')
        write('steps/pcb/layers/f.cu/features','''UNITS=MM
F 6
$0 r200
$1 rect2000x1000
$2 custom-aperture
P 1 -2 1 P 0 8 90
L 1 -2 3 -4 0 P 0
A 1 0 0 -1 0 0 0 P 0 Y
S P 0
OB 2 -2 I
OS 4 -2
OS 4 -4
OS 2 -4
OE
SE
P 7 -8 0 N 0 0
P 12 -13 2 P 0 0
''')
        write('steps/pcb/layers/b.cu/features','F 1\n$0 r1000\nP 10 -10 0 P 0 0\n')
        write('steps/pcb/layers/drill/features','F 1\n$0 r600\nP 10 -10 0 P 0 0\n')
        write('matrix/matrix','LAYER {\nTYPE=DRILL\nNAME=DRILL\nSTART_NAME=F.CU\nEND_NAME=B.CU\n}\n')
        write('symbols/custom-aperture/features','F 2\n$0 r1000\n$1 r500\nP 0 0 0 P 0 0\nP 0 0 1 N 0 0\n')
        return root,dict(bounds_mm=[0,0,20,20],nets=[dict(name='POWER'),dict(name='GND')])

    def test_combined_views_keep_exact_net_groups_coordinates_drills_and_local_custom_holes(self):
        with tempfile.TemporaryDirectory() as temp:
            root,board=self.fixture(Path(temp)/'odb');output=Path(temp)/'preview'
            write_net_plots(root,output,board)
            self.assertEqual(board['preview_source'],'native_odb_connectivity')
            self.assertEqual(board['colour_layers']['top']['feature_count'],6)
            self.assertEqual(board['colour_layers']['bottom']['feature_count'],1)
            self.assertEqual(board['plots']['top']['viewbox'],[0,0,20,20])
            key=hashlib.sha256(b'POWER').hexdigest()[:32]
            document=ET.parse(output/'coloured/top.svg').getroot()
            groups={g.attrib['data-net-key']:g for g in document.iter(SVG+'g') if 'data-net-key' in g.attrib}
            self.assertEqual(len(groups),2)
            # Bare standard aperture paths/circles inherit fill. Setting color
            # alone leaves these black while stroked tracks use the net colour.
            for group in groups.values():
                self.assertEqual(group.attrib.get('fill'),'currentColor')
                self.assertEqual(group.attrib.get('stroke'),'none')
            self.assertEqual(groups[key].attrib['data-net-name'],'POWER')
            self.assertIn('translate(1 -2)',ET.tostring(groups[key],encoding='unicode'))
            self.assertNotIn('translate(7 -8)',ET.tostring(groups[key],encoding='unicode'))
            masks={m.attrib['id']:m for m in document.iter(SVG+'mask')}
            self.assertIn('copper-holes-top',masks)
            for mask in masks.values():
                black_groups=[g for g in mask.iter(SVG+'g') if g.attrib.get('color')=='black']
                self.assertTrue(black_groups)
                self.assertTrue(all(g.attrib.get('fill')=='currentColor' for g in black_groups))
            self.assertTrue(any(name.startswith('symbol-') for name in masks))
            holes=ET.tostring(masks['copper-holes-top'],encoding='unicode')
            self.assertIn('translate(7 -8)',holes)
            self.assertIn('translate(10 -10)',holes)
            self.assertTrue(any(g.attrib.get('transform')=='scale(1 -1)' for g in document.iter(SVG+'g')))
            # The neutral preview includes outline and all copper, but no net request fan-out.
            full=ET.parse(output/'full/top.svg').getroot()
            neutral=[g for g in full.iter(SVG+'g') if g.attrib.get('color')=='#888888' and g.attrib.get('mask')]
            self.assertEqual(len(neutral),1)
            self.assertEqual(neutral[0].attrib.get('fill'),'currentColor')
            self.assertEqual(neutral[0].attrib.get('stroke'),'none')
            self.assertTrue(any(p.attrib.get('fill')=='none' and p.attrib.get('stroke-width')=='.05' for p in full.iter(SVG+'path')))
            self.assertEqual(len(list(output.rglob('*.svg'))),4)

    def test_unknown_transforms_and_invalid_connectivity_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root,board=self.fixture(Path(temp)/'odb')
            (root/'steps/pcb/stephdr').write_text('X_ORIGIN=1\n')
            with self.assertRaisesRegex(ValueError,'step transforms'):write_net_plots(root,Path(temp)/'preview',board)
            (root/'steps/pcb/stephdr').write_text('X_ORIGIN=0\n')
            eda=root/'steps/pcb/eda/data';eda.write_text(eda.read_text()+'FID C 1 99\n')
            with self.assertRaisesRegex(ValueError,'past the native'):write_net_plots(root,Path(temp)/'preview',board)


if __name__=='__main__':unittest.main()
