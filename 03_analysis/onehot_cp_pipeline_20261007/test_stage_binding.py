"""Synthetic worker->stage protocol checks; no model, EDA or scoring."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import pilot
import test_worker

class StageBindingControls(unittest.TestCase):
    def setUp(self):
        self.fixture=test_worker.WorkerControls('test_generated_zero_without_HTTP_or_fallback')
        self.fixture.setUp()
        self.patch=patch.object(pilot,'ROOT',self.fixture.owned);self.patch.start()
    def tearDown(self):
        self.patch.stop();self.fixture.tearDown()
    def execute(self,arm='P',abstain=False):
        f=self.fixture;f.args.arm=arm
        if abstain:f.source.joinpath('prompt.txt').write_bytes(b'FAKE unsupported partial specification')
        f.run_worker()
        journal=test_worker.read(f.args.out/'requests.json')
        for entry in journal:entry.update(replayed=False,response_received=True)
        test_worker.save(f.args.out/'requests.json',journal)
        return journal
    def bind(self,journal):
        f=self.fixture
        return pilot.generation_binding(f.args.out,f.source,f.args.arm,journal,dict(compiler_tools={'xvlog':{'path':'/FAKE/vivado/xvlog'}}))
    def test_actual_worker_mechanical_receipt_passes_stage_without_requests(self):
        journal=self.execute();self.assertEqual(journal,[])
        result=self.bind(journal)
        self.assertTrue(result['stage_generation_binding_verified'])
        self.assertEqual(result['generation_route'],'mechanical_onehot')
        self.assertEqual(self.fixture.fallback_calls,[])
    def test_actual_control_receipt_passes_original_model_route(self):
        journal=self.execute('C');self.assertEqual(len(journal),1)
        result=self.bind(journal);self.assertEqual(result['generation_route'],'model')
        self.assertIsNone(result['synthesis_receipt_sha256'])
        self.assertTrue(result['stage_generation_binding_verified'])
    def test_actual_candidate_abstention_passes_same_model_route(self):
        journal=self.execute(abstain=True)
        result=self.bind(journal);self.assertEqual(result['generation_route'],'model')
        self.assertIsNotNone(result['synthesis_receipt_sha256'])
        self.assertTrue(result['stage_generation_binding_verified'])
    def test_actual_matching_interface_and_CRLF_stage_binding(self):
        from native_material_fixture import fixture
        prompt,interface,_=fixture(n=3,k=2,module='SyntheticAdapter')
        f=self.fixture
        f.source.joinpath('prompt.txt').write_bytes(prompt.replace('\n','\r\n').encode())
        f.source.joinpath('interface.txt').write_bytes(interface.replace('\n','\r\n').encode())
        journal=self.execute()
        result=self.bind(journal)
        self.assertEqual(result['generation_route'],'mechanical_onehot')
        self.assertTrue(result['stage_generation_binding_verified'])
        self.assertEqual(journal,[])
    def test_fixed_seven_metadata_matches_metrics(self):
        import metrics,preparation_inputs
        groups=preparation_inputs.task_groups(Path(__file__).resolve().parent)
        self.assertEqual(groups['task_ids'],metrics.TASKS)
        self.assertEqual(groups['target_tasks'],metrics.TARGETS)
        self.assertEqual(groups['guard_tasks'],metrics.GUARDS)
        self.assertEqual(groups['expected_samples'],14)
    def test_outer_worker_wallclock_includes_adapter_overhead(self):
        command=dict(timeout=False,elapsed_s=299.75,launch_error=None,remaining_live_group=[],returncode=0)
        measurement=pilot.solver_measurement(command)
        self.assertEqual(measurement['solve_elapsed_s'],299.75)
        self.assertFalse(measurement['solve_deadline_reached'])
        for seconds in (300.01,float('inf'),float('nan'),-1):
            command['elapsed_s']=seconds
            with self.assertRaises(AssertionError):pilot.solver_measurement(command)

    def test_outer_worker_timeout_cannot_be_hidden_by_complete_fallback(self):
        command=dict(timeout=True,elapsed_s=300,launch_error=None,remaining_live_group=[],returncode=-15)
        self.assertTrue(pilot.solver_measurement(command)['solve_deadline_reached'])

    def test_legacy_table_schema_is_rejected_after_otherwise_exact_worker(self):
        journal=self.execute()
        path=self.fixture.args.out/'generation_route.json';route=test_worker.read(path)
        route['schema']='table_synthesis_generation_route_v1';test_worker.save(path,route)
        with self.assertRaises(AssertionError):self.bind(journal)

if __name__=='__main__':unittest.main()
