"""Exercise the bundled backend from a temporary directory, without source imports in the child."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from simulation.test_generic_engine import make_bar

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backend',type=Path)
    args=parser.parse_args()
    executable=args.backend.resolve()
    with tempfile.TemporaryDirectory(prefix='salt-pepper-package-test-') as tmp:
        root=Path(tmp);data=root/'data';source=root/'bar.step';make_bar(source)
        with (root/'server.log').open('wb') as log:
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            process=subprocess.Popen([str(executable),'--port','0','--no-browser','--data-dir',str(data)],
                                     cwd=root,env=env,stdout=log,stderr=log)
            base=None;control=None
            try:
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError('Bundled server exited before startup')
                    if (data/'server.json').exists():
                        control=json.loads((data/'server.json').read_text());break
                    time.sleep(.1)
                if not control:raise TimeoutError('Bundled server did not become ready')
                base=f'http://127.0.0.1:{control["port"]}'
                def request(path,value=None,raw=False):
                    payload=value if raw else json.dumps(value).encode() if value is not None else None
                    req=urllib.request.Request(base+path,data=payload)
                    with urllib.request.urlopen(req,timeout=15) as response:return response.read()
                def job_done(key):
                    deadline=time.monotonic()+90
                    while time.monotonic()<deadline:
                        job=json.loads(request('/api/jobs/'+key))
                        if job['status'] in ('succeeded','failed','cancelled'):
                            assert job['status']=='succeeded',job
                            return
                        time.sleep(.1)
                    raise TimeoutError('Bundled worker did not finish')
                assert json.loads(request('/api/health'))['status']=='ok'
                assert b'Clear workspace' in request('/')
                assert b'function displaySolidName' in request('/app.js')
                uploaded=json.loads(request('/api/models?filename=bar.step',source.read_bytes(),raw=True))
                job_done(uploaded['job_id'])
                model=json.loads(request('/api/models/'+uploaded['model_id']))
                rows=sorted(model['inventory']['solids'],key=lambda r:r['centroid_mm'][2])
                assert model['status']=='ready'
                config=dict(model_id=uploaded['model_id'],input_tags=[rows[0]['tag']],output_tags=[rows[-1]['tag']],
                            parameters=dict(analysis_mode='electrothermal',current_A=.1,alpha_per_K=0,
                                            mesh_size_mm=.8,refine=False))
                submitted=json.loads(request('/api/runs',config));job_done(submitted['job_id'])
                run=json.loads(request('/api/runs/'+submitted['run_id']))
                report=run['report']
                assert abs(report['resistance_ohm']-.01/(58e6*1e-6))<1e-9,report['resistance_ohm']
                assert report['maximum_temperature_C']>30
                viewer=request(run['viewer_url'])
                assert b'copperColor' in viewer and b'Colour map' in viewer
                assert any(a['name'].endswith('volume.msh') for a in run['artifacts'])
                request('/api/shutdown',dict(token=control['token']))
                assert process.wait(timeout=15)==0
                assert not (data/'server.json').exists()
                assert (data/'runs'/submitted['run_id']/'fields.npz').is_file()
                print(json.dumps(dict(status='PASS',backend=str(executable),resistance_ohm=report['resistance_ohm'],
                                      maximum_temperature_C=report['maximum_temperature_C'],
                                      checks=['isolated packaged runtime','STEP import and preview','electrothermal worker',
                                              'analytical resistance','result viewer and meshes','graceful shutdown with saved results']),indent=2))
            except Exception:
                log.flush();print((root/'server.log').read_text(errors='replace'),file=sys.stderr);raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

if __name__=='__main__':main()
