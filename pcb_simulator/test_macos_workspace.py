"""AppKit bridge protocol; persistence semantics also use shared native tests."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pcb_simulator import macos_workspace as mac,windows_workspace as native


class MacWorkspaceTests(unittest.TestCase):
    def picker(self,output,**options):
        with patch.object(mac.sys,'platform','darwin'),patch.object(Path,'is_file',return_value=True),\
             patch.object(mac.os,'access',return_value=True),\
             patch.object(mac.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')) as run:
            result=mac.choose_workspace_path(**options)
            return result,run.call_args.args[0]

    def test_unicode_selected_path_and_name_argument(self):
        path='/tmp/Board café.pepper'
        result,command=self.picker(json.dumps(dict(status='selected',path=path)),name='Board café',owner_pid=123)
        self.assertEqual(result,Path(path));self.assertIn('Board café.pepper',command)
        self.assertEqual(command[-2:],['--owner-pid','123'])

    def test_open_and_cancel(self):
        result,command=self.picker('{"status":"cancelled"}',open_existing=True)
        self.assertIsNone(result);self.assertIn('--open',command);self.assertNotIn('--name',command)

    def test_invalid_paths_and_response_are_rejected(self):
        for value in ['bad','{}','{"status":"selected","path":"relative.pepper"}',
                      '{"status":"selected","path":"/tmp/wrong.txt"}']:
            with self.subTest(value=value),self.assertRaises((ValueError,RuntimeError)):self.picker(value)

    def test_shared_persistence_dispatches_to_mac_picker(self):
        with patch.object(native.sys,'platform','darwin'),patch.object(mac,'choose_workspace_path',return_value=Path('/tmp/a.pepper')) as picker:
            self.assertEqual(native.choose_workspace_path('a',owner_pid=123),Path('/tmp/a.pepper'))
            picker.assert_called_once_with('a',None,123,False)


if __name__=='__main__':unittest.main()
