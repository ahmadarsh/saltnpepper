"""Workspace round trips preserve results and reject unsafe/inconsistent archives."""
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pcb_simulator import workspace_archive as wa


class WorkspaceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name); self.root=self.base/'data'; self.root.mkdir()
        self.board='a'*32; self.model='b'*32; self.run='c'*32
        self.other='d'*32; self.job='e'*32
        self.put('boards',self.board,'meta.json',{'id':self.board,'filename':'demo.kicad_pcb','job_id':self.job})
        self.put('boards',self.board,'board.json',{'nets':[{'name':'VCC','colour':'rgb(255, 0, 0)'}]})
        self.put('boards',self.board,'source.kicad_pcb',b'(kicad_pcb)')
        self.put('models',self.model,'meta.json',{'id':self.model,'board_id':self.board,'status':'ready','source_file':'source.xao','job_id':self.job})
        self.put('models',self.model,'inventory.json',{'source':'source.xao','solids':[{'tag':10,'name':'J1.1'}]})
        self.put('models',self.model,'source.xao',b'<XAO/>')
        self.put('runs',self.run,'meta.json',{'id':self.run,'model_id':self.model,'status':'succeeded','job_id':self.job})
        self.put('runs',self.run,'config.json',{'model_id':self.model,'parameters':{'current_A':2},'input_tags':[10]})
        self.put('runs',self.run,'report.json',{'resistance_ohm':.1,'url':f'/runs/{self.run}/viewer.html','source':str(self.root/'models'/self.model/'source.xao'),'artifact_path':str(self.root/'runs'/self.run/'fields.npz')})
        self.put('runs',self.run,'fields.npz',b'actual-field-bytes')
        self.put('runs',self.run,'viewer.html',b'<html>standalone</html>')
        self.put('models',self.other,'meta.json',{'id':self.other,'status':'ready'})
        self.put('models',self.other,'inventory.json',{})
        self.put('models',self.other,'source.step',b'private unrelated')
        self.archive=self.base/'board.pepper'

    def put(self,kind,key,file,value):
        path=self.root/kind/key/file;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode())
        return path

    def save(self,**kwargs):
        state={'net':'VCC','input':['pad-input'],'output':['pad-output'],'model_id':self.model,'parameters':{'voltage_V':3.3}}
        return wa.export_workspace(self.root,self.board,self.model,'My board',state,self.archive,**kwargs)

    def altered(self,edit=None,extra=None):
        target=self.base/'altered.pepper'
        with zipfile.ZipFile(self.archive) as source,zipfile.ZipFile(target,'w') as destination:
            for item in source.infolist():
                raw=source.read(item)
                if edit:raw=edit(item.filename,raw)
                destination.writestr(item,raw)
            if extra:
                destination.writestr(*extra)
        return target

    def test_roundtrip_preserves_all_artifacts_settings_and_existing_data(self):
        info=self.save()
        self.assertEqual(info['suggested_filename'],'My board.pepper')
        with zipfile.ZipFile(self.archive) as archive:
            self.assertFalse(any(self.other in n or '/jobs/' in n for n in archive.namelist()))
        result=wa.import_workspace(self.root,self.archive)
        self.assertNotEqual(result['board_id'],self.board)
        model=result['model_id'];run=result['runs'][0]
        self.assertEqual(result['ui_state']['model_id'],model)
        self.assertEqual(result['ui_state']['parameters']['voltage_V'],3.3)
        self.assertEqual((self.root/'runs'/run/'fields.npz').read_bytes(),b'actual-field-bytes')
        self.assertEqual((self.root/'runs'/run/'viewer.html').read_bytes(),b'<html>standalone</html>')
        report=json.loads((self.root/'runs'/run/'report.json').read_text())
        self.assertEqual(report['url'],f'/runs/{run}/viewer.html')
        self.assertEqual(report['source'],str((self.root/'models'/model/'source.xao').resolve()))
        self.assertEqual(report['artifact_path'],str((self.root/'runs'/run/'fields.npz').resolve()))
        meta=json.loads((self.root/'models'/model/'meta.json').read_text())
        self.assertEqual(meta['board_id'],result['board_id']);self.assertNotIn('job_id',meta)
        self.assertTrue((self.root/'models'/self.other/'source.step').is_file())
        self.assertEqual((self.root/'runs'/self.run/'fields.npz').read_bytes(),b'actual-field-bytes')
        # Reopening the same archive twice allocates another complete workspace.
        second=wa.import_workspace(self.root,self.archive)
        self.assertNotEqual(second['board_id'],result['board_id'])

    def test_geometry_only_workspace_and_legacy_board_model_association(self):
        geometry=self.base/'geometry.pepper'
        wa.export_workspace(self.root,None,self.other,'STEP',{},geometry)
        result=wa.import_workspace(self.root,geometry)
        self.assertIsNone(result['board_id']);self.assertEqual(len(result['models']),1)
        meta=self.root/'models'/self.model/'meta.json'
        row=json.loads(meta.read_text());row.pop('board_id');meta.write_text(json.dumps(row))
        self.put('jobs',self.job,'status.json',{'id':self.job,'board_id':self.board,'model_id':self.model,'status':'succeeded'})
        self.assertIn(self.model,self.save()['models'])

    def test_deleted_geometry_keeps_both_results_and_a_current_model(self):
        current='8'*32; second='f'*32
        self.put('models',current,'meta.json',{'id':current,'board_id':self.board,'status':'ready'})
        self.put('models',current,'inventory.json',{'solids':[]})
        self.put('models',current,'source.xao',b'current geometry')
        self.put('runs',second,'meta.json',{'id':second,'model_id':self.model,'status':'succeeded','board_id':self.board})
        self.put('runs',second,'config.json',{'model_id':self.model,'parameters':{'current_A':4}})
        self.put('runs',second,'source.xao',b'retained run geometry')
        self.put('runs',second,'fields.npz',b'second solved fields')
        self.put('jobs',self.job,'status.json',{'id':self.job,'model_id':self.model,'board_id':self.board,'status':'succeeded'})
        shutil.rmtree(self.root/'models'/self.model)
        saved=wa.export_workspace(self.root,self.board,current,'With old results',{'active_model_id':current,'current_run_id':second},self.archive)
        self.assertEqual(saved['models'],[current]);self.assertEqual(saved['detached_model_ids'],[self.model])
        self.assertEqual(set(saved['runs']),{self.run,second})
        restored=wa.import_workspace(self.root,self.archive)
        self.assertEqual(len(restored['runs']),2)
        detached=restored['detached_model_ids'][0]
        self.assertFalse((self.root/'models'/detached).exists())
        self.assertEqual(restored['ui_state']['active_model_id'],restored['model_id'])
        self.assertIn(restored['ui_state']['current_run_id'],restored['runs'])
        for run in restored['runs']:
            meta=json.loads((self.root/'runs'/run/'meta.json').read_text())
            self.assertEqual(meta['model_id'],detached)
            self.assertEqual(meta['board_id'],restored['board_id'])
            self.assertTrue((self.root/'runs'/run/'fields.npz').is_file())
        self.assertEqual((self.root/'runs'/second/'fields.npz').read_bytes(),b'second solved fields')
        # A subsequent save discovers detached results from restored board_id,
        # even though the original worker job directory was never imported.
        again=wa.export_workspace(self.root,restored['board_id'],restored['model_id'],'Again',{},self.base/'again.pepper')
        self.assertEqual(again['detached_model_ids'],[detached]);self.assertEqual(len(again['runs']),2)

    def test_running_jobs_and_invalid_ui_state_are_rejected(self):
        self.put('jobs',self.job,'status.json',{'id':self.job,'board_id':self.board,'status':'running'})
        with self.assertRaisesRegex(ValueError,'active jobs'):self.save()
        self.assertFalse(self.archive.exists())
        for state in [[],{'voltage':float('nan')},{'huge':'x'*(1024**2)}]:
            with self.assertRaises(ValueError):wa.export_workspace(self.root,self.board,self.model,'test',state,self.archive)

    def test_traversal_symlink_duplicate_and_undeclared_entries_rejected(self):
        self.save()
        link=zipfile.ZipInfo(f'boards/{self.board}/link');link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
        cases=[('../escape',b'bad'),(f'boards/{self.board}/../escape',b'bad'),(f'boards\\{self.board}\\escape',b'bad'),
               (link,b'/etc/passwd'),(f'models/{self.other}/source.step',b'bad'),('server.json',b'bad'),('manifest.json',b'{}')]
        before=set((self.root/'boards').iterdir())
        for extra in cases:
            with self.subTest(extra=extra[0]):
                with self.assertRaises(ValueError):wa.import_workspace(self.root,self.altered(extra=extra))
        self.assertEqual(before,set((self.root/'boards').iterdir()))
        self.assertFalse((self.base/'escape').exists())

    def test_missing_or_inconsistent_references_and_size_limits_rejected(self):
        self.save()
        def edit(name,raw):
            if name==f'runs/{self.run}/config.json':return json.dumps({'model_id':self.other}).encode()
            if name==f'runs/{self.run}/meta.json':
                row=json.loads(raw);row['model_id']=self.other;return json.dumps(row).encode()
            return raw
        with self.assertRaisesRegex(ValueError,'outside this workspace'):wa.import_workspace(self.root,self.altered(edit=edit))
        with patch.object(wa,'MAX_EXPANDED_BYTES',100):
            with self.assertRaises(ValueError):wa.import_workspace(self.root,self.archive)

    def test_publish_failure_rolls_back_all_restored_items(self):
        self.save();original=wa.os.rename;calls=[]
        def fail_second(source,target):
            calls.append(target)
            if len(calls)==2:raise OSError('disk full')
            return original(source,target)
        before={k:set((self.root/k).glob('*')) for k in wa.KINDS}
        with patch.object(wa.os,'rename',side_effect=fail_second):
            with self.assertRaisesRegex(ValueError,'disk full'):wa.import_workspace(self.root,self.archive)
        self.assertEqual(before,{k:set((self.root/k).glob('*')) for k in wa.KINDS})
        self.assertFalse(list(self.root.glob('.workspace-import-*')))


if __name__=='__main__':unittest.main()
