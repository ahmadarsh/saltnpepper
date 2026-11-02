"""Native backend integration: HTTP -> worker -> CAD/FEM -> result viewer."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request

from pcb_simulator import server
from simulation.test_generic_engine import make_bar


class BackendTests(unittest.TestCase):
    def test_upload_solve_and_download(self):
        with tempfile.TemporaryDirectory(prefix='pcb_backend_') as temporary:
            root = Path(temporary)
            source = root / 'bar.step'
            make_bar(source)
            with patch.object(server, 'DATA', root / 'data'):
                http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
                workbench = server.Workbench()
                http.workbench = workbench
                http.control_token = 'integration-test'
                thread = threading.Thread(target=http.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{http.server_port}'

                def request(path, data=None):
                    req = urllib.request.Request(base + path, data=data)
                    with urllib.request.urlopen(req, timeout=10) as response:
                        return response.read()

                def poll(job_id):
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        job = json.loads(request('/api/jobs/' + job_id))
                        if job['status'] in ('succeeded', 'failed', 'cancelled'):
                            self.assertEqual(job['status'], 'succeeded', job)
                            return
                        time.sleep(.1)
                    self.fail('Native worker did not finish within 90 seconds')

                try:
                    self.assertIn(b'Salt and Pepper', request('/'))
                    imported = json.loads(request('/api/models?filename=bar.step', source.read_bytes()))
                    poll(imported['job_id'])
                    model = json.loads(request('/api/models/' + imported['model_id']))
                    rows = sorted(model['inventory']['solids'], key=lambda row: row['centroid_mm'][2])
                    config = dict(model_id=imported['model_id'], input_tags=[rows[0]['tag']],
                                  output_tags=[rows[-1]['tag']],
                                  parameters=dict(analysis_mode='electrical', ambient_C=20,
                                                  mesh_size_mm=.8, refine=False))
                    run = json.loads(request('/api/runs', json.dumps(config).encode()))
                    poll(run['job_id'])
                    result = json.loads(request('/api/runs/' + run['run_id']))
                    self.assertAlmostEqual(result['report']['resistance_ohm'], .01 / (58e6 * 1e-6), places=9)
                    self.assertIn(b'<script id="geometry"', request(result['viewer_url']))
                    mesh = next(item for item in result['artifacts'] if item['name'].endswith('/volume.msh'))
                    self.assertIn(b'$MeshFormat', request(mesh['url']))
                    def delete(path, origin=None):
                        headers={'Origin':origin} if origin else {}
                        req=urllib.request.Request(base+path,method='DELETE',headers=headers)
                        with urllib.request.urlopen(req,timeout=10) as response:
                            return json.load(response)
                    with self.assertRaises(urllib.error.HTTPError) as blocked:
                        delete('/api/runs', 'https://untrusted.example')
                    self.assertEqual(blocked.exception.code,403)
                    delete('/api/models/'+imported['model_id'])
                    self.assertIn(b'<script id="geometry"', request(result['viewer_url']))
                    deleted=delete('/api/runs/'+run['run_id'])
                    self.assertEqual(deleted['deleted'],[run['run_id']])
                    self.assertEqual(json.loads(request('/api/runs'))['runs'],[])
                    self.assertEqual(json.loads(request('/api/models'))['models'],[])
                    self.assertFalse((root/'data'/'jobs'/run['job_id']).exists())
                finally:
                    workbench.stop()
                    # Drain the active worker before removing its temporary files.
                    workbench.pending.join()
                    http.shutdown()
                    thread.join(timeout=5)
                    http.server_close()


if __name__ == '__main__':
    unittest.main()
