"""Pure FAKE cohort/scorer fixtures; never model, EDA or quality evidence."""
import copy
import unittest

import metrics


TARGETS = ['Prob089_ece241_2014_q5a', 'Prob111_fsm2s', 'Prob133_2014_q3fsm', 'Prob139_2013_q2bfsm', 'Prob146_fsm_serialdata', 'Prob149_ece241_2013_q4', 'Prob150_review2015_fsmonehot', 'Prob154_fsm_ps2data']
GUARDS = ['Prob045_edgedetect2', 'Prob054_edgedetect', 'Prob058_alwaysblock2',
          'Prob071_always_casez', 'Prob112_always_case2', 'Prob115_shift18']
TASKS = sorted(TARGETS + GUARDS)
COEFFICIENTS = {0: 0., 1: .2, 2: .7, 3: 1.}


class FakeScorer:
    @staticmethod
    def summarize(samples):
        verdicts = [verdict for values in samples.values() for verdict in values]
        return dict(tasks=len(samples), scored_tasks=len(samples),
                    tool_errors=sum(bool(v['tool_error']) for v in verdicts),
                    samples_per_task=1,
                    normalized_score=sum(v['coefficient'] for v in verdicts) / len(samples))


def material():
    """Three target gains, total P=C+2; all first replies deliberately differ."""
    rows, provenance = [], []
    for i, task in enumerate(TASKS):
        for arm in (['C', 'P'] if i % 2 == 0 else ['P', 'C']):
            improved = task in TARGETS[:3] and arm == 'P'
            level = 3 if task in GUARDS or improved else 1
            calls = 2 if task in TARGETS[:2] and arm == 'P' else 1
            rows.append(dict(task=task, arm=arm,
                             verdict=dict(task_id=task, level=level,
                                          coefficient=COEFFICIENTS[level],
                                          tool_error=None, elapsed_s=1.),
                             actual_model_requests=calls, received_model_responses=calls,
                             solve_deadline_reached=False, solve_elapsed_s=10.))
            provenance.append(dict(task=task, arm=arm,
                                   first_reply_sha256='FAKE:' + arm + ':' + task,
                                   original_repair_feedback_bound=True,
                                   skill_messages_bound=True,
                                   contract_status='abstain', contract_family=None,
                                   native_checks=[]))
    return rows, provenance


def sample(rows, task, arm):
    return next(row for row in rows if row['task'] == task and row['arm'] == arm)


def grade(row, level):
    row['verdict'].update(level=level, coefficient=COEFFICIENTS[level])


def decide(rows, provenance):
    return metrics.decision(metrics.aggregate(rows, TASKS, FakeScorer), provenance, rows)


