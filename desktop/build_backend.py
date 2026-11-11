"""Build a portable backend with native CAD/FEM libraries, without saved user data."""
from pathlib import Path
import argparse
import subprocess
import os
import sys
import zipfile
import shutil
import plistlib

ROOT=Path(__file__).resolve().parent.parent
DESKTOP=ROOT/'desktop'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example-project',type=Path,help='Include the supplied USB-UART project ZIP as the packaged example.')
    args=parser.parse_args()
    os.environ.setdefault('PYINSTALLER_CONFIG_DIR', str(DESKTOP/'backend-build'/'cache'))
    import gmsh
    subprocess.run([sys.executable, str(ROOT/'tools'/'collect_licenses.py')], check=True)
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile',
             '--console','--name','salt-pepper-backend','--paths',str(ROOT),
             '--distpath',str(DESKTOP/'backend-dist'),
             '--workpath',str(DESKTOP/'backend-build'),
             '--specpath',str(DESKTOP/'backend-build'),
             '--add-data',f'{ROOT / "pcb_simulator" / "static"}:pcb_simulator/static',
             '--add-data',f'{ROOT / "pcb_simulator" / "viewer" / "viewer.template.html"}:pcb_simulator/viewer',
             '--add-data',f'{ROOT / "examples" / "copper-bar.step"}:examples',
             '--add-data',f'{ROOT / "examples" / "two-layer-demo.kicad_pcb"}:examples',
             '--add-data',f'{ROOT / "examples" / "two-layer-demo.kicad_pro"}:examples',
             '--add-binary',f'{gmsh.libpath}:.',
             '--hidden-import','pcb_simulator.worker',
             '--hidden-import','pcb_simulator.engine',
             '--hidden-import','pcb_simulator.results',
             '--hidden-import','pcb_simulator.kicad_preview',
             '--hidden-import','pcb_simulator.kicad_details',
             '--hidden-import','pcb_simulator.kicad_workbench',
             '--hidden-import','pcb_simulator.odb_preview',
             '--hidden-import','pcb_simulator.odb_symbols',
             '--hidden-import','pcb_simulator.workspace_archive',
             '--hidden-import','pcb_simulator.windows_workspace',
             '--hidden-import','pcb_simulator.macos_workspace',
             '--exclude-module','matplotlib',
             '--exclude-module','tkinter',
             str(DESKTOP/'backend_entry.py')]
    if sys.platform=='darwin':
        native=DESKTOP/'backend-build/native';native.mkdir(parents=True,exist_ok=True)
        contents=native/'Workspace Dialog.app/Contents'
        (contents/'MacOS').mkdir(parents=True,exist_ok=True)
        helper=contents/'MacOS/workspace-dialog'
        (contents/'Info.plist').write_bytes(plistlib.dumps(dict(CFBundleExecutable='workspace-dialog',
            CFBundleIdentifier='com.arshahmad.salt-and-pepper.workspace-dialog',
            CFBundleName='Salt and Pepper Workspace',CFBundleDisplayName='Salt and Pepper Workspace',
            CFBundlePackageType='APPL',CFBundleVersion='1',LSUIElement=False,LSMinimumSystemVersion='14.0')))
        subprocess.run(['xcrun','swiftc',str(DESKTOP/'workspace_dialog.swift'),'-O',
                        '-target','arm64-apple-macos14.0','-module-cache-path',str(native/'module-cache'),
                        '-o',str(helper)],check=True)
        subprocess.run(['codesign','--force','--sign','-',str(helper)],check=True)
    if args.example_project:
        archive=args.example_project.expanduser().resolve()
        sample=DESKTOP/'backend-build'/'example-project';sample.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive) as project:
            for name in ('USB-UART.kicad_pcb','USB-UART.kicad_pro'):
                entries=[entry for entry in project.infolist() if not entry.is_dir() and Path(entry.filename).name==name]
                if len(entries)!=1 or entries[0].file_size>16*1024*1024:raise ValueError('Choose the original USB-UART project ZIP with one board and project file.')
                (sample/name).write_bytes(project.read(entries[0]))
        shutil.copyfile(archive,sample/'USB-UART.zip')
        command[-1:-1]=['--add-data',f'{sample / "USB-UART.kicad_pcb"}:examples/USB-UART',
                        '--add-data',f'{sample / "USB-UART.kicad_pro"}:examples/USB-UART',
                        '--add-data',f'{sample / "USB-UART.zip"}:examples']
    subprocess.run(command,cwd=ROOT,check=True)
    if sys.platform=='darwin':
        # A stable signed bundle path avoids registering a fresh temporary app
        # identity each time the one-file backend is extracted on startup.
        destination=DESKTOP/'backend-dist/Workspace Dialog.app'
        if destination.exists():shutil.rmtree(destination)
        shutil.copytree(contents.parent,destination)

if __name__=='__main__':main()
