"""Synthetic integrity/causal-evidence rejection tests; zero actual model/EDA."""
import json,tempfile,unittest
from pathlib import Path
import audit,fixture
from unittest.mock import patch

class Audit(unittest.TestCase):
    def case(self,version=1,mutate=None,failure=False):
        with tempfile.TemporaryDirectory(prefix='bridge-audit-test-') as td:
            root=Path(td);run=fixture.v1(root);prior=root/'v1.zip'
            if version==2:fixture.archive(run,prior);run=fixture.v2(root)
            if mutate:mutate(run)
            archive=root/'case.zip';fixture.archive(run,archive,prior if version==2 else None,failure)
            return audit.audit(archive,fixture=True)
    def test_synthetic_v1_reconstruction_and_v2_nested_dependency_pass_no_execution_claim(self):
        for version in [1,2]:
            result=self.case(version);self.assertTrue(result['passed']);self.assertFalse(result['actual_execution_verified']);self.assertEqual(result['evidence_kind'],'synthetic_checker_fixture');self.assertFalse(result['adoption']);self.assertFalse(result['quality_score_measured'])
    def test_synthetic_cannot_be_admitted_by_production_cli(self):
        with tempfile.TemporaryDirectory(prefix='bridge-audit-test-') as td:
            root=Path(td);run=fixture.v1(root);archive=root/'case.zip';fixture.archive(run,archive)
            with self.assertRaises(AssertionError):audit.audit(archive)
    def test_terminal_failure_can_be_collected_but_cannot_be_accepted(self):
        def failure(run):
            p=run/'results/summary.json';d=json.loads(p.read_text(encoding='utf-8'));d.update(complete=False,passed=False,error='Synthetic early failure');fixture.save(p,d)
        with self.assertRaises(AssertionError):self.case(mutate=failure,failure=True)
    def test_wrong_negative_count_is_rejected_even_with_updated_native_receipt_binding(self):
        def wrong(run):
            p=run/'results/native_parity/http_worker/map_check_0/probe/result.json';d=json.loads(p.read_text(encoding='utf-8'));d['mismatches']=0;fixture.save(p,d)
        with self.assertRaises(AssertionError):self.case(mutate=wrong)
    def test_modified_feedback_in_actual_second_request_is_rejected(self):
        def wrong(run):
            p=run/'results/native_parity/fake_model_requests.json';d=json.loads(p.read_text(encoding='utf-8'));d[1]['messages'][1]['content']+='\nInvent an answer from PRIVATE_REFERENCE';fixture.save(p,d)
        with self.assertRaises(AssertionError):self.case(mutate=wrong)
    def test_tb_changes_cannot_hide_behind_rehashed_probe_receipt(self):
        def wrong(run):
            p=run/'results/native_parity/legacy_probe_0/tb.sv';fixture.write(p,p.read_text(encoding='utf-8')+'// changed\n');r=p.parent/'result.json';d=json.loads(r.read_text(encoding='utf-8'));d['tb_sha256']=fixture.sha(p);fixture.save(r,d)
        with self.assertRaises(AssertionError):self.case(mutate=wrong)
    def test_extra_production_module_is_recorded_and_rejected(self):
        with self.assertRaises(AssertionError):self.case(mutate=lambda run:fixture.write(run/'package/json.py','# synthetic shadow module\n'))
    def test_v2_32gib_boundary_and_attribution_inconsistent_counters_are_rejected(self):
        for kind in ['over_limit','wrong_pid','counter_inconsistent']:
            def wrong(run):
                p=run/'results/live_health/summary.json';d=json.loads(p.read_text(encoding='utf-8'))
                if kind=='over_limit':d['http_reply']['vram_gb']=32+1/1024**3
                elif kind=='wrong_pid':d['observation']['model_pid']=77
                else:d['observation']['card_vram_used_bytes']+=1
                fixture.save(p,d);r=run/'results/summary.json';report=json.loads(r.read_text(encoding='utf-8'));report['live_health_receipt_sha256']=fixture.sha(p);fixture.save(r,report)
            with self.subTest(kind=kind),self.assertRaises(AssertionError):self.case(2,wrong)
    def test_guard_release_and_cleanup_failure_are_rejected(self):
        for key in ['own_slot_released','owned_cleanup']:
            def wrong(run):
                p=run/'guard/status.json';d=json.loads(p.read_text(encoding='utf-8'));d[key]=False if key=='own_slot_released' else {'verified':False,'remaining':[{'pid':77,'starttime':'synthetic-invalid'}],'recorded':[]};fixture.save(p,d)
            with self.subTest(key=key),self.assertRaises(AssertionError):self.case(mutate=wrong,failure=key=='owned_cleanup')
    def test_terminal_json_with_live_recorded_owned_process_cannot_be_collected(self):
        with tempfile.TemporaryDirectory(prefix='bridge-audit-live-fixture-') as td:
            root=Path(td);run=fixture.v1(root);proc=root/'proc'
            fixture.write(proc/'777/stat','777 (owned fixture) '+' '.join(['S']+['0']*18+['555']))
            p=run/'guard/status.json';d=json.loads(p.read_text(encoding='utf-8'));d['owned_cleanup']['recorded']=[{'pid':777,'starttime':'555'}];fixture.save(p,d)
            original=fixture.collect.Path
            def paths(value):return proc if str(value)=='/proc' else original(value)
            with patch.object(fixture.collect,'Path',side_effect=paths),self.assertRaises(AssertionError):fixture.archive(run,root/'must_not_exist.zip')
            self.assertFalse((root/'must_not_exist.zip').exists())

if __name__=='__main__':unittest.main()
