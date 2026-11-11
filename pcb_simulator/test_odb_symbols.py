"""Geometry and unit checks for standard ODB++ symbol rendering."""
import unittest
import xml.etree.ElementTree as ET
from pcb_simulator.odb_symbols import symbol_svg,symbol_width,symbol_line_style


class ODBSymbolTests(unittest.TestCase):
    def test_standard_dimensions_follow_metric_or_mil_symbol_units(self):
        metric=ET.fromstring(symbol_svg('r200'))
        imperial=ET.fromstring(symbol_svg('r20',units='INCH'))
        self.assertEqual(float(metric.attrib['r']),.1)
        self.assertAlmostEqual(float(imperial.attrib['r']),.254)
        self.assertEqual(symbol_line_style('s200'),(.2,'square'))
        self.assertEqual(symbol_line_style('r200'),(.2,'round'))
        self.assertAlmostEqual(symbol_width('r10',units='INCH'),.254)

    def test_capsule_is_not_an_ellipse(self):
        oval=ET.fromstring(symbol_svg('oval1000x3000'))
        self.assertEqual(oval.tag,'rect')
        self.assertEqual({key:float(oval.attrib[key]) for key in ['width','height','rx']},dict(width=1,height=3,rx=.5))

    def test_round_and_chamfer_corner_numbers_start_upper_right_counterclockwise(self):
        rounded=ET.fromstring(symbol_svg('rect2000x1000xr100x13')).attrib['d']
        self.assertEqual(rounded.count('A'),2)
        # Upper-right corner 1 is (1,.5), entered from the right edge.
        self.assertTrue(rounded.startswith('M1 0.4 A0.1 0.1 0 0 1 0.9 0.5'))
        chamfered=ET.fromstring(symbol_svg('rect800x1700xc160x2')).attrib['d']
        self.assertNotIn('A',chamfered)
        self.assertIn('L-0.24 0.85 L-0.4 0.69',chamfered)
        self.assertTrue(chamfered.startswith('M0.4 0.85 L0.4 0.85'))

    def test_donut_preserves_inner_hole_and_nonpositive_inner_becomes_solid(self):
        donut=ET.fromstring(symbol_svg('donut_r2000x1000'))
        self.assertEqual(donut.attrib['fill-rule'],'evenodd')
        self.assertEqual(donut.attrib['d'].count('M'),2)
        solid=ET.fromstring(symbol_svg('donut_r25.4020x-12.6980'))
        self.assertEqual(solid.attrib['d'].count('M'),1)
        rectangular=ET.fromstring(symbol_svg('donut_rc1910x990x50xr25'))
        self.assertEqual(rectangular.attrib['d'].count('M'),2)
        self.assertEqual(rectangular.attrib['d'].count('A'),4)

    def test_diamond_octagon_and_custom_geometry(self):
        diamond=ET.fromstring(symbol_svg('di2000x1000')).attrib['d']
        self.assertIn('M 1 0 L 0 0.5',diamond)
        octagon=ET.fromstring(symbol_svg('oct2000x1000x100')).attrib['d']
        self.assertNotIn('A',octagon)
        seen=[]
        self.assertEqual(symbol_svg('custom_pad',custom_loader=lambda name:seen.append(name) or '<path d="M0 0 L1 0 L0 1 Z"/>'),'<path d="M0 0 L1 0 L0 1 Z"/>')
        self.assertEqual(seen,['custom_pad'])

    def test_unsupported_or_invalid_shapes_fail_without_bbox_substitution(self):
        for name in ['unknown','r0','rect0x100','oct100x100','donut_r100x200','rect100x100xr5x0']:
            with self.subTest(name=name),self.assertRaises(ValueError):symbol_svg(name)
        with self.assertRaises(ValueError):symbol_width('rect200x400')
        with self.assertRaises(ValueError):symbol_svg('r100',units='FURLONG')


if __name__=='__main__':unittest.main()
