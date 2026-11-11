"""Interactive Mac check: native Open, same-file Save, Save As and Cancel.

Run from a visible Mac desktop. The printed paths are temporary test files;
no existing user workspace is modified. This is not an installed-app UI test.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from pcb_simulator.windows_workspace import save_workspace,open_workspace


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=ROOT/'prototypes/mac-native-save-verification.json')
    args=parser.parse_args()
    if sys.platform!='darwin':parser.error('Run on a Mac desktop; real dialogs are required.')
    checks=[]
    with tempfile.TemporaryDirectory(prefix='pepper-native-dialog-test-') as tmp:
        root=Path(tmp);data=root/'data';data.mkdir();original=root/'Original folder'/'Original board.pepper'
        original.parent.mkdir();new=root/'Another folder'/'Renamed café board.pepper';new.parent.mkdir()
        model='a'*32;folder=data/'models'/model;folder.mkdir(parents=True)
        (folder/'meta.json').write_text(json.dumps(dict(id=model,status='ready',source_file='source.step')))
        (folder/'inventory.json').write_text('{}');(folder/'source.step').write_text('temporary dialog-test fixture')
        save_workspace(data,dict(model_id=model,name='Original board',ui_state=dict(revision=1)),picker=lambda **kw:original)
        print('1. In the Mac OPEN dialog choose this temporary workspace:\n'+str(original),flush=True)
        opened=open_workspace(data)
        assert opened.get('status')=='opened' and Path(opened['path']).samefile(original),'Choose the exact printed test file.'
        checks.append('real Mac native Open returns original full path')
        value=dict(model_id=opened['model_id'],name=opened['name'],ui_state=dict(revision=2))
        before=hashlib.sha256(original.read_bytes()).hexdigest()
        saved=save_workspace(data,value,existing_path=original)
        assert Path(saved['path']).samefile(original) and hashlib.sha256(original.read_bytes()).hexdigest()!=before
        with zipfile.ZipFile(original) as archive:assert json.loads(archive.read('manifest.json'))['ui_state']['revision']==2
        checks.append('Save updates the exact opened .pepper file without creating another file')
        original_bytes=original.read_bytes()
        print('2. In SAVE AS choose this NEW path (paste the full path in File name):\n'+str(new),flush=True)
        fork=save_workspace(data,value,existing_path=original,save_as=True)
        print('Save As result: '+json.dumps(fork),flush=True)
        assert fork.get('status')=='saved' and Path(fork['path']).samefile(new)
        assert original.read_bytes()==original_bytes
        value['ui_state']['revision']=3;save_workspace(data,value,existing_path=fork['path'])
        with zipfile.ZipFile(new) as archive:assert json.loads(archive.read('manifest.json'))['ui_state']['revision']==3
        assert original.read_bytes()==original_bytes
        checks.append('Save As chooses another folder/name; later Save updates the new file only')
        new_bytes=new.read_bytes()
        print('3. Click CANCEL in the next Save As dialog.',flush=True)
        cancelled=save_workspace(data,value,existing_path=new,save_as=True)
        assert cancelled==dict(status='cancelled') and new.read_bytes()==new_bytes
        checks.append('Cancel writes nothing and preserves the existing workspace')
        print('4. In the next SAVE AS choose the EXISTING original file. Confirm that Mac asks to replace it; decline replacement, then cancel the chooser:\n'+str(original),flush=True)
        cancelled=save_workspace(data,value,existing_path=new,save_as=True)
        assert cancelled==dict(status='cancelled') and original.read_bytes()==original_bytes
        checks.append('native overwrite approval can be declined without modifying the original')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(dict(status='PASS',scope='Native Mac dialogs and archive operations; installed Tauri UI still requires WINDOWS_VERIFICATION.md',checks=checks),indent=2)+'\n')
    print('PASS: '+str(args.report),flush=True)


if __name__=='__main__':main()
