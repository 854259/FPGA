"""Synthetic evidence gates; never real quality or model evidence."""
import copy,json,math,shutil,tempfile,unittest
from pathlib import Path
import metrics,factor_proof
ROOT=Path(__file__).resolve().parent
class Scorer:
    @staticmethod
    def summarize(by_task):
        levels=[v[0]['level'] for v in by_task.values()]
        return dict(tasks=len(by_task),scored_tasks=len(by_task),samples_per_task=1,tool_errors=0,level_counts={f'L{i}':levels.count(i) for i in range(4)})
def rows(gain=True):
    out=[]
    for task,arm in metrics.order(metrics.TASKS):
        emitted=arm=='P' and task in metrics.EMIT_TASKS
        level=3 if task in metrics.GUARDS or (gain and arm=='P' and task==metrics.TARGETS[0]) else 1
        out.append(dict(task=task,arm=arm,verdict=dict(task_id=task,level=level,coefficient=metrics.COEFFICIENTS[level],tool_error=None),actual_model_requests=0 if emitted else 1,received_model_responses=0 if emitted else 1,solve_deadline_reached=False,solve_elapsed_s=.25,stage_generation_binding_verified=True,generation_route='mechanical_serial_timer' if emitted else 'model',producer_contract_sha256='FAKE' if emitted else None,synthesis_receipt_sha256='FAKE' if arm=='P' else None,emitted_solution_sha256='FAKE' if emitted else None,solution_sha256='FAKE',route_receipt_sha256='FAKE'))
    return out
def aggregate(r):return metrics.aggregate(r,metrics.TASKS,Scorer)
class MetricsControls(unittest.TestCase):
    def test_fixed_seven_task_six_guards_one_gain_eligible(self):
        r=rows();a=aggregate(r);self.assertEqual(len(r),14);self.assertEqual(len(metrics.GUARDS),6);self.assertTrue(a['screening_eligible']);self.assertEqual(len(a['repairs']),1);self.assertFalse(a['full_score_measured'])
    def test_no_gain_regression_or_guard_failure_rejects(self):
        self.assertFalse(aggregate(rows(False))['screening_eligible'])
        for target in (metrics.TARGETS[0],metrics.GUARDS[0]):
            r=rows();v=next(x['verdict'] for x in r if x['task']==target and x['arm']=='P');v.update(level=0,coefficient=0.);self.assertFalse(aggregate(r)['screening_eligible'])
    def test_unchanged_fallback_cost_cannot_be_hidden_by_mechanical_savings(self):
        r=rows();p=next(x for x in r if x['task']==metrics.GUARDS[0] and x['arm']=='P');p.update(actual_model_requests=2,received_model_responses=2);a=aggregate(r);self.assertLessEqual(a['requests_by_arm']['P'],a['requests_by_arm']['C']);self.assertFalse(a['screening_eligible'])
    def test_improved_historical_fallback_cost_still_cannot_increase(self):
        r=rows();task=metrics.GUARDS[0]
        c=next(x for x in r if x['task']==task and x['arm']=='C')
        c['verdict'].update(level=1,coefficient=.2)
        p=next(x for x in r if x['task']==task and x['arm']=='P')
        p.update(actual_model_requests=2,received_model_responses=2)
        a=aggregate(r)
        self.assertFalse(a['every_fixed_task_request_cost'])
        self.assertTrue(a['unchanged_task_request_cost'])
        self.assertLessEqual(a['requests_by_arm']['P'],a['requests_by_arm']['C'])
        self.assertFalse(a['screening_eligible'])

    def test_missing_duplicate_or_reordered_rows_refuse(self):
        for r in (rows()[:-1],rows()+[rows()[0]],list(reversed(rows()))):
            with self.assertRaises(AssertionError):aggregate(r)
    def test_model_zero_or_mechanical_nonzero_masquerade_refuse(self):
        for mechanical in (True,False):
            r=rows();p=next(x for x in r if (x['generation_route']=='mechanical_serial_timer')==mechanical);p.update(actual_model_requests=1 if mechanical else 0,received_model_responses=1 if mechanical else 0)
            with self.assertRaises(AssertionError):aggregate(r)
    def test_unconfirmed_deadline_and_nonfinite_time_cannot_qualify(self):
        for kind in ('unconfirmed','deadline','inf'):
            r=rows();p=next(x for x in r if x['generation_route']=='model')
            if kind=='unconfirmed':p['received_model_responses']=0
            elif kind=='deadline':p['solve_deadline_reached']=True
            else:p['solve_elapsed_s']=math.inf
            if kind=='inf':
                with self.assertRaises(AssertionError):aggregate(r)
            else:self.assertFalse(aggregate(r)['screening_eligible'])
    def test_complete_provenance_and_all_native_flags_required(self):
        r=rows();a=aggregate(r);flags=['generation_route_bound','input_bytes_bound','source_hashes_bound','solution_bytes_bound','native_execution_bound','original_model_replay_bound','synthesis_abstention_bound','mechanical_recipe_bound','empty_model_artifacts_bound'];p=[dict(task=x['task'],arm=x['arm'],generation_route=x['generation_route'],**{f:True for f in flags}) for x in r];self.assertTrue(metrics.decision(a,p,r)['qualified_for_new_full_regression']);p[0]['native_execution_bound']=False;self.assertFalse(metrics.decision(a,p,r)['qualified_for_new_full_regression'])
class SourceControls(unittest.TestCase):
    def test_same_prepared_producer_and_original_fallback_byte_proof(self):
        p=factor_proof.verify(ROOT);self.assertEqual(p['maximum_model_requests_per_sample'],2);self.assertEqual(p['model_output_token_budget'],8192)
    def test_producer_and_baseline_mutation_refuse_pending_native_closed_elsewhere(self):
        for name in ('synthesis.py','reserved_keywords.py','baseline_worker.py'):
            with tempfile.TemporaryDirectory() as td:
                root=Path(td)/'copy';shutil.copytree(ROOT,root,ignore=shutil.ignore_patterns('__pycache__'));f=root/name;f.write_bytes(f.read_bytes()+b'\nFAKE SOURCE DRIFT\n')
                with self.assertRaises(AssertionError):factor_proof.verify(root)
