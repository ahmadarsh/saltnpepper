"""Regression checks for terminal selection and job cancellation/recovery."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pcb_simulator import server


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)
        self.data_patch=patch.object(server,'DATA',self.data)
        self.data_patch.start();self.addCleanup(self.data_patch.stop)
        self.thread_patch=patch.object(server.threading.Thread,'start')
        self.thread_patch.start();self.addCleanup(self.thread_patch.stop)

    def test_parent_monitor_checks_current_and_absent_process(self):
        self.assertTrue(server.process_alive(os.getpid()))
        self.assertFalse(server.process_alive(0x7fffffff))

    def test_selection_disjoint_known_integer_tags(self):
        inventory={'solids':[{'tag':1},{'tag':2}]}
        self.assertEqual(server.validate_selection({'input_tags':[1,1],'output_tags':[2]},inventory),[[1],[2]])
        for inputs,outputs in [([1],[1]),([3],[2]),([True],[2]),([],[2])]:
            with self.assertRaises(ValueError):
                server.validate_selection({'input_tags':inputs,'output_tags':outputs},inventory)

    def test_stop_cancels_waiting_jobs_and_preserves_artifacts(self):
        workbench=server.Workbench()
        run='a'*32
        server.write_json(self.data/'runs'/run/'meta.json',{'status':'queued'})
        mesh=self.data/'runs'/run/'mesh.msh';mesh.write_text('saved mesh')
        job=workbench.submit('simulation',{},run_id=run)
        workbench.stop()
        self.assertEqual(workbench.job(job['id'])['status'],'cancelled')
        self.assertEqual(server.read_json(mesh.parent/'meta.json')['status'],'cancelled')
        self.assertEqual(mesh.read_text(),'saved mesh')

    def test_restart_marks_unfinished_job_failed_with_saved_data(self):
        workbench=server.Workbench()
        run='b'*32
        server.write_json(self.data/'runs'/run/'meta.json',{'status':'running'})
        job=workbench.submit('simulation',{},run_id=run)
        recovered=server.Workbench()
        self.assertEqual(recovered.job(job['id'])['status'],'failed')
        self.assertEqual(server.read_json(self.data/'runs'/run/'meta.json')['status'],'failed')

    def test_successful_run_does_not_keep_an_old_shutdown_error(self):
        path=self.data/'runs'/('c'*32)/'meta.json'
        server.write_json(path,dict(status='succeeded',error='Interrupted by server shutdown.'))
        server.Workbench()
        self.assertEqual(server.read_json(path),dict(status='succeeded'))

    def test_delete_run_removes_artifacts_and_its_job_only(self):
        workbench=server.Workbench()
        run='d'*32
        server.write_json(self.data/'runs'/run/'meta.json',dict(status='succeeded'))
        artifact=self.data/'runs'/run/'volume.msh';artifact.write_text('mesh')
        job=workbench.submit('simulation',{},run_id=run)
        workbench.jobs[job['id']]['status']='succeeded'
        result=workbench.delete_saved('runs',run)
        self.assertEqual(result['deleted_jobs'],[job['id']])
        self.assertFalse(artifact.parent.exists())
        self.assertFalse((self.data/'jobs'/job['id']).exists())
        self.assertNotIn(job['id'],workbench.jobs)

    def test_deletion_rejects_active_jobs_and_invalid_paths(self):
        workbench=server.Workbench()
        model='e'*32;run='f'*32
        server.write_json(self.data/'models'/model/'meta.json',dict(status='ready'))
        server.write_json(self.data/'runs'/run/'meta.json',dict(status='queued'))
        workbench.submit('simulation',{},model_id=model,run_id=run)
        for kind,key in [('models',model),('runs',run),('runs',None)]:
            with self.assertRaises(RuntimeError):workbench.delete_saved(kind,key)
        self.assertTrue((self.data/'models'/model).exists())
        self.assertTrue((self.data/'runs'/run).exists())
        for key in ['..','../models','not-an-id']:
            with self.assertRaises(ValueError):workbench.delete_saved('runs',key)

    def test_model_deletion_preserves_completed_runs(self):
        workbench=server.Workbench()
        model='e'*32;run='f'*32
        server.write_json(self.data/'models'/model/'meta.json',dict(status='ready'))
        server.write_json(self.data/'runs'/run/'meta.json',dict(status='succeeded'))
        workbench.delete_saved('models',model)
        self.assertTrue((self.data/'runs'/run/'meta.json').is_file())


if __name__=='__main__':unittest.main()
