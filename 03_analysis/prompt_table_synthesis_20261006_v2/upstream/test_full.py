"""Real orchestration with synthetic transport/judges: all312 coverage, never quality evidence."""
import copy,importlib.util,json,tempfile,types,unittest,sys
from pathlib import Path
from unittest.mock import patch
import full_metrics as metrics
import pilot
R=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('full_pinned_score_fixture',R/'raw_evidence/test_fixtures/score.py');score=importlib.util.module_from_spec(spec);spec.loader.exec_module(score)
def material():
    tasks=sorted({n.split('/')[0] for n in json.loads((R/'INPUT_MANIFEST.json').read_bytes())['input_sha256']})
    rows=[];prov=[]
    for t,a in metrics.order(tasks):
        rows.append(dict(task=t,arm=a,verdict=dict(task_id=t,level=3,coefficient=1.,tool_error=None,elapsed_s=1.),actual_model_requests=1,received_model_responses=1,solve_deadline_reached=False,solve_elapsed_s=1.))
        prov.append(dict(task=t,arm=a,first_reply_sha256=t,contract_status='abstain',contract_family=None,native_checks=[],original_repair_feedback_bound=True))
    return tasks,rows,prov
class Full(unittest.TestCase):
    def test_actual_stage_schedules_all312_original_workers_and_judges(self):
        tasks,_,_=material()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);commands=[];s=dict(task_ids=tasks,arms=['C','P'],schema='phase_full156_frozen_v1',model='fake',dependencies_cloud=str(root),identity='fake-full',solve_deadline_s=300,stage_timeout_s=86400,max_actual_model_requests=624,minimum_disk_free_bytes=0)
            (root/'RUN_SPEC.json').write_text(json.dumps(s));(root/'FRESH_PILOT_AUDIT.json').write_text(json.dumps(dict(evidence_valid=True,qualified_for_new_full_regression=True)))
            def owned(argv,cwd,log,seconds):
                commands.append(argv);t=argv[argv.index('--task')+1];out=Path(argv[argv.index('--out')+1]);out.mkdir()
                if '--arm' in argv:
                    (out/'solution.v').write_text('fake');(out/'requests.json').write_text(json.dumps([dict(replayed=False,response_received=True)]*2));self.assertEqual(seconds,300)
                else:
                    v=dict(task_id=t,level=3,coefficient=1.,tool_error=None,elapsed_s=1.);(out/'bound_verdict.json').write_text(json.dumps(dict(solution_sha256='fake',verdict_sha256='fake',verdict=v)));self.assertEqual(seconds,360)
                return dict(returncode=0,timeout=False,launch_error=None,remaining_live_group=[],elapsed_s=1.)
            pair=types.SimpleNamespace(check_resource=lambda *a,**k:None,owned_command=owned)
            loader=lambda name,path:score if name=='full_pinned_official_score' else pair
            with patch.object(pilot,'ROOT',root),patch.object(pilot,'frozen',return_value=s),patch.object(pilot,'validate_environment',return_value=dict(verified=True,fixture_only=True)),patch.object(pilot,'load',side_effect=loader),patch.object(pilot,'publish'),patch.object(pilot.sys,'platform','linux'),patch.object(pilot.ctypes,'CDLL',return_value=types.SimpleNamespace(prctl=lambda *a:0)),patch.dict(sys.modules,activity=types.SimpleNamespace(append=lambda *a:None)):
                self.assertEqual(pilot.main(types.SimpleNamespace(kit=root,resource_check=root/'resource.json')),0)
            result=json.loads((root/'results/summary.json').read_bytes());self.assertEqual(len(result['rows']),312);self.assertEqual(result['actual_model_requests'],624);self.assertEqual(len(commands),624)
            self.assertEqual([(r['task'],r['arm']) for r in result['rows']],metrics.order(tasks));self.assertTrue(result['complete']);self.assertFalse(result['candidate_qualified_for_independent_validation'])
    def test_all156_denominator_and_partial_duplicate_reverse_rejected(self):
        tasks,rows,_=material();a=metrics.aggregate(rows,tasks,score);self.assertEqual(a['official_scores']['P']['scored_tasks'],156)
        for bad in [rows[:-1],rows+[rows[0]],rows[::-1]]:
            with self.assertRaises(AssertionError):metrics.aggregate(bad,tasks,score)
        with self.assertRaises(AssertionError):metrics.order(tasks[:-1])
    def positive(self):
        tasks,rows,p=material()
        for r in rows:
            if r['task'] in metrics.EDGES:
                if r['arm']=='C':r['verdict'].update(level=1,coefficient=.2)
                else:r.update(actual_model_requests=2,received_model_responses=2)
        for r in p:
            if r['task'] in metrics.EDGES and r['arm']=='P':r.update(contract_status='supported',contract_family='edge',native_checks=[dict(index='map_check_0',status='fail',mismatches=1),dict(index='map_check_1',status='pass',mismatches=0)])
        return tasks,rows,p
    def test_quality_requires_actual_matching_chains_and_preserves_old_gate(self):
        tasks,rows,p=self.positive();a=metrics.aggregate(rows,tasks,score);self.assertTrue(a['screening_eligible']);self.assertFalse(a['candidate_qualified_for_independent_validation'])
        decision=metrics.decision(a,p,rows);self.assertTrue(decision['candidate_qualified_for_independent_validation']);self.assertFalse(decision['adoption']);self.assertFalse(decision['five_sample_qualified']);self.assertTrue(decision['previous_full_gate_still_failed'])
        p[0]['first_reply_sha256']='changed'
        # Alter an actual new edge chain, not an unrelated row.
        next(v for v in p if v['task']==metrics.EDGES[1] and v['arm']=='P')['first_reply_sha256']='different'
        self.assertFalse(metrics.decision(a,p,rows)['candidate_qualified_for_independent_validation'])
    def test_deadline_unconfirmed_regression_or_extra_cost_reject(self):
        tasks,rows,_=self.positive()
        for field,value in [('solve_deadline_reached',True),('received_model_responses',0)]:
            bad=copy.deepcopy(rows);bad[0][field]=value;self.assertFalse(metrics.aggregate(bad,tasks,score)['screening_eligible'])
        bad=copy.deepcopy(rows);next(r for r in bad if r['task']==metrics.GUARDS[0] and r['arm']=='P')['verdict'].update(level=1,coefficient=.2);self.assertFalse(metrics.aggregate(bad,tasks,score)['screening_eligible'])
        bad=copy.deepcopy(rows);next(r for r in bad if r['task']==metrics.GUARDS[0] and r['arm']=='P').update(actual_model_requests=2,received_model_responses=2);self.assertFalse(metrics.aggregate(bad,tasks,score)['screening_eligible'])
    def test_environment_failure_not_scored_as_model_error(self):
        tasks,rows,_=material();rows[0]['verdict']['tool_error']='environment'
        with self.assertRaises(AssertionError):metrics.aggregate(rows,tasks,score)
if __name__=='__main__':unittest.main()
