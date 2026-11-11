"""Native workspace persistence shared by desktop platforms; Win32 picker."""
from __future__ import annotations
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


def suggested_filename(name):
    name=str(name or 'Workspace').replace('\\','/').rsplit('/',1)[-1]
    if name.lower().endswith('.pepper'):name=name[:-7]
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name).strip(' .')[:100] or 'Workspace'
    if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]',name.split('.')[0],re.I):name='Workspace-'+name
    return name+'.pepper'


def choose_workspace_path(name='Workspace',initial_directory=None,owner_pid=None,open_existing=False):
    """Return the exact user-confirmed path, or None on Cancel.

    GetSaveFileNameW handles Unicode, folder navigation and overwrite approval.
    The desktop shell's window owns the dialog, so it stays in front of the app.
    """
    if sys.platform=='darwin':
        from pcb_simulator.macos_workspace import choose_workspace_path as mac_picker
        return mac_picker(name,initial_directory,owner_pid,open_existing)
    if sys.platform!='win32':raise RuntimeError('Native workspace saving requires a Mac or Windows desktop build.')
    import ctypes
    from ctypes import wintypes as w
    user=ctypes.WinDLL('user32',use_last_error=True)
    common=ctypes.WinDLL('comdlg32',use_last_error=True)
    class OPENFILENAMEW(ctypes.Structure):
        _fields_=[('lStructSize',w.DWORD),('hwndOwner',w.HWND),('hInstance',w.HINSTANCE),
            ('lpstrFilter',w.LPCWSTR),('lpstrCustomFilter',w.LPWSTR),('nMaxCustFilter',w.DWORD),
            ('nFilterIndex',w.DWORD),('lpstrFile',w.LPWSTR),('nMaxFile',w.DWORD),
            ('lpstrFileTitle',w.LPWSTR),('nMaxFileTitle',w.DWORD),('lpstrInitialDir',w.LPCWSTR),
            ('lpstrTitle',w.LPCWSTR),('Flags',w.DWORD),('nFileOffset',w.WORD),('nFileExtension',w.WORD),
            ('lpstrDefExt',w.LPCWSTR),('lCustData',ctypes.c_ssize_t),('lpfnHook',ctypes.c_void_p),
            ('lpTemplateName',w.LPCWSTR),('pvReserved',ctypes.c_void_p),('dwReserved',w.DWORD),('FlagsEx',w.DWORD)]
    owner=0
    if owner_pid:
        found=[];callback_type=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
        user.GetWindowThreadProcessId.restype=w.DWORD
        user.IsWindowVisible.argtypes=[w.HWND];user.IsWindowVisible.restype=w.BOOL
        @callback_type
        def visit(hwnd,param):
            pid=w.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==owner_pid and user.IsWindowVisible(hwnd):found.append(hwnd);return False
            return True
        user.EnumWindows.argtypes=[callback_type,w.LPARAM];user.EnumWindows.restype=w.BOOL
        user.EnumWindows(visit,0)
        if found:owner=found[0]
    buffer=ctypes.create_unicode_buffer('' if open_existing else suggested_filename(name),32768)
    filters=ctypes.create_unicode_buffer('Salt and Pepper workspace (*.pepper)\0*.pepper\0\0')
    options=OPENFILENAMEW();options.lStructSize=ctypes.sizeof(options);options.hwndOwner=owner
    options.lpstrFile=ctypes.cast(buffer,w.LPWSTR);options.nMaxFile=len(buffer)
    options.lpstrFilter=ctypes.cast(filters,w.LPCWSTR);options.nFilterIndex=1
    options.lpstrTitle=('Open' if open_existing else 'Save')+' Salt and Pepper workspace';options.lpstrDefExt='pepper'
    if initial_directory and Path(initial_directory).is_dir():options.lpstrInitialDir=str(initial_directory)
    options.Flags=0x00080000|0x00800000|0x00000800|0x00000008|0x00000004|0x00000002
    if open_existing:options.Flags=(options.Flags & ~0x00000002)|0x00001000
    dialog=common.GetOpenFileNameW if open_existing else common.GetSaveFileNameW
    dialog.argtypes=[ctypes.POINTER(OPENFILENAMEW)];dialog.restype=w.BOOL
    common.CommDlgExtendedError.argtypes=[];common.CommDlgExtendedError.restype=w.DWORD
    if not dialog(ctypes.byref(options)):
        error=common.CommDlgExtendedError()
        if error:raise OSError(f'The Windows file dialog failed (0x{error:04x}).')
        return None
    path=Path(buffer.value)
    # Never change the path after the dialog's overwrite confirmation.
    if path.suffix.lower()!='.pepper':raise ValueError('Choose a filename ending in .pepper.')
    return path


def atomic_copy(archive,destination):
    """Keep an existing workspace intact if archive creation/copy fails."""
    archive=Path(archive);destination=Path(destination)
    if destination.suffix.lower()!='.pepper':raise ValueError('Choose a filename ending in .pepper.')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.pepper-save-',suffix='.tmp',dir=destination.parent,delete=False) as stream:
            temporary=Path(stream.name)
            with archive.open('rb') as source:shutil.copyfileobj(source,stream,1024**2)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,destination);temporary=None
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def save_workspace(data_root,value,owner_pid=None,previous_path=None,picker=None,existing_path=None,save_as=False):
    from pcb_simulator.workspace_archive import export_workspace
    picker=picker or choose_workspace_path
    previous=existing_path or previous_path
    initial=Path(previous).parent if previous else None
    path=Path(existing_path) if existing_path and not save_as else picker(name=value.get('name','Workspace'),initial_directory=initial,owner_pid=owner_pid)
    if path is None:return dict(status='cancelled')
    path=Path(path)
    if path.suffix.lower()!='.pepper':raise ValueError('Choose a filename ending in .pepper.')
    with tempfile.TemporaryDirectory(prefix='.workspace-native-',dir=data_root) as tmp:
        result=export_workspace(data_root,board_id=value.get('board_id'),model_id=value.get('model_id'),
            name=path.stem,ui_state=value.get('ui_state',{}),outputpath=Path(tmp)/'snapshot.pepper')
        atomic_copy(result['path'],path)
    return dict(status='saved',path=str(path),filename=path.name,name=path.stem)


def open_workspace(data_root,owner_pid=None,previous_path=None,picker=None):
    from pcb_simulator.workspace_archive import import_workspace
    picker=picker or choose_workspace_path
    path=picker(open_existing=True,initial_directory=Path(previous_path).parent if previous_path else None,owner_pid=owner_pid)
    if path is None:return dict(status='cancelled')
    path=Path(path)
    if path.suffix.lower()!='.pepper':raise ValueError('Choose a .pepper workspace file.')
    if not path.is_file() or path.stat().st_size>2*1024**3:raise ValueError('Choose an existing workspace smaller than 2 GiB.')
    restored=import_workspace(data_root,path)
    restored.update(status='opened',path=str(path),filename=path.name)
    return restored
