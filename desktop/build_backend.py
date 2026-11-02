"""Build a portable backend with native CAD/FEM libraries, without saved user data."""
from pathlib import Path
import subprocess
import os
import sys

ROOT=Path(__file__).resolve().parent.parent
DESKTOP=ROOT/'desktop'

def main():
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
             '--add-binary',f'{gmsh.libpath}:.',
             '--hidden-import','pcb_simulator.worker',
             '--hidden-import','pcb_simulator.engine',
             '--hidden-import','pcb_simulator.results',
             '--exclude-module','matplotlib',
             '--exclude-module','tkinter',
             str(DESKTOP/'backend_entry.py')]
    subprocess.run(command,cwd=ROOT,check=True)

if __name__=='__main__':main()
