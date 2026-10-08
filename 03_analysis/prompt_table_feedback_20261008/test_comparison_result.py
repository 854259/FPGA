"""AMD-only synthetic checks for official five-sample aggregation; no scoring."""
import copy
import json
from pathlib import Path
import sys
import comparison_result as summary


def main(root):
    score = Path('/workspace/team/tasks/autodl-rtl-kit/project/official_reference/selftest/score.py')
    assert summary.sha(score) == summary.SCORE_SHA
    official = summary.load('official_scoring_for_control', score)
    rows = []
    for task in ('SyntheticAlpha', 'SyntheticBeta'):
        for arm in ('A', 'P', 'B'):
            for sample in range(5):
                level = (3 if task == 'SyntheticAlpha' else 0) if arm == 'A' else 1
                if arm == 'P' and task == 'SyntheticAlpha' and sample < 4:
                    level = 3
                rows.append(dict(task=task, arm=arm, sample=sample,
                                 verdict=dict(task_id=task, level=level, coefficient=summary.WEIGHTS[level],
                                              tool_error=None, elapsed_s=1),
                                 calls=1, solve_s=2, judge_s=1, row_s=3))
    tasks = ['SyntheticAlpha', 'SyntheticBeta']
    good = summary.summarize(rows, tasks, official)
    assert abs(good['P_minus_A_mean']-.02) < 1e-12
    a, p = good['arms']['A'], good['arms']['P']
    assert a['official_summary']['level_counts']['L3'] == 5
    assert p['official_summary']['level_counts']['L3'] == 4
    assert p['official_summary']['pass@1'] == .52 and p['official_summary']['pass@5'] == .6
    assert p['same_run_official_baseline_gain'] == 2.6
    assert p['observed_solve_s'] == 20 and p['model_requests'] == 10
    zero = copy.deepcopy(rows)
    for row in zero:
        if row['arm'] == 'B':
            row['verdict'].update(level=0, coefficient=0.)
    assert summary.summarize(zero, tasks, official)['arms']['P']['same_run_official_baseline_gain'] is None
    invalid = [('missing_sample', rows[:-1]), ('duplicate_sample', rows[:-1]+[rows[0]])]
    for label, field, value in [('zero_call', 'calls', 0), ('third_call', 'calls', 3),
                                ('nan_time', 'solve_s', float('nan')), ('negative_time', 'judge_s', -1),
                                ('boolean_sample', 'sample', True)]:
        bad = copy.deepcopy(rows)
        bad[0][field] = value
        invalid.append((label, bad))
    for label, field, value in [('false_coefficient', 'coefficient', .7),
                                ('tool_error', 'tool_error', 'FAKE_LICENSE_ERROR'),
                                ('wrong_task', 'task_id', 'OtherSynthetic')]:
        bad = copy.deepcopy(rows)
        bad[0]['verdict'][field] = value
        invalid.append((label, bad))
    checks = ['official_mean_not_best', 'higher_weighted_with_fewer_L3', 'same_run_baseline', 'zero_baseline_unknown']
    for label, bad in invalid:
        try:
            summary.summarize(bad, tasks, official)
        except AssertionError:
            checks.append(label)
        else:
            raise AssertionError('accepted '+label)
    result = dict(passed=True, synthetic_only=True, checks=checks, model_calls=0, eda_calls=0,
                  real_results_read=0, official_score_sha256=summary.SCORE_SHA,
                  reader_sha256=summary.sha(Path(summary.__file__)),
                  test_sha256=summary.sha(__file__))
    with (root/'CONTROL_RESULT.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    main(Path(sys.argv[1]).resolve())

