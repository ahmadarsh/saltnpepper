"""Destination, cancellation and atomic-save regressions (portable tests).

These tests mock the picker; the separate Windows checklist verifies its real UI.
"""
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from urllib.parse import urlsplit
from pcb_simulator import windows_workspace as native,workspace_archive,server


class NativeWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.data=self.root/'data';self.data.mkdir()
        self.model='a'*32;self.run='b'*32
        model=self.data/'models'/self.model;model.mkdir(parents=True)
        (model/'meta.json').write_text(json.dumps(dict(id=self.model,status='ready',source_file='source.step')))
        (model/'inventory.json').write_text('{}');(model/'source.step').write_text('sample geometry')
        run=self.data/'runs'/self.run;run.mkdir(parents=True)
        (run/'meta.json').write_text(json.dumps(dict(id=self.run,model_id=self.model,status='succeeded')))
        (run/'config.json').write_text(json.dumps(dict(model_id=self.model)))
        (run/'fields.npz').write_bytes(b'saved fields')
        folder=self.root/'User chosen folder';folder.mkdir()
        self.destination=folder/'Ma carte café.pepper'
        self.value=dict(model_id=self.model,name='Initial name',ui_state=dict(voltage_V=2.5))

    def test_selected_folder_filename_and_archive_reopen(self):
        seen={}
        def picker(**options):seen.update(options);return self.destination
        result=native.save_workspace(self.data,self.value,owner_pid=123,picker=picker)
        self.assertEqual(result['path'],str(self.destination));self.assertEqual(result['name'],'Ma carte café')
        self.assertEqual(seen['owner_pid'],123)
        with zipfile.ZipFile(self.destination) as archive:
            self.assertIsNone(archive.testzip());manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['name'],'Ma carte café');self.assertEqual(len(manifest['runs']),1)
        restored=workspace_archive.import_workspace(self.data,self.destination)
        self.assertEqual(len(restored['runs']),1);self.assertNotEqual(restored['model_id'],self.model)

    def test_cancel_does_not_export_or_touch_existing_file(self):
        self.destination.write_bytes(b'keep previous workspace')
        with patch.object(workspace_archive,'export_workspace') as export:
            result=native.save_workspace(self.data,self.value,picker=lambda **kwargs:None)
        self.assertEqual(result,dict(status='cancelled'));export.assert_not_called()
        self.assertEqual(self.destination.read_bytes(),b'keep previous workspace')

    def test_failed_export_preserves_previous_file_and_removes_staging(self):
        self.destination.write_bytes(b'keep')
        with patch.object(workspace_archive,'export_workspace',side_effect=RuntimeError('job active')):
            with self.assertRaisesRegex(RuntimeError,'job active'):
                native.save_workspace(self.data,self.value,picker=lambda **kwargs:self.destination)
        self.assertEqual(self.destination.read_bytes(),b'keep')
        self.assertFalse(list(self.data.glob('.workspace-native-*')))

    def test_failed_copy_or_replace_keeps_old_file_and_cleans_temporary(self):
        archive=self.root/'new.pepper';archive.write_bytes(b'new archive');self.destination.write_bytes(b'old archive')
        for target in ['shutil.copyfileobj','os.replace']:
            with patch('pcb_simulator.windows_workspace.'+target,side_effect=OSError('write denied')):
                with self.assertRaises(OSError):native.atomic_copy(archive,self.destination)
            self.assertEqual(self.destination.read_bytes(),b'old archive')
            self.assertFalse(list(self.destination.parent.glob('.pepper-save-*')))

    def test_save_as_suggests_previous_folder_but_uses_new_user_choice(self):
        other=self.root/'Another folder';other.mkdir();new=other/'Second.pepper';seen={}
        def picker(**kwargs):seen.update(kwargs);return new
        native.save_workspace(self.data,self.value,previous_path=self.destination,picker=picker)
        self.assertEqual(seen['initial_directory'],self.destination.parent)
        self.assertTrue(new.is_file());self.assertFalse(self.destination.exists())

    def test_extension_is_not_changed_after_overwrite_confirmation(self):
        wrong=self.destination.with_suffix('.txt');wrong.write_text('keep')
        with self.assertRaisesRegex(ValueError,'pepper'):
            native.save_workspace(self.data,self.value,picker=lambda **kwargs:wrong)
        self.assertEqual(wrong.read_text(),'keep');self.assertFalse(wrong.with_suffix('.pepper').exists())

    def test_suggestions_are_filenames_and_not_reserved_windows_devices(self):
        for name,expected in [('demo.pepper','demo.pepper'),('C:\\private\\board','board.pepper'),('CON','Workspace-CON.pepper'),('a:b','a_b.pepper'),('   ','Workspace.pepper')]:
            self.assertEqual(native.suggested_filename(name),expected)

    def test_native_open_then_save_updates_exact_same_file_without_picker(self):
        native.save_workspace(self.data,self.value,picker=lambda **kwargs:self.destination)
        opened=native.open_workspace(self.data,picker=lambda **kwargs:self.destination)
        self.assertEqual(opened['path'],str(self.destination))
        changed=dict(model_id=opened['model_id'],name=opened['name'],ui_state=dict(voltage_V=5))
        with patch.object(native,'choose_workspace_path') as picker:
            result=native.save_workspace(self.data,changed,existing_path=opened['path'])
        picker.assert_not_called();self.assertEqual(result['path'],str(self.destination))
        with zipfile.ZipFile(self.destination) as archive:
            manifest=json.loads(archive.read('manifest.json'));self.assertEqual(manifest['ui_state']['voltage_V'],5)
        self.assertEqual(list(self.destination.parent.glob('*.pepper')),[self.destination])

    def test_save_as_forks_file_and_next_save_updates_only_new_file(self):
        native.save_workspace(self.data,self.value,picker=lambda **kwargs:self.destination)
        original=self.destination.read_bytes();other=self.destination.parent/'New name.pepper'
        chosen=native.save_workspace(self.data,self.value,existing_path=self.destination,save_as=True,picker=lambda **kwargs:other)
        self.assertEqual(self.destination.read_bytes(),original)
        changed=dict(self.value,ui_state=dict(voltage_V=12))
        native.save_workspace(self.data,changed,existing_path=chosen['path'])
        self.assertEqual(self.destination.read_bytes(),original)
        with zipfile.ZipFile(other) as archive:self.assertEqual(json.loads(archive.read('manifest.json'))['ui_state']['voltage_V'],12)

    def test_cancel_save_as_preserves_existing_file(self):
        self.destination.write_bytes(b'previous file')
        result=native.save_workspace(self.data,self.value,existing_path=self.destination,save_as=True,picker=lambda **kwargs:None)
        self.assertEqual(result['status'],'cancelled');self.assertEqual(self.destination.read_bytes(),b'previous file')


