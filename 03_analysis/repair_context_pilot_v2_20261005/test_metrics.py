import copy
import importlib.util
import unittest
from pathlib import Path
import metrics

ROOT=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('pinned_pilot_score',ROOT/'raw_evidence/test_fixtures/score.py')
score=importlib.util.module_from_spec(s);s.loader.exec_module(score)
TASKS=sorted(metrics.GUARDS+['Prob070_ece241_2013_q2','Prob147_circuit10','Prob153_gshare'])


def material():
    rows=[dict(task=t,arm=a,verdict=dict(task_id=t,level=3,coefficient=1.,tool_error=None,elapsed_s=1.),
          actual_model_requests=1,received_model_responses=1,solve_deadline_reached=False,solve_elapsed_s=10.) for t,a in metrics.order(TASKS)]
    provenance=[dict(task=t,arm=a,first_reply_sha256=t,context_receipts=[dict(changed=t.startswith(('Prob070','Prob153')))] if a=='D' else []) for t,a in metrics.order(TASKS)]
    return rows,provenance


class Metrics(unittest.TestCase):
    def test_fixed16_all8_denominator_and_no_partial_or_reordering(self):
        rows,_=material();self.assertEqual(metrics.aggregate(rows,TASKS,score)['coefficients'],dict(C=1.,D=1.))
        for bad in [rows[:-1],rows+[rows[0]],rows[::-1]]:
            with self.assertRaises(AssertionError):metrics.aggregate(bad,TASKS,score)

    def test_control_deadline_remains_in_denominator_candidate_clean_required(self):
        rows,p=material()
        c=next(r for r in rows if r['task'].startswith('Prob070') and r['arm']=='C')
        c.update(solve_deadline_reached=True,actual_model_requests=2,received_model_responses=1,solve_elapsed_s=300.)
        c['verdict'].update(level=0,coefficient=0.)
        a=metrics.aggregate(rows,TASKS,score);self.assertEqual(a['coefficients']['C'],7/8)
        self.assertEqual(a['unconfirmed_attempts'],1);self.assertTrue(metrics.decision(a,p,rows)['qualified_for_new_full_regression'])
        d=next(r for r in rows if r['task']==c['task'] and r['arm']=='D')
        d['solve_deadline_reached']=True
        self.assertFalse(metrics.decision(metrics.aggregate(rows,TASKS,score),p,rows)['qualified_for_new_full_regression'])

    def test_no_gain_no_trigger_single_trigger_or_different_first_never_qualifies(self):
        rows,p=material();a=metrics.aggregate(rows,TASKS,score)
        self.assertFalse(metrics.decision(a,p,rows)['qualified_for_new_full_regression'])
        for r in rows:
            if r['arm']=='D':r['solve_elapsed_s']=1.
        a=metrics.aggregate(rows,TASKS,score);self.assertTrue(metrics.decision(a,p,rows)['qualified_for_new_full_regression'])
        bad=copy.deepcopy(p)
        for r in bad:
            if r['task'].startswith('Prob070') and r['arm']=='D':r['first_reply_sha256']='different'
        self.assertFalse(metrics.decision(a,bad,rows)['qualified_for_new_full_regression'])
        for r in p:r['context_receipts']=[]
        self.assertFalse(metrics.decision(a,p,rows)['qualified_for_new_full_regression'])

    def test_guard_regression_or_candidate_unconfirmed_rejects_positive_mean(self):
        rows,p=material()
        for r in rows:
            if r['task'].startswith('Prob070') and r['arm']=='C':r['verdict'].update(level=0,coefficient=0.)
        for field,value in [('received_model_responses',0),('solve_deadline_reached',True)]:
            bad=copy.deepcopy(rows);next(r for r in bad if r['arm']=='D')[field]=value
            self.assertFalse(metrics.decision(metrics.aggregate(bad,TASKS,score),p,bad)['qualified_for_new_full_regression'])
        next(r for r in rows if r['task']==metrics.GUARDS[0] and r['arm']=='D')['verdict'].update(level=1,coefficient=.2)
        self.assertFalse(metrics.decision(metrics.aggregate(rows,TASKS,score),p,rows)['qualified_for_new_full_regression'])


if __name__=='__main__':unittest.main()
