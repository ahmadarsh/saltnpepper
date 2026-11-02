"""Small mesh export checks. Run: python -m unittest pcb_simulator.viewer.test_results"""
import base64
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from pcb_simulator.results import _project_elements, _surface_groups, build_results


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.nodes = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, -2]], dtype=float)
        self.tet = np.array([[0, 1, 2, 3], [0, 2, 1, 4]])
        self.surface = np.array([[0, 1, 3], [1, 2, 3], [2, 0, 3], [0, 2, 4], [2, 1, 4], [1, 0, 4]])
        np.savez(self.output / "fields.npz", nodes_mm=self.nodes, node_tags=np.arange(10, 15),
                 tetrahedra=self.tet, external_triangles=self.surface,
                 voltage_V=np.array([5, 4.99, 4.99, 5, 4.99]),
                 ir_drop_mV=np.array([0, 10, 10, 0, 10]), temperature_C=np.arange(30., 35.),
                 current_density_A_mm2=np.array([3., 9.]), joule_W_mm3=np.array([2., 8.]))
        self.report = dict(input_voltage_V=5, output_voltage_V=4.99, terminal_drop_V=.01,
                           total_current_A=2, resistance_ohm=.005, total_joule_power_W=.02,
                           thermal_solved=False, room_temperature_C=30, limit_temperature_C=75,
                           maximum_temperature_C=None, assumptions=["Test cooling assumption"],
                           per_pad=[dict(name="Input </script><script>bad()</script>", role="input", current_A=2, mean_voltage_V=5)])

    def build(self):
        events = []
        summary = build_results(self.output, self.report, lambda *args, **kwargs: events.append((args, kwargs)))
        html = (self.output / "viewer.html").read_text(encoding="utf-8")
        packed = html.split('<script id="geometry" type="application/json">', 1)[1].split('</script>', 1)[0]
        self.assertEqual(len(events), 2)
        return summary, json.loads(packed), html

    def test_volume_weighted_projection_uses_element_volume(self):
        result, weights = _project_elements(self.nodes, self.tet, {"J": np.array([3., 9.])})
        np.testing.assert_allclose(result["J"], [7, 7, 7, 3, 9])
        self.assertAlmostEqual(weights[0], .5)

    def test_projection_across_memory_chunks(self):
        tetrahedra = np.tile(self.tet, (50_001, 1))
        field = np.tile([3., 9.], 50_001)
        result, _ = _project_elements(self.nodes, tetrahedra, {"J": field})
        np.testing.assert_allclose(result["J"], [7, 7, 7, 3, 9])

    def test_generic_nested_ports_file(self):
        folder = self.output / "arbitrary-mesh"
        folder.mkdir()
        ports = [dict(name="Supply A", role="input", centroid_mm=[0, .5, .1]),
                 dict(name="Load B", role="output", centroid_mm=[.3, .4, -.2])]
        (folder / "ports.json").write_text(json.dumps(dict(ports=ports)), encoding="utf-8")
        self.report["ports_file"] = "arbitrary-mesh/ports.json"
        _, payload, _ = self.build()
        self.assertEqual([port["name"] for port in payload["ports"]], ["Supply A", "Load B"])
        self.assertEqual(payload["ports"][1]["position"], [.3, .4, -.2])

    def test_viewer_refresh_retains_numeric_exports_and_reports(self):
        self.build()
        retained = {path.name: path.read_bytes() for path in self.output.iterdir() if path.name != "viewer.html"}
        build_results(self.output, self.report, lambda *args, **kwargs: None, viewer_only=True)
        for name, content in retained.items():
            self.assertEqual((self.output / name).read_bytes(), content)
        html = (self.output / "viewer.html").read_text(encoding="utf-8")
        self.assertIn("Salt and Pepper", html)
        self.assertIn("salt-pepper-theme", html)
        self.assertIn('id="themeToggle"', html)

    def test_electrical_only_does_not_export_fake_temperature(self):
        summary, payload, html = self.build()
        self.assertNotIn("temperature_C", payload["field_names"])
        self.assertNotIn("temperature_C", payload["ranges"])
        with np.load(self.output / "surface_fields.npz") as arrays:
            self.assertNotIn("temperature_C", arrays.files)
            np.testing.assert_allclose(arrays["current_density_A_mm2"], [7, 7, 7, 3, 9])
            np.testing.assert_array_equal(arrays["voltage_V"], [5, 4.99, 4.99, 5, 4.99])
        self.assertEqual(payload["ranges"]["ir_drop_mV"], [0, 10])
        self.assertEqual(payload["ranges"]["voltage_V"], [4.99, 5])
        self.assertIn("viewer.html", summary["files"])
        self.assertTrue((self.output / "pad_currents.csv").is_file())
        self.assertNotIn("<script>bad()", html)

    def test_thermal_preserves_nodal_temperature_and_physical_range(self):
        self.report.update(thermal_solved=True, maximum_temperature_C=34)
        _, payload, _ = self.build()
        self.assertEqual(payload["ranges"]["temperature_C"], [30, 75])
        with np.load(self.output / "surface_fields.npz") as arrays:
            np.testing.assert_array_equal(arrays["temperature_C"], np.arange(30., 35.))
        count = sum(len(base64.b64decode(body["faces"])) // 12 for body in payload["bodies"])
        self.assertEqual(count, len(self.surface))

    def test_surface_planes_detected_without_stackup_constants(self):
        nodes = np.array([[0, 0, 8.1], [1, 0, 8.1], [0, 1, 8.1],
                          [0, 0, 8.133], [1, 0, 8.133], [0, 1, 8.133]])
        faces = np.array([[0, 1, 2], [3, 4, 5], [0, 1, 3]])
        groups = _surface_groups(nodes, faces)
        self.assertEqual(len(groups), 3)
        self.assertIn("8.133", groups[0][0])
        self.assertIn("walls", groups[-1][0])
        self.assertEqual(sum(len(triangles) for _, triangles in groups), 3)

    def test_degenerate_mesh_rejected(self):
        nodes = self.nodes.copy()
        nodes[3] = nodes[0]
        with self.assertRaisesRegex(ValueError, "degenerate"):
            _project_elements(nodes, self.tet, {"J": np.array([3., 9.])})


if __name__ == "__main__":
    unittest.main()
