"""Synthetic scores/provenance test gates only; no score or native gain evidence."""
from pathlib import Path
import copy,unittest
import metrics,worker

R=Path(__file__).resolve().parent
scorer=worker.load('diag_fixture_score',R/'raw_evidence/test_fixtures/score.py')

def material():
    tasks=sorted(metrics.TARGETS+metrics.COUNTEREXAMPLES+metrics.GUARDS)
    rows=[];provenance=[]
    for task,arm in metrics.order(tasks):
        target=task in metrics.TARGETS;level=3 if not target or arm=='P' else 0
        calls=2 if target else 1
        rows.append(dict(task=task,arm=arm,actual_model_requests=calls,received_model_responses=calls,
            solve_deadline_reached=False,solve_elapsed_s=1.,verdict=dict(task_id=task,tool_error=None,level=level,coefficient=metrics.COEFFICIENTS[level])))
        chain=dict(repair_request_index=1,initial_code_sha256='samecode',initial_native_fact_sha256='samefullfacts',
            initial_returncode=1,priority_invoked=arm=='P',policy_effect_feedback_changed=arm=='P',
            normalized_feedback_sha256=arm,feedback_bound=True,complete=True,repaired_compile_returncode=0,
            repaired_compile_direct=True) if target else None
        provenance.append(dict(task=task,arm=arm,first_reply_sha256='samefirst',original_repair_feedback_bound=True,native_compile_repair=chain))
    return tasks,rows,provenance

class Metrics(unittest.TestCase):
    def result(self,rows,provenance):
        tasks=sorted(metrics.TARGETS+metrics.COUNTEREXAMPLES+metrics.GUARDS)
        return metrics.decision(metrics.aggregate(rows,tasks,scorer),provenance,rows)

    def test_only_complete_target_chain_opens_newfull_scope(self):
        tasks,rows,p=material();r=self.result(rows,p)
        self.assertTrue(r['qualified_for_new_full_regression']);self.assertEqual(r['matched_native_repair_tasks'],metrics.TARGETS)
        self.assertFalse(r['adoption']);self.assertFalse(r['independent_validation_qualified']);self.assertFalse(r['five_sample_qualified'])

    def test_no_samefirst_samecode_samefacts_changed_feedback_or_binding_no_qualification(self):
        for where,key,value in [
            ('top','first_reply_sha256','different'),('chain','initial_code_sha256','different'),
            ('chain','initial_native_fact_sha256','different'),('chain','policy_effect_feedback_changed',False),
            ('chain','normalized_feedback_sha256','C'),('chain','feedback_bound',False),('chain','complete',False),
            ('chain','priority_invoked',False),('chain','repaired_compile_direct',False),('chain','repaired_compile_returncode',1),
            ('chain','repaired_compile_returncode',False),('chain','initial_returncode',True),('chain','initial_returncode',-9)]:
            with self.subTest(key=key,value=value):
                tasks,rows,p=material();candidate=next(v for v in p if v['task'] in metrics.TARGETS and v['arm']=='P')
                (candidate if where=='top' else candidate['native_compile_repair'])[key]=value
                self.assertFalse(self.result(rows,p)['qualified_for_new_full_regression'])

    def test_any_regression_guard_cost_deadline_unknown_or_request_growth_blocks(self):
        for mode in ['regression','guardcost','deadline','unknown','extra']:
            with self.subTest(mode=mode):
                tasks,rows,p=material();guard=next(r for r in rows if r['task']==metrics.GUARDS[0] and r['arm']=='P')
                if mode=='regression':guard['verdict'].update(level=1,coefficient=.2)
                if mode=='guardcost':guard.update(actual_model_requests=2,received_model_responses=2)
                if mode=='deadline':rows[0]['solve_deadline_reached']=True
                if mode=='unknown':rows[0]['received_model_responses']=0
                if mode=='extra':
                    for r in rows:
                        if r['arm']=='P' and r['task'] in metrics.COUNTEREXAMPLES+metrics.GUARDS[:1]:r.update(actual_model_requests=2,received_model_responses=2)
                self.assertFalse(self.result(rows,p)['qualified_for_new_full_regression'])

    def test_missing_duplicate_reordered_unknown_level_or_toolerror_rejected(self):
        for mode in ['missing','duplicate','order','level','tool']:
            with self.subTest(mode=mode):
                tasks,rows,p=material()
                if mode=='missing':rows.pop()
                if mode=='duplicate':rows[-1]=copy.deepcopy(rows[0])
                if mode=='order':rows[0],rows[1]=rows[1],rows[0]
                if mode=='level':rows[0]['verdict']['level']=True
                if mode=='tool':rows[0]['verdict']['tool_error']='FAKE tool failure'
                with self.assertRaises(AssertionError):metrics.aggregate(rows,tasks,scorer)

    def test_counterexample_improvement_without_target_chain_cannot_open_full(self):
        tasks,rows,p=material()
        for r in rows:
            if r['task'] in metrics.TARGETS:r['verdict'].update(level=0,coefficient=0.)
            if r['task']==metrics.COUNTEREXAMPLES[0] and r['arm']=='C':r['verdict'].update(level=0,coefficient=0.)
        self.assertFalse(self.result(rows,p)['qualified_for_new_full_regression'])

    def test_xvlog_pass_without_external_coefficient_improvement_cannot_open_full(self):
        tasks,rows,p=material()
        next(r for r in rows if r['task'] in metrics.TARGETS and r['arm']=='P')['verdict'].update(level=0,coefficient=0.)
        self.assertFalse(self.result(rows,p)['qualified_for_new_full_regression'])

if __name__=='__main__':unittest.main()
