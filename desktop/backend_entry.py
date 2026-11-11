"""Entry point shared by the bundled server and isolated solver workers."""
import sys
import os
from pathlib import Path

# The native Mac package keeps KiCad beside the frozen Python backend, outside
# PyInstaller's temporary extraction directory. Workers inherit the same path.
if getattr(sys,'frozen',False) and sys.platform in ('darwin','win32'):
    runtime=Path(sys.executable).resolve().parent.parent/'kicad'
    bundled=runtime/'bin'/'kicad-cli.exe' if sys.platform=='win32' else runtime/'Contents'/'MacOS'/'kicad-cli'
    if bundled.is_file():
        os.environ.setdefault('SALT_PEPPER_KICAD_CLI',str(bundled))
        os.environ['SALT_PEPPER_KICAD_BUNDLED']='1'

if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        sys.argv.pop(1)
        from pcb_simulator.worker import main
    else:
        from pcb_simulator.server import main
    raise SystemExit(main())
