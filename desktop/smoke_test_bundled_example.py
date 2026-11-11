"""Verify a self-contained desktop package using its embedded USB-UART example.

The frozen backend runs from a temporary directory with Python/KiCad overrides
removed. No external board, project, ZIP, or KiCad installation is supplied.
This exercises real native import, named geometry handoff and refined FEM.
"""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


def require(value, message):
    if not value:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backend', type=Path, help='Frozen backend with ../kicad runtime adjacent to its backend directory')
    parser.add_argument('--report', type=Path, help='Optional JSON verification report')
    parser.add_argument('--timeout', type=float, default=1200, help='Maximum seconds per worker job')
    args = parser.parse_args()
    executable = args.backend.expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        parser.error('backend must be an executable frozen backend file')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    bundled_cli = executable.parent.parent / 'kicad' / ('bin/kicad-cli.exe' if sys.platform=='win32' else 'Contents/MacOS/kicad-cli')
    if not bundled_cli.is_file():
        parser.error('The adjacent bundled KiCad runtime is missing: ' + str(bundled_cli))
    result = dict(status='FAIL', backend=str(executable), kicad_cli=str(bundled_cli), checks=[])
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='salt-pepper-embedded-example-test-') as tmp:
            root = Path(tmp)
            data = root / 'data'
            with (root / 'server.log').open('wb') as log:
                env = dict(os.environ)
                for name in list(env):
                    if name.startswith('SALT_PEPPER_KICAD_') or name in ('PYTHONPATH', 'PYTHONHOME', 'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH'):
                        env.pop(name, None)
                if sys.platform=='win32':
                    system=Path(env.get('SystemRoot',r'C:\Windows'))
                    env['PATH']=os.pathsep.join(map(str,[system/'System32',system]))
                else:env['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
                command=[str(executable), '--port', '0', '--no-browser', '--data-dir', str(data)]
                if sys.platform in ('darwin','win32'):command.append('--native-workspace-dialogs')
                process = subprocess.Popen(
                    command,
                    cwd=root, env=env, stdout=log, stderr=log)
                control = None
                base = None
                try:
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError('Packaged backend exited before startup.')
                        try:
                            control = json.loads((data / 'server.json').read_text())
                            break
                        except (OSError, ValueError):
                            time.sleep(.1)
                    require(control, 'Packaged backend did not become ready.')
                    base = f'http://127.0.0.1:{control["port"]}'

                    def fetch(path, value=None, raw=False, with_headers=False):
                        payload = value if raw else json.dumps(value).encode() if value is not None else None
                        headers = {'Content-Type': 'application/octet-stream' if raw else 'application/json'}
                        request = urllib.request.Request(base + path, data=payload, headers=headers)
                        with urllib.request.urlopen(request, timeout=210) as response:
                            body = response.read()
                            return (body, response.headers) if with_headers else body

                    def api(path, value=None):
                        return json.loads(fetch(path, value))

                    def job_done(key):
                        deadline = time.monotonic() + args.timeout
                        while time.monotonic() < deadline:
                            require(process.poll() is None, 'Backend exited during a worker job.')
                            job = api('/api/jobs/' + key)
                            if job['status'] in ('succeeded', 'failed', 'cancelled'):
                                require(job['status'] == 'succeeded', 'Worker failed: ' + json.dumps(job))
                                return job
                            time.sleep(.2)
                        raise TimeoutError(f'Worker {key} exceeded {args.timeout:g} seconds.')

                    require(api('/api/health')['status'] == 'ok', 'Health endpoint failed.')
                    page = fetch('/')
                    require(all(marker in page for marker in [b'newWorkspaceCard', b'openWorkspaceCard', b'setupKiCadImport', b'data-nav="kicad"']),
                            'Packaged GUI is missing workspace or KiCad import entry points.')
                    require(b'function workspaceSaveNamed' in fetch('/workspace.js'), 'Workspace controls were not packaged.')
                    require(api('/api/workspace/capabilities')['native_save']==(sys.platform in ('darwin','win32')),
                            'Packaged native Save capability does not match the platform.')
                    status = api('/api/kicad/status')
                    require(status.get('available') and status.get('bundled') is True,
                            'Automatic bundled KiCad selection failed: ' + json.dumps(status))
                    result['kicad_version'] = status['version']
                    result['checks'].append('isolated frozen backend automatically selects its bundled KiCad without override or user PATH')

                    pcb, headers = fetch('/api/kicad/example', with_headers=True)
                    require(headers.get_filename() == 'USB-UART.kicad_pcb' and 'attachment' in headers.get('Content-Disposition', ''),
                            'Try example did not serve USB-UART with the correct attachment filename.')
                    require(pcb.lstrip().startswith(b'(kicad_pcb'), 'Embedded example is not a KiCad PCB.')
                    project = api('/api/kicad/example-project')
                    require(isinstance(project.get('net_settings'), dict), 'Embedded companion project lacks net settings.')
                    archive, zip_headers = fetch('/api/kicad/example-project.zip', with_headers=True)
                    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                        members = [m for m in zipped.infolist() if not m.is_dir()]
                        expected = {'.history/README.txt', 'USB-A.kicad_sym', 'USB-UART.kicad_pcb',
                                    'USB-UART.kicad_prl', 'USB-UART.kicad_pro', 'USB-UART.kicad_sch'}
                        require(len(members) == 6 and {m.filename for m in members} == expected,
                                'Embedded ZIP does not contain the six original USB-UART project files.')
                        require(all(m.file_size > 0 for m in members) and zipped.testzip() is None,
                                'Embedded ZIP has empty or damaged project members.')
                        require(zipped.read('USB-UART.kicad_pcb') == pcb, 'Embedded PCB differs from the bundled project ZIP.')
                        require(json.loads(zipped.read('USB-UART.kicad_pro')) == project, 'Embedded project differs from the bundled ZIP.')
                    result.update(example_bytes=len(pcb), project_zip_bytes=len(archive), project_zip_files=6)
                    result['checks'].append('embedded USB-UART PCB, companion project and intact six-file project ZIP match')

                    print('[smoke] Importing the bundled USB-UART board.', flush=True)
                    uploaded = json.loads(fetch('/api/kicad/boards?filename=USB-UART.kicad_pcb', pcb, raw=True))
                    job_done(uploaded['job_id'])
                    board_base = '/api/kicad/boards/' + uploaded['board_id']
                    board = api(board_base)['board']
                    require(len(board['nets']) == 18 and len(board['pads']) == 96, 'Bundled USB-UART net/pad inventory changed.')
                    require(board['sha256'] == hashlib.sha256(pcb).hexdigest(), 'Imported board hash differs from the embedded example.')
                    require(board['details']['copper_layer_count'] == 2 and len(board['details']['stackup']) == 9,
                            'Expected a complete two-layer, nine-entry USB-UART stackup.')
                    require(math.isclose(board['details']['board_thickness_mm'], 1.6), 'Expected 1.6 mm board thickness.')
                    require(board.get('preview_source') == 'native_odb_connectivity', 'Preview did not use exact native ODB connectivity.')
                    require(board['import_timings']['kicad_exports'] == 1, 'Import performed more than one KiCad export.')
                    require(set(board['colour_layers']) == {'top', 'bottom'}, 'Both combined copper layers are required.')
                    require(len({n['colour'] for n in board['nets']}) == 18, 'Automatic net colours should be distinct.')
                    ns = '{http://www.w3.org/2000/svg}'
                    for side in ['top', 'bottom']:
                        for folder in ['full', 'coloured']:
                            document = ET.fromstring(fetch(board_base + '/' + folder + '/' + side + '.svg'))
                            require(document.tag == ns + 'svg', 'Invalid native copper SVG.')
                            if folder == 'coloured':
                                groups = [g for g in document.iter(ns + 'g') if 'data-net-key' in g.attrib]
                                require(len(groups) == 18, 'Combined SVG lost native net groups.')
                                require(all(g.attrib.get('fill') == 'currentColor' for g in groups), 'Native pad colours do not inherit net colours.')
                                require({g.attrib['data-net-key'] for g in groups} == {n['plot_key'] for n in board['nets']},
                                        'Combined SVG group identities differ from the net list.')
                    imported_folder = data / 'boards' / uploaded['board_id']
                    require(not (imported_folder / 'nets').exists(), 'Import generated per-net export folders.')
                    commands = [line for line in (imported_folder / 'kicad-cli.log').read_text().splitlines() if line.startswith('pcb export ')]
                    require(len(commands) == 1 and commands[0].startswith('pcb export odb '),
                            'Native import log does not contain exactly one ODB export.')
                    coloured = api(board_base + '/colours', project)
                    require(len(coloured['board']['nets']) == 18, 'Companion project colour import changed net inventory.')
                    result['import_timings'] = board['import_timings']
                    result['checks'].append('18 nets, 96 pads, real stackup and two combined net SVGs from exactly one native ODB export')

                    selection = api(board_base + '/select', dict(net='VCC_3V3'))
                    job_done(selection['job_id'])
                    selected = api(board_base + '/exports/' + selection['export_id'] + '/selection.json')
                    require(len(selected['pads']) == 5, 'VCC_3V3 should expose five pads.')
                    def pad(reference, number, side):
                        matches = [p for p in selected['pads'] if p['reference'] == reference and p['number'] == number]
                        require(len(matches) == 1 and matches[0]['sides'] == [side], f'Invalid terminal {reference}.{number}')
                        return matches[0]['id']
                    print('[smoke] Preparing U1.8 input and JP1.1 output.', flush=True)
                    prepared = api(board_base + '/prepare', dict(net='VCC_3V3', input_ids=[pad('U1', '8', 'top')], output_ids=[pad('JP1', '1', 'bottom')]))
                    job_done(prepared['job_id'])
                    handoff = api(board_base + '/exports/' + prepared['export_id'] + '/handoff.json')
                    expected_terminals = {('input', 'U1 · Pad 8'), ('output', 'JP1 · Pad 1')}
                    require(handoff['solver_connected'] and {(t['role'], t['label']) for t in handoff['terminals']} == expected_terminals,
                            'Native geometry handoff lost the selected named terminals.')
                    model = api('/api/models/' + prepared['model_id'])
                    require(model['status'] == 'ready' and model['origin'] == 'kicad' and model['source_file'] == 'source.xao',
                            'Expected a ready KiCad XAO model in the Geometry workbench.')
                    inventory = model['inventory']
                    inputs, outputs = inventory['default_input_tags'], inventory['default_output_tags']
                    rows = {row['tag']: row for row in inventory['solids']}
                    require(len(inputs) == len(outputs) == 1 and rows[inputs[0]]['name'] == 'U1 · Pad 8' and rows[outputs[0]]['name'] == 'JP1 · Pad 1',
                            'Geometry terminal defaults differ from the chosen pads.')
                    require(all(rows[tag].get('electrode_faces') for tag in inputs + outputs), 'Named electrode faces were lost.')
                    require(bool(api('/api/models/' + prepared['model_id'] + '/preview.json')['bodies']), 'Geometry preview is empty.')
                    result['checks'].append('VCC_3V3 XAO prepares direct Geometry model with U1.8/JP1.1 names, roles and electrode faces')

                    print('[smoke] Running refined 0.1 A electrothermal FEM.', flush=True)
                    submitted = api('/api/runs', dict(model_id=prepared['model_id'], input_tags=inputs, output_tags=outputs,
                        parameters=dict(analysis_mode='electrothermal', voltage_V=3.3, current_A=.1,
                                        mesh_size_mm=.8, refine=True, refinement_factor=.6)))
                    job_done(submitted['job_id'])
                    run = api('/api/runs/' + submitted['run_id'])
                    report = run['report']
                    require(report['thermal_solved'] and math.isfinite(report['resistance_ohm']) and report['resistance_ohm'] > 0,
                            'Electrothermal solution is invalid.')
                    require(report['maximum_temperature_C'] > report['room_temperature_C'], 'Expected positive Joule heating.')
                    require(math.isclose(report['total_current_A'], .1, rel_tol=1e-8), 'Requested current was not retained.')
                    require(report['refinement']['enabled'] and len(report['refinement']['runs']) == 2, 'Expected two refinement passes.')
                    require(all(abs(report['checks'][key]) < 1e-5 for key in ['relative_current_imbalance', 'relative_linear_residual', 'relative_electrical_power_error']),
                            'Electrical conservation/residual checks failed.')
                    require({(p['role'], p['name']) for p in report['per_pad']} == expected_terminals, 'Solver report lost named terminal roles.')
                    viewer = fetch(run['viewer_url'])
                    require(b'copperColor' in viewer and b'Colour map' in viewer, 'Result viewer is missing controls.')
                    artifacts = {item['name'] for item in run['artifacts']}
                    require('fields.npz' in artifacts and 'refinement.json' in artifacts, 'Result fields/refinement report are missing.')
                    require(sum(name.endswith('/volume.msh') for name in artifacts) == 2, 'Expected both refinement volume meshes.')
                    require(len(fetch('/artifacts/' + submitted['run_id'] + '/fields.npz')) > 100, 'Simulation field download is empty.')
                    result.update(resistance_ohm=report['resistance_ohm'], maximum_temperature_C=report['maximum_temperature_C'],
                                  tetrahedra=report['tetrahedra'], refinement_runs=report['refinement']['runs'])
                    result['checks'].append('real electrothermal solution, two refined meshes, conserved named terminals and downloadable viewer/fields')
                    print('[smoke] Saving and reopening the packaged .pepper workspace.', flush=True)
                    workspace = fetch('/api/workspace/export', dict(board_id=uploaded['board_id'], model_id=prepared['model_id'],
                        name='Packaged USB-UART test', ui_state=dict(model_input_tags=inputs, model_output_tags=outputs)))
                    with zipfile.ZipFile(io.BytesIO(workspace)) as saved:
                        require(saved.testzip() is None, 'Workspace archive integrity failed.')
                        manifest = json.loads(saved.read('manifest.json'))
                        require(len(manifest['runs']) == 1, 'Workspace did not include the completed run.')
                    restored = json.loads(fetch('/api/workspace/import?filename=packaged-test.pepper', workspace, raw=True))
                    require(restored['board_id'] != uploaded['board_id'] and restored['model_id'] != prepared['model_id'],
                            'Workspace restore did not allocate isolated IDs.')
                    require(len(restored['runs']) == 1 and api('/api/models/' + restored['model_id'])['status'] == 'ready',
                            'Workspace did not restore the prepared model and run.')
                    require(api('/api/kicad/boards/' + restored['board_id'])['board']['nets'], 'Restored board inventory is missing.')
                    result['workspace_bytes'] = len(workspace)
                    result['checks'].append('packaged New/Open/KiCad controls and portable workspace export/import with model, board and completed results')
                    fetch('/api/shutdown', dict(token=control['token']))
                    require(process.wait(timeout=20) == 0, 'Packaged backend did not exit cleanly.')
                    require(not (data / 'server.json').exists(), 'Server control file was not removed.')
                    require((data / 'runs' / submitted['run_id'] / 'fields.npz').is_file(), 'Shutdown did not retain results.')
                    result['checks'].append('graceful shutdown retaining saved results')
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
                            fetch('/api/shutdown', dict(token=control['token']))
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
