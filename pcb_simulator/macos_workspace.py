"""Native AppKit Open/Save panels; file writing remains in the archive layer."""
import json
import os
from pathlib import Path
import subprocess
import sys


def choose_workspace_path(name='Workspace',initial_directory=None,owner_pid=None,open_existing=False):
    from pcb_simulator.windows_workspace import suggested_filename
    if sys.platform!='darwin':raise RuntimeError('AppKit workspace dialogs require macOS.')
    if getattr(sys,'frozen',False):
        helper=Path(sys.executable).parent/'Workspace Dialog.app/Contents/MacOS/workspace-dialog'
    else:
        helper=Path(__file__).resolve().parent.parent/'desktop/backend-build/native/Workspace Dialog.app/Contents/MacOS/workspace-dialog'
    if not helper.is_file() or not os.access(helper,os.X_OK):
        raise RuntimeError('The native workspace dialog is missing. Rebuild or reinstall the Mac app.')
    command=[str(helper)]
    if open_existing:command.append('--open')
    else:command.extend(['--name',suggested_filename(name)])
    if initial_directory and Path(initial_directory).is_dir():command.extend(['--directory',str(initial_directory)])
    if owner_pid:command.extend(['--owner-pid',str(int(owner_pid))])
    # No timeout: a user may spend as long as needed browsing the native panel.
    result=subprocess.run(command,capture_output=True,text=True)
    if result.returncode:raise RuntimeError('The native workspace dialog could not open: '+result.stderr[-500:])
    try:value=json.loads(result.stdout)
    except (ValueError,TypeError):raise RuntimeError('The native workspace dialog returned an invalid response.')
    if value.get('status')=='cancelled':return None
    path=Path(value.get('path',''))
    if value.get('status')!='selected' or not path.is_absolute() or path.suffix.lower()!='.pepper':
        raise ValueError('Choose a filename ending in .pepper.')
    return path
