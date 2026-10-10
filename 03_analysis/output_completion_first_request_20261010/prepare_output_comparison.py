"""Freeze the fixed temporal first-request comparison on AMD; no admission here.

Preserve original132 queue, official baseline, evaluator and repair budgets.
The qualification prototype is read-only and is never run as a real evaluation.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

PARENT_SPEC = 'b499f6c16fa91868ca7ba60a168929204f02d5b0e164f5ade776a65983aa5c5d'
PARENT_PLAN = 'c85226725bab88c08503cd9feda393378ef17c491fabebec4bea0abd930d954c'
SCORE_SHA = '2b382a41fa2d357d021c09d41b65bdfcd598149f038f4c9b571ef48d74816768'
CHANGED = {
    'baseline_worker.py': '17ff2b54cdbc469a631e6dcc29446726f00612f755e9d823699f779bf0870e11',
    'worker.py': '1dba9741da82e79e24db62b1ccb767920320f6b8b73477de6e635ef584897d65',
    'first_system_request.py': '65da3d134b7b1c3e57a24a6e8d6c78869644542d8865b444c20a63ba6b900a10',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(args):
    root, parent, qualified, packet, kit = map(Path.resolve,
        (args.out, args.parent, args.qualified, args.packet, args.kit))
    assert not root.exists() and root.parent == Path('/workspace/team/runs/fpga_owner')
    assert sha(parent/'RUN_SPEC.json') == PARENT_SPEC and sha(parent/'PLAN.json') == PARENT_PLAN
    parent_spec = read(parent/'RUN_SPEC.json')
    parent_plan = read(parent/'PLAN.json')
    assert len(parent_spec['source_hashes']) == 26
    assert all(sha(parent/n) == h for n, h in parent_spec['source_hashes'].items())
    qualified_spec = read(qualified/'RUN_SPEC.json')
    assert qualified_spec['qualification_only'] and not qualified_spec['execution_authorized']
    assert qualified_spec['model'] == 'PURE_SYNTHETIC_MODEL_NO_HTTP'
    qualification = read(packet/'QUALIFICATION_READBACK.json')
    receipt = qualification['receipt']
    assert receipt['passed'] and receipt['returncode'] == 0
    assert receipt['owned_child_reaped'] and receipt['actual_identity_retired']
    assert qualification['result']['passed']
    assert all(sha(qualified/n) == h for n, h in receipt['source_hashes'].items())
    assert all(sha(qualified/n) == h for n, h in CHANGED.items())
    assert all(sha(qualified/n) == h for n, h in parent_spec['source_hashes'].items()
               if n not in CHANGED)
    preflight = read(packet/'INPUT_PREFLIGHT.json')
    preregister = read(packet/'PREREGISTER.json')
    assert preflight['passed'] and preflight['first_context_capacity_conservatively_passed']
    assert preflight['context_tokens'] == 16384 and preflight['output_max_tokens'] == 8192
    assert not preflight['all_possible_repair_capacity_proven']
    assert len(preflight['rows']) == len(preregister['tasks']) == 5
    assert sorted(r['task'] for r in preflight['rows']) == sorted(preregister['tasks'])
    assert preregister['expected_outputs'] == 75 and preregister['max_reserved_requests'] == 125
    assert sha(args.official_score) == SCORE_SHA
    root.mkdir()
    save(root/'PREPARATION_INTENT.json', dict(model_max=0, eda_max=0, fifo_max=0,
        parent_spec_sha256=PARENT_SPEC, parent_plan_sha256=PARENT_PLAN,
        selected_tasks=preregister['tasks']))
    source_hashes = {}
    for n in [*parent_spec['source_hashes'], 'first_system_request.py']:
        p = root/n
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(qualified/n, p)
        source_hashes[n] = sha(p)
    for name, source in [('comparison_result.py', packet/'comparison_result.py'),
                         ('prepare_temporal_comparison.py', Path(__file__))]:
        shutil.copyfile(source, root/name)
        source_hashes[name] = sha(root/name)
    assert len(source_hashes) == 29
    spec = dict(parent_spec, schema='output_completion_first_request_model_comparison_v1',
        identity=root.name, cloud_root=str(root), model=parent_spec['model'],
        dependencies_cloud=str(root/'dependencies'), source_hashes=source_hashes,
        model_generated_rtl_only=True, execution_authorized=True, qualification_only=False,
        parent_spec_sha256=PARENT_SPEC, parent_plan_sha256=PARENT_PLAN,
        qualification_result_sha256=sha(qualified/'QUALIFICATION_RESULT.json'),
        qualification_process_receipt_sha256=sha(qualified/'PROCESS_RECEIPT.json'),
        qualification_archive_sha256=qualification['archive_sha256'],
        preflight_sha256=sha(packet/'INPUT_PREFLIGHT.json'),
        preregister_sha256=sha(packet/'PREREGISTER.json'),
        factor='Generic concise complete RTL instruction on first system only; unchanged original132 single-counterexample table-P feedback in both arms',
        arm_definitions=preregister['arm_meanings'])
    assert spec['model'] == 'Qwen3.6-27B-Q4_K_M'
    save(root/'RUN_SPEC.json', spec)
    tasks = []
    for item in preflight['rows']:
        template = item['row_template']
        task = template['task']
        original = [r for r in parent_plan['rows'] if r['task'] == task and r['sample'] == 0 and r['arm'] == 'P']
        assert original == [template]
        target = root/'inputs'/task
        target.mkdir(parents=True)
        for name, digest in template['input_hashes'].items():
            assert name in ('prompt.txt', 'interface.txt')
            source = Path(template['task_dir'])/name
            assert sha(source) == digest
            shutil.copyfile(source, target/name)
        tasks.append(dict(dataset=template['dataset'], task=task,
            family=template['family'], use=template['use'], task_dir=str(target),
            hashes=template['input_hashes'], evaluator_dir=template['evaluator_dir'],
            evaluator_hashes=template['evaluator_hashes']))
    sys.path.insert(0, str(root))
    queue = load('temporal_original132_queue', root/'three_arm_queue_20261005.py')
    sources = dict(root=str(root), model_feedback=True, files={
        **{str(root/n): h for n, h in source_hashes.items()},
        str(root/'RUN_SPEC.json'): sha(root/'RUN_SPEC.json')})
    plan = queue.build_plan(tasks, 5, sources, root/'official_baseline_arm_20261005.py', kit, 125, 43200)
    plan.update(execution_authorized=True, model_generated_rtl_only=True,
        arm_definitions=spec['arm_definitions'], factor=spec['factor'],
        historical_correct_controls=preregister['historical_correct_controls'],
        development_targets=preregister['development_tasks'], independent_unseen=0,
        formal_adoption=False, full156=False, full_goal_complete=False,
        active_full156_completion_gates_evaluated=False,
        data_selection='Fixed five tasks preregistered before execution; no new-result task additions',
        selection_policy='Report unchanged official summary, same-run baseline gain and all paired/historical/call diagnostics. No automatic adoption; this subset cannot complete the active full156 goal.',
        first_capacity_preflight_sha256=spec['preflight_sha256'],
        all_future_repairs_fit_proven=False, retries=0)
    assert len(plan['rows']) == 75 and plan['required_reserved_calls'] == 125
    assert (plan['solve_deadline_s'], plan['solve_supervisor_s'], plan['judge_supervisor_s'], plan['row_reservation_s']) == (300, 310, 360, 670)
    queue.validate(plan)
    save(root/'PLAN.json', plan)
    # Check the previously retained positive cases through the unchanged scoring
    # bridge. Reading/binding only: no generation, compilation, judging or replay.
    bridge = load('temporal_original_bridge', root/'official_baseline_scoring_20261005.py')
    old_model = bridge.arm.MODEL
    checked = []
    try:
        bridge.arm.MODEL = qualified_spec['model']
        for outer, case in [('A', 'C_two_requests'), ('P', 'P_two_requests')]:
            solve = qualified/'cases'/case
            bound = bridge.eligible(solve, solve/'prompt_only', outer, model_source=qualified)
            assert bound['arm'] == outer and bound['model_binding']['worker_arm'] == 'P'
            assert bound['client_request_attempts'] == 2
            checked.append(dict(outer_arm=outer, worker_arm='P', retained_case=case,
                requests=bound['client_request_attempts'], model_generated_rtl_bound=True))
    finally:
        bridge.arm.MODEL = old_model
    assert bridge.arm.MODEL == old_model
    reader = load('temporal_completed_reader', root/'comparison_result.py')
    assert reader.EXPECTED_WORKER_ARMS == {'A': 'P', 'P': 'P'}
    save(root/'SCORING_INTERFACE_READBACK.json', dict(passed=True, retained_cases=checked,
        original_scoring_bridge_unchanged=True, new_model_calls=0, new_eda_calls=0,
        source_qualification_not_rerun=True, synthetic_only=True))
    assert all(sha(root/n) == h for n, h in source_hashes.items())
    assert all(sha(parent/n) == h for n, h in parent_spec['source_hashes'].items())
    assert all(sha(qualified/n) == h for n, h in receipt['source_hashes'].items())
    save(root/'PREPARATION_RESULT.json', dict(complete=True, prepared=True, submitted=False,
        model_calls=0, eda_calls=0, fifo_calls=0, tasks=len(preregister['tasks']), outputs=len(plan['rows']), max_calls=plan['required_reserved_calls'],
        spec_sha256=sha(root/'RUN_SPEC.json'), plan_sha256=sha(root/'PLAN.json'),
        sources_held=True, parent_sources_held=True, qualification_sources_held=True,
        original_queue_and_official_B_and_judge_unchanged=True, scoring_interface_passed=True,
        execution_authorized=True, admission_requires_root_review=True,
        safety_caps=dict(queue_wall_s=43200, proposed_stage_cap_s=43320,
            proposed_guard_s=43500, proposed_fifo_slot_minutes=730),
        terminal_reader_sha256=sha(root/'comparison_result.py'),
        official_score_sha256=SCORE_SHA, official_score=str(args.official_score),
        terminal_reader=str(root/'comparison_result.py')))


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    parser = argparse.ArgumentParser()
    for name in ('out', 'parent', 'qualified', 'packet', 'kit', 'official-score'):
        parser.add_argument('--'+name, type=Path, required=True)
    prepare(parser.parse_args())