class NativeWorkspaceEndpointTests(unittest.TestCase):
    def handler(self,enabled=True):
        handler=object.__new__(server.Handler)
        handler.server=SimpleNamespace(native_workspace_save=enabled,desktop_parent=42,workspace_save_lock=threading.Lock(),last_workspace_path='previous.pepper')
        handler.body_json=lambda:dict(name='Board');handler.results=[]
        handler.send_json=lambda value,status=200:handler.results.append((value,status))
        return handler

    def test_disabled_server_cannot_open_dialog(self):
        h=self.handler(False)
        with patch.object(native,'save_workspace') as save:h.workspace_post(urlsplit('/api/workspace/save-native'))
        save.assert_not_called();self.assertEqual(h.results[0][1],403)

    def test_only_one_native_dialog_is_open_at_a_time(self):
        h=self.handler();h.server.workspace_save_lock.acquire()
        with patch.object(native,'save_workspace') as save:h.workspace_post(urlsplit('/api/workspace/save-native'))
        save.assert_not_called();self.assertEqual(h.results[0][1],409)

    def test_cancel_does_not_replace_previous_path_and_failure_releases_lock(self):
        h=self.handler()
        with patch.object(native,'save_workspace',return_value=dict(status='cancelled')):
            h.workspace_post(urlsplit('/api/workspace/save-native'))
        self.assertEqual(h.server.last_workspace_path,'previous.pepper');self.assertFalse(h.server.workspace_save_lock.locked())
        with patch.object(native,'save_workspace',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):h.workspace_post(urlsplit('/api/workspace/save-native'))
        self.assertFalse(h.server.workspace_save_lock.locked())

    def test_client_cannot_supply_an_arbitrary_destination_or_unknown_token(self):
        h=self.handler();h.body_json=lambda:dict(file_token='unknown',path='arbitrary.pepper')
        with patch.object(native,'save_workspace') as save:h.workspace_post(urlsplit('/api/workspace/save-native'))
        save.assert_not_called();self.assertEqual(h.results[0][1],409)
        self.assertFalse(h.server.workspace_save_lock.locked())

    def test_known_file_token_routes_save_to_original_path_and_save_as_to_picker(self):
        h=self.handler();h.server.workspace_files={'known':'original.pepper'}
        for save_as in [False,True]:
            h.body_json=lambda:dict(file_token='known',save_as=save_as)
            with patch.object(native,'save_workspace',return_value=dict(status='saved',path='chosen.pepper')) as save:
                h.workspace_post(urlsplit('/api/workspace/save-native'))
            self.assertEqual(save.call_args.kwargs['existing_path'],'original.pepper')
            self.assertEqual(save.call_args.kwargs['save_as'],save_as)
            self.assertTrue(h.results[-1][0]['native_file_token'])
            h.server.workspace_files['known']='original.pepper'


if __name__=='__main__':unittest.main()
