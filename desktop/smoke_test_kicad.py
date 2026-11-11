"""Smoke-test a packaged backend with a public or private KiCad fixture.

Run with a frozen backend executable, --kicad-cli pointing to its bundled
runtime, and --board pointing to a local KiCad board. The default usb-uart
sample uses the private USB-UART fixture. Use --sample demo with the original
examples/two-layer-demo.kicad_pcb for public CI. Fixtures are uploaded at runtime.
The backend runs from a fresh temporary working directory without PYTHONPATH.
This checks the HTTP workflow and real solver; it does not automate a GUI.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backend', type=Path, help='Frozen salt-pepper-backend executable')
    parser.add_argument('--kicad-cli', type=Path, required=True, help='Bundled KiCad CLI executable')
    parser.add_argument('--board', type=Path, required=True, help='Local .kicad_pcb fixture matching --sample')
    parser.add_argument('--sample', choices=['usb-uart', 'demo'], default='usb-uart', help='Fixture expectations (default: private USB-UART; demo is suitable for public CI)')
    parser.add_argument('--report', type=Path, help='Optional JSON verification report')
    parser.add_argument('--timeout', type=float, default=1200, help='Maximum seconds per worker job')
    args = parser.parse_args()
    executable, cli, source = (p.expanduser().resolve() for p in (args.backend, args.kicad_cli, args.board))
    for label, path in [('backend', executable), ('KiCad CLI', cli), ('board', source)]:
        if not path.is_file():
            parser.error(f'{label} does not exist: {path}')
    if not os.access(executable, os.X_OK) or not os.access(cli, os.X_OK):
        parser.error('The backend and bundled KiCad CLI must be executable.')
    if source.suffix.lower() != '.kicad_pcb':
        parser.error('--board must point to the extracted .kicad_pcb file.')
    if args.timeout <= 0:
        parser.error('--timeout must be positive.')
    sample = {
        'usb-uart': dict(nets=18, pads=96, net='VCC_3V3', selected_pads=5,
                         input=('U1', '8'), output=('JP1', '1')),
        'demo': dict(nets=1, pads=2, net='DEMO_POWER', selected_pads=2,
                     input=('J1', '1'), output=('J2', '1'))
    }[args.sample]
    input_label = f"{sample['input'][0]} · Pad {sample['input'][1]}"
    output_label = f"{sample['output'][0]} · Pad {sample['output'][1]}"
    result = dict(status='FAIL', sample=args.sample, backend=str(executable), kicad_cli=str(cli), checks=[])
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='salt-pepper-kicad-package-test-') as tmp:
            root = Path(tmp)
            data = root / 'data'
            with (root / 'server.log').open('wb') as log:
                env = dict(os.environ)
                env.pop('PYTHONPATH', None)
                env.pop('PYTHONHOME', None)
                env['SALT_PEPPER_KICAD_CLI'] = str(cli)
                process = subprocess.Popen(
                    [str(executable), '--port', '0', '--no-browser', '--data-dir', str(data)],
                    cwd=root, env=env, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                control = None
                base = None
                try:
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError('Packaged backend exited before startup.')
                        try:
                            control = json.loads((data / 'server.json').read_text())
                            break
                        except (OSError, ValueError):
                            time.sleep(.1)
                    if not control:
                        raise TimeoutError('Packaged backend did not become ready.')
                    base = f'http://127.0.0.1:{control["port"]}'

                    def request(path, value=None, raw=False):
                        payload = value if raw else json.dumps(value).encode() if value is not None else None
                        headers = {'Content-Type': 'application/octet-stream' if raw else 'application/json'}
                        req = urllib.request.Request(base + path, data=payload, headers=headers)
                        with urllib.request.urlopen(req, timeout=30) as response:
                            return response.read()

                    def api(path, value=None):
                        return json.loads(request(path, value))

                    def job_done(key):
                        end = time.monotonic() + args.timeout
                        while time.monotonic() < end:
                            if process.poll() is not None:
                                raise RuntimeError('Packaged backend exited during a worker job.')
                            job = api('/api/jobs/' + key)
                            if job['status'] in ('succeeded', 'failed', 'cancelled'):
                                require(job['status'] == 'succeeded', f'Worker failed: {json.dumps(job)}')
                                return job
                            time.sleep(.2)
                        raise TimeoutError(f'Worker {key} exceeded {args.timeout:g} seconds.')

                    def svg(path):
                        document = ET.fromstring(request(path))
                        require(document.tag.endswith('svg'), f'Not an SVG: {path}')
                        require(len(list(document.iter())) > 1, f'Empty SVG: {path}')
                        return document

                    require(api('/api/health')['status'] == 'ok', 'Health endpoint failed.')
                    status = api('/api/kicad/status')
                    require(status['available'], f'Bundled KiCad unavailable: {status}')
                    result['kicad_version'] = status['version']
                    result['checks'].append('isolated packaged backend and bundled KiCad runtime')
                    require(b'kcPrepare' in request('/kicad.js'), 'KiCad frontend missing from bundle.')
                    uploaded = json.loads(request('/api/kicad/boards?filename=' + urllib.parse.quote(source.name), source.read_bytes(), raw=True))
                    job_done(uploaded['job_id'])
                    board_base = '/api/kicad/boards/' + uploaded['board_id']
                    board = api(board_base)['board']
                    require(len(board['nets']) == sample['nets'] and len(board['pads']) == sample['pads'], f'{args.sample} net/pad inventory changed.')
                    require(board['details']['copper_layer_count'] == 2, 'Expected two copper layers.')
                    require(math.isclose(board['details']['board_thickness_mm'], 1.6), 'Expected 1.6 mm board thickness.')
                    require(len(board['details']['stackup']) == 9, 'Expected complete nine-entry stackup.')
                    for side in ['top', 'bottom']:
                        svg(board_base + '/full/' + side + '.svg')
                    require(len({n['colour'] for n in board['nets']}) == sample['nets'], 'Automatic net colours are not distinct.')
                    for side in ['top','bottom']:
                        document=svg(board_base+'/coloured/'+side+'.svg')
                        groups=[item for item in document.iter() if 'data-net-key' in item.attrib]
                        require({item.attrib['data-net-key'] for item in groups}=={net['plot_key'] for net in board['nets']},'Combined copper SVG lost net identities.')
                    require(board['import_timings']['kicad_exports']==1,'Expected one native ODB export.')
                    result['checks'].append(f"two combined native SVGs, {sample['nets']} net identities, {sample['pads']} pads and complete stackup")

                    net_name = sample['net']
                    selection = api(board_base + '/select', dict(net=net_name))
                    job_done(selection['job_id'])
                    export_base = board_base + '/exports/' + selection['export_id']
                    selected = api(export_base + '/selection.json')
                    require(len(selected['pads']) == sample['selected_pads'], f'{net_name} pad inventory changed.')
                    for side in ['top', 'bottom']:
                        svg(export_base + '/highlight/' + side + '.svg')
                    def pad(reference, number):
                        matches = [p for p in selected['pads'] if p['reference'] == reference and p['number'] == number]
                        require(len(matches) == 1, f'Ambiguous terminal {reference}.{number}')
                        return matches[0]
                    input_pad, output_pad = pad(*sample['input']), pad(*sample['output'])
                    require(input_pad['sides'] == ['top'] and output_pad['sides'] == ['bottom'], 'Expected a top-side input and bottom-side output.')
                    prepared = api(board_base + '/prepare', dict(net=net_name, input_ids=[input_pad['id']], output_ids=[output_pad['id']]))
                    job_done(prepared['job_id'])
                    export_base = board_base + '/exports/' + prepared['export_id']
                    handoff = api(export_base + '/handoff.json')
                    require(handoff['solver_connected'], 'KiCad geometry was not connected to the solver workbench.')
                    terminal_names = {(t['role'], t['label']) for t in handoff['terminals']}
                    require(terminal_names == {('input', input_label), ('output', output_label)}, 'Named terminal roles changed.')
                    model = api('/api/models/' + prepared['model_id'])
                    require(model['status'] == 'ready' and model['origin'] == 'kicad' and model['source_file'] == 'source.xao', 'Expected ready KiCad XAO workbench model.')
                    inventory = model['inventory']
                    inputs, outputs = inventory['default_input_tags'], inventory['default_output_tags']
                    by_tag = {row['tag']: row for row in inventory['solids']}
                    require(len(inputs) == len(outputs) == 1, 'Expected one input and one output default.')
                    require(by_tag[inputs[0]]['name'] == input_label and by_tag[outputs[0]]['name'] == output_label, 'Geometry terminal names do not match the chosen pads.')
                    require(all(by_tag[t].get('electrode_faces') for t in inputs + outputs), 'Selected pads lost named electrode faces.')
                    preview = api('/api/models/' + prepared['model_id'] + '/preview.json')
                    require(bool(preview['bodies']), 'Workbench geometry preview is empty.')
                    require((data / 'models' / prepared['model_id'] / 'source.xao').is_file(), 'Workbench did not retain XAO source.')
                    result['checks'].append(f'{net_name} native copper export and direct Geometry workbench with named {input_label}/{output_label} electrodes')

                    submitted = api('/api/runs', dict(model_id=prepared['model_id'], input_tags=inputs, output_tags=outputs,
                        parameters=dict(analysis_mode='electrothermal', voltage_V=3.3, current_A=.1,
                                        mesh_size_mm=.8, refine=True, refinement_factor=.6)))
                    job_done(submitted['job_id'])
                    run = api('/api/runs/' + submitted['run_id'])
                    report = run['report']
                    require(report['thermal_solved'] and math.isfinite(report['resistance_ohm']) and report['resistance_ohm'] > 0, 'Electrothermal solution is invalid.')
                    require(report['maximum_temperature_C'] > report['room_temperature_C'], 'Expected positive Joule heating.')
                    require(math.isclose(report['total_current_A'], .1, rel_tol=1e-8), 'Requested current was not retained.')
                    require(report['refinement']['enabled'] and len(report['refinement']['runs']) == 2, 'Expected two mesh refinement passes.')
                    require(all(abs(report['checks'][key]) < 1e-5 for key in ['relative_current_imbalance', 'relative_linear_residual', 'relative_electrical_power_error']), 'Electrical conservation/residual checks failed.')
                    require({(p['role'],p['name']) for p in report['per_pad']} == terminal_names, 'Solver report lost named terminal roles.')
                    viewer = request(run['viewer_url'])
                    require(b'copperColor' in viewer and b'Colour map' in viewer, 'Result viewer is missing controls.')
                    artifact_names = {item['name'] for item in run['artifacts']}
                    require('fields.npz' in artifact_names and 'refinement.json' in artifact_names, 'Result fields or refinement report are missing.')
                    require(sum(name.endswith('/volume.msh') for name in artifact_names) == 2, 'Expected both refinement volume meshes.')
                    require(len(request('/artifacts/' + submitted['run_id'] + '/fields.npz')) > 100, 'Downloaded simulation fields are empty.')
                    result.update(resistance_ohm=report['resistance_ohm'], maximum_temperature_C=report['maximum_temperature_C'],
                                  tetrahedra=report['tetrahedra'], refinement_runs=report['refinement']['runs'])
                    result['checks'].append('real 0.1 A electrothermal FEM, two refinement meshes, named per-pad report and downloadable results/viewer')
                    request('/api/shutdown', dict(token=control['token']))
                    require(process.wait(timeout=20) == 0, 'Packaged backend did not exit cleanly.')
                    require(not (data / 'server.json').exists(), 'Server control file was not removed.')
                    require((data / 'runs' / submitted['run_id'] / 'fields.npz').is_file(), 'Shutdown did not preserve results.')
                    result['checks'].append('graceful shutdown with saved results')
                    result['status'] = 'PASS'
                except Exception:
                    log.flush()
                    print((root / 'server.log').read_text(errors='replace')[-12000:], file=sys.stderr)
                    for path in sorted((data / 'jobs').glob('*/worker.log')):
                        print(str(path) + '\n' + path.read_text(errors='replace')[-6000:], file=sys.stderr)
                    raise
                finally:
                    if process.poll() is None and base and control:
                        try:
                            request('/api/shutdown', dict(token=control['token']))
                            process.wait(timeout=15)
                        except Exception:
                            pass
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill(); process.wait(timeout=5)
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        result['elapsed_seconds'] = round(time.monotonic() - started, 2)
        if args.report:
            target = args.report.expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