class Metrics(unittest.TestCase):
    def test_fixed_fourteen_tasks_twentyeight_samples_and_fourteen_task_denominators(self):
        rows, provenance = material()
        self.assertEqual(sorted(metrics.TARGETS), TARGETS)
        self.assertEqual(sorted(metrics.GUARDS), GUARDS)
        self.assertEqual(len(TASKS), 14)
        self.assertEqual(len(rows), 28)
        result = metrics.aggregate(rows, TASKS, FakeScorer)
        self.assertAlmostEqual(result['coefficients']['C'], 7.6/14)
        self.assertAlmostEqual(result['coefficients']['P'], 10./14)
        self.assertEqual(result['improved_target_tasks'], TARGETS[:3])
        self.assertEqual(result['requests_by_arm'], dict(C=14, P=16))
        for arm in ['C', 'P']:
            self.assertEqual(result['official_scores'][arm]['scored_tasks'], 14)
        self.assertTrue(decide(rows, provenance)['qualified_for_new_full_regression'])

    def test_missing_duplicate_reversed_or_wrong_cohort_is_rejected(self):
        rows, _ = material()
        for bad in [rows[:-1], rows + [rows[0]], rows[::-1]]:
            with self.subTest(samples=len(bad)), self.assertRaises(AssertionError):
                metrics.aggregate(bad, TASKS, FakeScorer)
        for tasks in [TASKS[:-1], TASKS + [TASKS[0]], TASKS[::-1],
                      sorted(TASKS[:-1] + ['FAKE_other_task'])]:
            with self.subTest(tasks=tasks), self.assertRaises(AssertionError):
                metrics.aggregate(rows, tasks, FakeScorer)

    def test_different_first_replies_and_no_old_edge_chain_can_qualify(self):
        rows, provenance = material()
        for task in TASKS:
            self.assertNotEqual(sample(provenance, task, 'C')['first_reply_sha256'],
                                sample(provenance, task, 'P')['first_reply_sha256'])
        self.assertTrue(all(not row['native_checks'] for row in provenance))
        self.assertTrue(decide(rows, provenance)['qualified_for_new_full_regression'])

    def test_one_target_gain_or_no_mean_gain_cannot_qualify(self):
        rows, provenance = material()
        grade(sample(rows, TARGETS[2], 'P'), 1)
        grade(sample(rows, TARGETS[1], 'P'), 1)
        sample(rows, TARGETS[1], 'P').update(actual_model_requests=1, received_model_responses=1)
        result = metrics.aggregate(rows, TASKS, FakeScorer)
        self.assertGreater(result['coefficients']['P'], result['coefficients']['C'])
        self.assertEqual(result['improved_target_tasks'], TARGETS[:1])
        self.assertFalse(decide(rows, provenance)['qualified_for_new_full_regression'])
        grade(sample(rows, TARGETS[0], 'P'), 1)
        sample(rows, TARGETS[0], 'P').update(actual_model_requests=1, received_model_responses=1)
        self.assertFalse(decide(rows, provenance)['qualified_for_new_full_regression'])

    def test_three_partial_target_gains_do_not_require_l3_repairs(self):
        rows, provenance = material()
        for task in TARGETS[:3]:
            grade(sample(rows, task, 'C'), 0)
            grade(sample(rows, task, 'P'), 1)
            sample(rows, task, 'P').update(actual_model_requests=1, received_model_responses=1)
        result = metrics.aggregate(rows, TASKS, FakeScorer)
        self.assertEqual(result['improved_target_tasks'], TARGETS[:3])
        self.assertTrue(decide(rows, provenance)['qualified_for_new_full_regression'])

    def test_any_target_regression_rejects_even_when_mean_still_rises(self):
        rows, provenance = material()
        grade(sample(rows, TARGETS[-1], 'P'), 0)
        result = metrics.aggregate(rows, TASKS, FakeScorer)
        self.assertGreater(result['coefficients']['P'], result['coefficients']['C'])
        self.assertIn(TARGETS[-1], result['regressions'])
        self.assertFalse(decide(rows, provenance)['qualified_for_new_full_regression'])

    def test_each_guard_must_be_l3_in_both_arms(self):
        rows, provenance = material()
        for task in GUARDS:
            for arm in ['C', 'P']:
                bad = copy.deepcopy(rows)
                grade(sample(bad, task, arm), 2)
                with self.subTest(task=task, arm=arm):
                    self.assertFalse(decide(bad, provenance)['qualified_for_new_full_regression'])

    def test_guard_p_calls_cannot_increase_even_inside_total_plus_two_cap(self):
        rows, provenance = material()
        sample(rows, TARGETS[0], 'P').update(actual_model_requests=1, received_model_responses=1)
        sample(rows, GUARDS[0], 'P').update(actual_model_requests=2, received_model_responses=2)
        result = metrics.aggregate(rows, TASKS, FakeScorer)
        self.assertEqual(result['requests_by_arm']['P'], result['requests_by_arm']['C'] + 2)
        self.assertFalse(decide(rows, provenance)['qualified_for_new_full_regression'])

    def test_fewer_guard_p_calls_are_allowed(self):
        rows, provenance = material()
        sample(rows, GUARDS[0], 'C').update(actual_model_requests=2, received_model_responses=2)
        self.assertTrue(decide(rows, provenance)['qualified_for_new_full_regression'])

    def test_total_plus_three_calls_rejects_without_guard_call_increase(self):
        rows, provenance = material()
        sample(rows, TARGETS[2], 'P').update(actual_model_requests=2, received_model_responses=2)
        result = metrics.aggregate(rows, TASKS, FakeScorer)
        self.assertEqual(result['requests_by_arm']['P'], result['requests_by_arm']['C'] + 3)
        self.assertFalse(decide(rows, provenance)['qualified_for_new_full_regression'])

    def test_either_arm_deadline_or_unconfirmed_attempt_is_retained_and_rejects(self):
        rows, provenance = material()
        for arm in ['C', 'P']:
            for field, value in [('solve_deadline_reached', True), ('received_model_responses', 0)]:
                bad = copy.deepcopy(rows)
                sample(bad, GUARDS[0], arm)[field] = value
                result = metrics.aggregate(bad, TASKS, FakeScorer)
                with self.subTest(arm=arm, field=field):
                    if field == 'solve_deadline_reached':
                        self.assertIn(dict(task=GUARDS[0], arm=arm), result['solve_deadlines'])
                    else:
                        self.assertEqual(result['unconfirmed_attempts'], 1)
                    self.assertFalse(decide(bad, provenance)['qualified_for_new_full_regression'])

    def test_environment_error_and_invalid_request_counts_are_rejected(self):
        rows, _ = material()
        bad = copy.deepcopy(rows)
        bad[0]['verdict']['tool_error'] = 'FAKE_environment_failure'
        with self.assertRaises(AssertionError):
            metrics.aggregate(bad, TASKS, FakeScorer)
        for actual, received in [(0, 0), (3, 3), (1, 2)]:
            bad = copy.deepcopy(rows)
            bad[0].update(actual_model_requests=actual, received_model_responses=received)
            with self.subTest(actual=actual, received=received), self.assertRaises(AssertionError):
                metrics.aggregate(bad, TASKS, FakeScorer)

    def test_every_sample_requires_both_repair_and_skill_message_provenance(self):
        rows, provenance = material()
        for index in range(len(provenance)):
            for field in ['original_repair_feedback_bound', 'skill_messages_bound']:
                bad = copy.deepcopy(provenance)
                bad[index][field] = False
                with self.subTest(index=index, field=field):
                    self.assertFalse(decide(rows, bad)['qualified_for_new_full_regression'])

    def test_qualification_only_permits_new_full_and_keeps_other_flags_false(self):
        rows, provenance = material()
        result = decide(rows, provenance)
        self.assertTrue(result['qualified_for_new_full_regression'])
        self.assertTrue(result['prior_phase_full_qualification_unchanged'])
        self.assertFalse(result['adoption'])
        self.assertFalse(result['independent_validation_qualified'])
        self.assertFalse(result['five_sample_qualified'])


if __name__ == '__main__':
    unittest.main()
