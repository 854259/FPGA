"""AMD-only real production entry qualification under an external whole-task lease.

Exercise the declared prefix through the actual frozen queue, not substitute
workers or resource checks. An incomplete solve keeps its unknown grade/cost.
This entry never makes a full-batch score or adoption claim.
"""
import argparse
import ctypes
import json
from pathlib import Path
import sys

import three_arm_queue_20261005 as queue
import official_baseline_arm_20261005 as official


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--resource-check', type=Path, required=True)
    args = parser.parse_args()
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    root = args.root.resolve()
    assert root == Path(__file__).resolve().parent
    assert official.sha(root/'PLAN.json') == args.plan_sha256
    plan = json.loads((root/'PLAN.json').read_bytes())
    assert plan['qualification_only'] is True and plan['execution_authorized'] is True
    selection = plan['engineering_prefix']
    count = selection['rows']
    assert count == 4 and len(plan['rows']) == 6
    assert [r['arm'] for r in plan['rows'][:count]] == ['A', 'A', 'P', 'B']
    assert sum(r['reserved_calls'] for r in plan['rows'][:count]) == 7
    assert not (root/'qualification_queue').exists()
    resource = official.resource_module()
    resource.check_resource(args.resource_check, Path(plan['kit']), first=True)
    resource.model_idle('http://127.0.0.1:8000/v1', plan['model'])
    queue.validate(plan)
    out = root/'qualification_queue'
    results = []
    # advance seals a failure before admitting the next row. There is no retry.
    for index in range(count):
        progress = queue.advance(plan, out, args.resource_check,
            lambda argv, row, folder: queue.execute_row(plan, argv, row, folder, args.resource_check))
        assert progress['executed_key'] == plan['rows'][index]['key']
        folder = out/('row_'+str(index).zfill(6))
        terminal = queue.verify_terminal(folder, plan['rows'][index], queue.digest(plan))
        failed = (folder/'FAILED_SEALED.json').is_file()
        result = dict(index=index, arm=plan['rows'][index]['arm'],
            row_key=plan['rows'][index]['key'], inspected_failure=failed,
            terminal_sha256=official.sha(folder/'TERMINAL.json'),
            complete=terminal['complete'], actual_calls=terminal['actual_calls'])
        if failed:
            seal=json.loads((folder/'FAILED_SEALED.json').read_bytes())
            result.update(failure_basis=seal['failure_basis'],
                inspected_model_idle=seal['inspection']['processing_slots']==0,
                owned_solver_reaped_and_group_clear=seal['inspection']['owned_solver_reaped_and_group_clear'])
        results.append(result)
        queue.save(root/'QUALIFICATION_PROGRESS.json', dict(rows=results, score_eligible=False))
    idle = resource.model_idle('http://127.0.0.1:8000/v1', plan['model'])
    resource.check_resource(args.resource_check, Path(plan['kit']))
    queue.validate(plan)
    first = results[0]
    cancelled = first['inspected_failure'] and first.get('failure_basis')=='owned_worker_budget_expired'
    later_complete = all(r['complete'] and not r['inspected_failure'] for r in results[1:])
    result=dict(schema='real_production_entries_budget_qualification_v1',
        complete=True, passed=bool(cancelled and later_complete),
        physical_parent_clock=True, resource_and_model_admission_simulated=False,
        real_shared_model=True, real_A_P_B_entry=True,
        budget_failure_then_actual_queue_continuation=bool(cancelled and later_complete),
        source_bound_failed_row_unknown_grade_and_cost=bool(cancelled),
        rows=results, prepared_rows=len(plan['rows']), intentionally_unattempted_rows=2,
        prefix_only=True, full_score_batch=False, score_eligible=False,
        no_retries=True, max_reserved_model_requests=7,
        idle_after=idle, full156=False, full_goal_complete=False,
        plan_sha256=official.sha(root/'PLAN.json'),
        spec_sha256=official.sha(root/'RUN_SPEC.json'),
        limitation='Shared-model CLI/queue qualification only; submission HTTP contract and full156 capability/cost regression remain separate.',
        missing=[] if cancelled and later_complete else ['Expected budget cancellation/continuation not demonstrated; inspect originals, do not resample.'])
    queue.save(root/'QUALIFICATION_RESULT.json', result)
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
