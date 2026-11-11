"""Checks for explicitly recorded physical stackup values and unit conversion."""
import unittest
from pcb_simulator.kicad_preview import parse
from pcb_simulator.kicad_details import board_details


class KiCadDetailsTests(unittest.TestCase):
    def test_custom_display_names_preserve_canonical_layer_identity(self):
        data=board_details(parse('''(kicad_pcb
          (layers (0 "F.Cu" signal "Component Copper") (2 "B.Cu" signal "Solder Copper"))
          (setup (stackup (layer "F.Cu" (type "copper") (thickness .035))
                          (layer "B.Cu" (type "copper") (thickness .035)))))'''))
        self.assertEqual(data['copper_layers'],['F.Cu','B.Cu'])
        self.assertEqual([r['display_name'] for r in data['stackup']],['Component Copper','Solder Copper'])
        self.assertEqual(data['layer_display_names']['B.Cu'],'Solder Copper')

    def test_ordered_stackup_and_mm_to_mils(self):
        data = board_details(parse('''(kicad_pcb
          (general (thickness 1.6))
          (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (1 "F.Mask" user))
          (setup (stackup
            (layer "F.SilkS" (type "Top Silk Screen"))
            (layer "F.Mask" (type "Top Solder Mask") (thickness .01))
            (layer "F.Cu" (type "copper") (thickness .035))
            (layer "dielectric 1" (type "core") (thickness 1.51)
              (material "FR4") (epsilon_r 4.5) (loss_tangent .02))
            (layer "B.Cu" (type "copper") (thickness .035))
            (layer "B.Mask" (type "Bottom Solder Mask") (thickness .01))
            (copper_finish "ENIG") (dielectric_constraints yes))))'''))
        self.assertEqual(data['copper_layers'], ['F.Cu', 'B.Cu'])
        self.assertEqual(data['copper_layer_count'], 2)
        self.assertEqual([r['name'] for r in data['stackup']],
                         ['F.SilkS', 'F.Mask', 'F.Cu', 'dielectric 1', 'B.Cu', 'B.Mask'])
        self.assertIsNone(data['stackup'][0]['thickness_mm'])
        self.assertAlmostEqual(data['stackup'][2]['thickness_mils'], 1.3779527559)
        self.assertEqual(data['stackup'][3]['material'], 'FR4')
        self.assertEqual(data['stackup'][3]['epsilon_r'], 4.5)
        self.assertAlmostEqual(data['specified_stackup_thickness_mm'], 1.6)
        self.assertAlmostEqual(data['board_thickness_mils'], 62.9921259843)
        self.assertEqual(data['copper_finish'], 'ENIG')

    def test_dielectric_sublayers_are_preserved_and_summed(self):
        data = board_details(parse('''(kicad_pcb (setup (stackup
          (layer "dielectric 1" (type "prepreg") (thickness .1 locked)
            (material "A") (epsilon_r 4.2) addsublayer
            (thickness .2) (material "B") (epsilon_r 3.8)))) )'''))
        row = data['stackup'][0]
        self.assertAlmostEqual(row['thickness_mm'], .3)
        self.assertEqual([s['material'] for s in row['sublayers']], ['A', 'B'])
        self.assertTrue(row['sublayers'][0]['thickness_locked'])
        self.assertEqual([s['epsilon_r'] for s in row['sublayers']], [4.2, 3.8])

    def test_missing_and_invalid_thicknesses_never_get_defaults(self):
        for raw in ['', '(general (thickness nan))', '(general (thickness -1))']:
            data = board_details(parse('(kicad_pcb '+raw+')'))
            self.assertIsNone(data['board_thickness_mm'])
            self.assertIsNone(data['board_thickness_mils'])
            self.assertIsNone(data['specified_stackup_thickness_mm'])
            self.assertEqual(data['stackup'], [])
        data = board_details(parse('''(kicad_pcb (setup (stackup
          (layer "dielectric 1" (thickness .1) addsublayer (material "unknown")))))'''))
        self.assertIsNone(data['stackup'][0]['thickness_mm'])
        self.assertAlmostEqual(data['specified_stackup_thickness_mm'], .1)


if __name__ == '__main__':
    unittest.main()
