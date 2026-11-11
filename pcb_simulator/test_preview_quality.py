"""Smooth small CAD holes independently of the overall board's dimensions."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import gmsh
import numpy as np
from pcb_simulator.engine import inspect_model


def make_ring(path,large=False):
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal',0)
        outside=gmsh.model.occ.addCylinder(0,0,0,0,0,1,.6)
        inside=gmsh.model.occ.addCylinder(0,0,0,0,0,1,.2)
        gmsh.model.occ.cut([(3,outside)],[(3,inside)])
        if large:gmsh.model.occ.addBox(300,0,0,1,1,1)
        gmsh.model.occ.synchronize();gmsh.write(str(path))
    finally:gmsh.finalize()


class PreviewQualityTests(unittest.TestCase):
    def test_hole_resolution_is_independent_of_distant_copper_extent(self):
        counts=[]
        with tempfile.TemporaryDirectory(prefix='pcb-preview-quality-') as temporary:
            folder=Path(temporary)
            for large in [False,True]:
                with self.subTest(large_board_extent=large):
                    source=folder/('large.step' if large else 'compact.step');make_ring(source,large)
                    original=hashlib.sha256(source.read_bytes()).hexdigest();target=folder/str(large)
                    inventory=inspect_model(source,target,lambda *a,**k:None)
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)
                    preview=json.loads((target/'preview.json').read_text())
                    center=np.asarray(preview['center'])
                    self.assertEqual({b['tag'] for b in preview['bodies']},{r['tag'] for r in inventory['solids']})
                    self.assertFalse((target/'preview-surfaces.stl').exists(),'Do not retain a redundant display-mesh artifact.')
                    ring=next(body for body in preview['bodies'] if body['bounds_mm'][0]<0 and body['bounds_mm'][3]<1)
                    for body in preview['bodies']:
                        vertices=np.frombuffer(base64.b64decode(body['vertices_b64']),dtype='<f4').reshape(-1,3)
                        triangles=np.frombuffer(base64.b64decode(body['triangles_b64']),dtype='<u4').reshape(-1,3)
                        self.assertTrue(np.all(np.isfinite(vertices)))
                        self.assertGreater(len(triangles),0)
                        self.assertLess(int(triangles.max()),len(vertices))
                        areas=np.linalg.norm(np.cross(vertices[triangles[:,1]]-vertices[triangles[:,0]],vertices[triangles[:,2]]-vertices[triangles[:,0]]),axis=1)
                        self.assertTrue(np.all(areas>0),'Every encoded triangle must have nonzero area.')
                        absolute=vertices+center;bounds=np.asarray(body['bounds_mm'])
                        self.assertTrue(np.all(absolute.min(axis=0)>=bounds[:3]-2e-5))
                        self.assertTrue(np.all(absolute.max(axis=0)<=bounds[3:]+2e-5))
                        if body is not ring:self.assertEqual(len(triangles),12,'Planar copper should not receive a dense FE display mesh.')
                    vertices=np.frombuffer(base64.b64decode(ring['vertices_b64']),dtype='<f4').reshape(-1,3)+center
                    radii=np.hypot(vertices[:,0],vertices[:,1])
                    boundary=vertices[np.isclose(radii,.2,atol=2e-5)&np.isclose(vertices[:,2],1,atol=2e-5)]
                    angles=np.unique(np.round(np.mod(np.arctan2(boundary[:,1],boundary[:,0]),2*np.pi),5))
                    counts.append(len(angles))
                    self.assertGreaterEqual(len(angles),60,'Small holes need approximately64 segments, even on large boards.')
                    gaps=np.diff(np.r_[angles,angles[0]+2*np.pi])
                    self.assertLess(float(gaps.max()),2*np.pi/48,'Avoid a coarse gap hidden among clustered boundary vertices.')
                    ring_row=next(row for row in inventory['solids'] if row['tag']==ring['tag'])
                    self.assertAlmostEqual(ring_row['volume_mm3'],np.pi*(.6**2-.2**2),places=8)
            self.assertLessEqual(abs(counts[0]-counts[1]),2,'Distant copper must not coarsen the same hole.')
        self.assertFalse(gmsh.isInitialized())


if __name__=='__main__':unittest.main()
