"""Meaningful analytical and STEP-to-FEM regression checks; no Blender access."""
import json
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from pcb_simulator.engine import gmsh, np, inspect_model, run_simulation
from simulation.solve_3v3_thermal import thermal_benchmark


def emit(stage,message,**kw):
    print(f'{stage}: {message}',flush=True)


def make_bar(path,disconnected=False):
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal',0)
        gmsh.model.add('Analytical vertical copper bar')
        gmsh.model.occ.addBox(0,0,0,1,1,1)
        gmsh.model.occ.addBox(0,0,1,1,1,8 if not disconnected else 7)
        gmsh.model.occ.addBox(0,0,9,1,1,1)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:gmsh.finalize()


def main():
    thermal_benchmark()
    with tempfile.TemporaryDirectory(prefix='pcb_engine_test_') as temp:
        root=Path(temp);source=root/'bar.step';make_bar(source)
        inv=inspect_model(source,root/'inspection',emit)
        # The same numeric STEP coordinates declared in meters represent a
        # physically 1000x larger body. Import must convert the declared units.
        step_text=source.read_text()
        assert 'SI_UNIT(.MILLI.,.METRE.)' in step_text
        meters=root/'meter_bar.step'
        meters.write_text(step_text.replace('SI_UNIT(.MILLI.,.METRE.)','SI_UNIT($,.METRE.)'))
        meter_inv=inspect_model(meters,root/'meter_inspection',emit)
        meter_extent=np.asarray(meter_inv['bounds_mm'])[3:]-np.asarray(meter_inv['bounds_mm'])[:3]
        assert np.allclose(meter_extent,[1000,1000,10000],rtol=1e-8),meter_extent
        assert np.isclose(sum(r['volume_mm3'] for r in meter_inv['solids']),10e9,rtol=1e-8)
        rows=sorted(inv['solids'],key=lambda r:r['centroid_mm'][2]);inputs=[rows[0]['tag']];outputs=[rows[-1]['tag']]
        p=dict(analysis_mode='electrical',ambient_C=20,mesh_size_mm=.8,refine=True)
        report=run_simulation(source,inv,root/'electrical',inputs,outputs,p,emit)
        expected=.01/(58e6*1e-6)
        assert np.isclose(report['resistance_ohm'],expected,rtol=2e-6),(report['resistance_ohm'],expected)
        assert report['thermal_solved'] is False and report['maximum_temperature_C'] is None
        with np.load(root/'electrical'/'fields.npz') as f:assert 'temperature_C' not in f.files
        assert report['refinement']['relative_resistance_change']<1e-6
        ports=json.loads((root/'electrical'/'ports.json').read_text())['ports']
        assert ports[0]['face']=='bottom' and ports[1]['face']=='top'
        assert np.isclose(sum(pad['current_A'] for pad in report['per_pad']),0,atol=1e-8)
        thermal=run_simulation(source,inv,root/'thermal',inputs,outputs,
            dict(mesh_size_mm=.7,refine=False,current_A=.1,ambient_C=30,alpha_per_K=0),emit)
        assert thermal['thermal_solved'] and thermal['maximum_temperature_C']>30
        assert thermal['relative_thermal_power_error']<1e-6
        # With alpha=0, heat is uniform and equal end convection gives analytical
        # center rise q*L/(2h)+q*L^2/(8k). Linear elements converge from below.
        q=(.1/1e-6)**2/58e6
        exact_rise=q*.01/(2*5)+q*.01**2/(8*400)
        assert np.isclose(thermal['temperature_rise_C'],exact_rise,rtol=1e-3),(thermal['temperature_rise_C'],exact_rise)
        broken=root/'broken.step';make_bar(broken,True)
        broken_inv=inspect_model(broken,root/'broken_inspect',emit)
        try:run_simulation(broken,broken_inv,root/'broken_run',inputs,outputs,dict(analysis_mode='electrical',refine=False),emit)
        except ValueError as exc:assert 'disconnected' in str(exc),str(exc)
        else:raise AssertionError('Disconnected copper unexpectedly solved')
        assert (root/'broken_run'/'mesh_01_1mm'/'volume.msh').is_file()
        assert (root/'broken_run'/'mesh_01_1mm'/'ports.json').is_file()
        print(json.dumps(dict(status='PASS',bar_resistance_ohm=report['resistance_ohm'],analytical_resistance_ohm=expected,
            thermal_rise_C=thermal['temperature_rise_C'],analytical_thermal_rise_C=exact_rise,
            tested=['STEP import/preview','STEP meter-to-millimeter conversion','single conductor','exact electrical bar','two meshes','electrical-only fields',
                    'AUTO bottom/top faces','thermal bar analytical solution','disconnected rejection with saved mesh/ports'])),flush=True)


if __name__=='__main__':main()
