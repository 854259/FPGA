import copy
import importlib.util
from pathlib import Path
import unittest
import metrics

ROOT = Path(__file__).resolve().parent
s = importlib.util.spec_from_file_location('edge_pinned_score', ROOT/'raw_evidence/test_fixtures/score.py')
score = importlib.util.module_from_spec(s)
s.loader.exec_module(score)
TASKS = sorted(metrics.EDGES+metrics.GUARDS+[metrics.UNKNOWN])


def material():
    rows, provenance = [], []
    for t, a in metrics.order(TASKS):
        level = 1 if t == metrics.UNKNOWN or t in metrics.EDGES and a == 'C' else 3
        rows.append(dict(task=t, arm=a, verdict=dict(task_id=t, level=level, coefficient={1:.2,3:1.}[level],
                         tool_error=None, elapsed_s=1.), actual_model_requests=2 if t in metrics.EDGES and a=='E' else 1,
                         received_model_responses=2 if t in metrics.EDGES and a=='E' else 1,
                         solve_deadline_reached=False, solve_elapsed_s=10.))
        edge = t in metrics.EDGES and a == 'E'
        checks = [dict(index='map_check_0', status='fail', checks=80, mismatches=20),
                  dict(index='map_check_1', status='pass', checks=80, mismatches=0)] if edge else []
        provenance.append(dict(task=t, arm=a, first_reply_sha256=t, original_repair_feedback_bound=True,
                               contract_status='supported' if edge else 'abstain',
                               contract_family='edge' if edge else None, native_checks=checks))
    return rows, provenance


def decide(rows, p):
    return metrics.decision(metrics.aggregate(rows, TASKS, score), p, rows)['qualified_for_new_full_regression']


class Metrics(unittest.TestCase):
    def test_fixed_complete_order_and_all_eight_denominators(self):
        rows, p = material()
        self.assertTrue(decide(rows, p))
        self.assertEqual(metrics.aggregate(rows, TASKS, score)['coefficients'], dict(C=.7,E=.9))
        for bad in [rows[:-1], rows+[rows[0]], rows[::-1]]:
            with self.assertRaises(AssertionError):
                metrics.aggregate(bad, TASKS, score)

    def test_either_arm_deadline_or_unconfirmed_retained_and_rejects(self):
        rows, p = material()
        for arm in metrics.ARMS:
            for field, value in [('solve_deadline_reached', True), ('received_model_responses', 0)]:
                bad = copy.deepcopy(rows)
                next(r for r in bad if r['arm']==arm)[field] = value
                self.assertFalse(decide(bad, p))

    def test_no_real_two_task_chain_no_qualification(self):
        rows, p = material()
        for field, value in [('first_reply_sha256', 'different'), ('original_repair_feedback_bound', False),
                             ('contract_family', None), ('native_checks', [])]:
            bad = copy.deepcopy(p)
            next(r for r in bad if r['task']==metrics.EDGES[0] and r['arm']=='E')[field]=value
            self.assertFalse(decide(rows, bad))
        bad = copy.deepcopy(p)
        next(r for r in bad if r['task']==metrics.EDGES[0] and r['arm']=='E')['native_checks'][1].update(status='fail',mismatches=1)
        self.assertFalse(decide(rows, bad))

    def test_guard_or_unknown_changes_extra_cost_and_tool_error_reject(self):
        rows, p = material()
        bad = copy.deepcopy(rows)
        next(r for r in bad if r['task']==metrics.GUARDS[0] and r['arm']=='E')['verdict'].update(level=1,coefficient=.2)
        self.assertFalse(decide(bad,p))
        bad = copy.deepcopy(rows)
        next(r for r in bad if r['task']==metrics.UNKNOWN and r['arm']=='E')['verdict'].update(level=3,coefficient=1.)
        self.assertFalse(decide(bad,p))
        bad = copy.deepcopy(rows)
        next(r for r in bad if r['task']==metrics.GUARDS[0] and r['arm']=='E').update(actual_model_requests=2,received_model_responses=2)
        self.assertFalse(decide(bad,p))
        bad = copy.deepcopy(rows)
        bad[0]['verdict']['tool_error']='environment'
        with self.assertRaises(AssertionError):
            metrics.aggregate(bad,TASKS,score)

    def test_execution_success_is_not_production_or_independent_qualification(self):
        rows,p=material()
        result=metrics.decision(metrics.aggregate(rows,TASKS,score),p,rows)
        self.assertTrue(result['qualified_for_new_full_regression'])
        self.assertTrue(result['previous_full_gate_still_failed'])
        self.assertFalse(result['adoption'])
        self.assertFalse(result['independent_validation_qualified'])
        self.assertFalse(result['five_sample_qualified'])


if __name__ == '__main__':unittest.main()
