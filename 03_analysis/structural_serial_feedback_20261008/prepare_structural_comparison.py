"""AMD-only structural-factor preparation; reuse qualified A/P/B queue.

No model, EDA, FIFO submission or continuation occurs here. A partial preparation
is retained; choose a new reviewed identity rather than rerunning over it.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

INTAKE_SHA = '507d8b1af34dc0b132d1143a2bbdb60019bef49e7e261df967c1b3f25e18e97d'
PURE_SHA = '4a355fb9fc5413061c0dd57cd8ae88302b4c3a733727058e99c6ff246c84cc3b'
QUALIFIED_SPEC_SHA = 'ce62b7261c8b2a3344ec45a6f91ad3adaff7446400181e4147a96f315368e1f7'
PEER_SPEC_SHA = '317e40d723e7c0956a11143fc914b1841e036fe871a0ffba415f0939c90399da'
READER_SHA = 'f270b078e4f96b93dab231d26dec8af24d53bc23a69123ada4679fe6b609ca39'
SCORE_SHA = '2b382a41fa2d357d021c09d41b65bdfcd598149f038f4c9b571ef48d74816768'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def prepare(args):
    root, qualified, intake_root, peer = map(Path.resolve,
        (args.out, args.qualified_root, args.intake_root, args.peer_root))
    kit = args.kit.resolve()
    assert not root.exists() and root.is_relative_to(Path('/workspace/team/runs/fpga_owner'))
    assert root not in (qualified, intake_root, peer)
    assert not any(root.is_relative_to(p) or p.is_relative_to(root) for p in (qualified, intake_root, peer))
    assert sha(peer / 'RUN_SPEC.json') == PEER_SPEC_SHA
    peer_spec = read(peer / 'RUN_SPEC.json')
    binding_path = qualified / 'results/RESULT.json'
    assert len(args.qualification_result_sha256) == 64
    assert sha(binding_path) == args.qualification_result_sha256
    assert sha(qualified / 'RUN_SPEC.json') == QUALIFIED_SPEC_SHA
    binding, qualified_spec = read(binding_path), read(qualified / 'RUN_SPEC.json')
    assert qualified_spec['schema'] == 'structural_serial_feedback_binding_controls_v1'
    assert qualified_spec['qualification_only'] is True
    assert qualified_spec['model_generated_rtl_only'] is True
    assert qualified_spec['cloud_root'] == str(qualified)
    assert binding['complete'] and binding['passed'] and binding['simulated_controls']
    assert binding['sources_unchanged'] and binding['originals_unchanged']
    assert binding['new_model_calls'] == binding['new_eda_calls'] == binding['old_native_reruns'] == 0
    expected_controls = {'A_uses_original_serial', 'P_conflict', 'P_no_conflict',
        'flow_A_serial', 'flow_P_append', 'flow_P_empty', 'reject_missing_record',
        'reject_source_hash', 'reject_diagnostic_fact', 'reject_combined_file', 'reject_next_request'}
    assert len(binding['reports']) == 11 and all(row['passed'] for row in binding['reports'])
    assert {row['control'] for row in binding['reports']} == expected_controls
    assert binding['source_sha256'] == qualified_spec['source_hashes']
    assert len(binding['source_sha256']) == 36
    qualification_receipt = read(qualified / 'EXECUTION_RECEIPT.json')
    assert qualification_receipt['passed'] and qualification_receipt['protected_held']
    assert qualification_receipt['result_sha256'] == args.qualification_result_sha256
    pure_root = Path(qualified_spec['parent_pure_root'])
    assert qualified_spec['parent_pure_result_sha256'] == PURE_SHA
    assert sha(pure_root / 'results/RESULT.json') == PURE_SHA
    pure = read(pure_root / 'results/RESULT.json')
    assert pure['complete'] and pure['passed'] and pure['tests_run'] == 28
    assert pure['source_hashes_held'] and pure['original_candidate_hashes_held']
    assert pure['original_candidate_files'] == 20 and len(pure['actual_replay']) == 6
    assert pure['model_calls'] == pure['eda_commands'] == pure['old_native_or_worker_reruns'] == 0
    assert sha(pure_root / 'SOURCE_MANIFEST.json') == pure['source_manifest_sha256']
    pure_sources = read(pure_root / 'SOURCE_MANIFEST.json')
    for name in ('structural_driver_feedback.py', 'agent_extract_boundary.py', 'reserved_keywords.py'):
        assert sha(pure_root / name) == pure_sources[name] == qualified_spec['source_hashes'][name]
    assert qualified_spec['model'] == peer_spec['model']
    assert qualified_spec['parent_comparison_spec_sha256'] == PEER_SPEC_SHA
    assert sha(intake_root / 'RESULT.json') == INTAKE_SHA
    intake = read(intake_root / 'RESULT.json')
    assert intake['complete'] and intake['tasks'] == len(intake['rows']) == 156
    assert len({row['task'] for row in intake['rows']}) == 156
    assert intake['model_calls'] == intake['eda_calls'] == 0 and not intake['score_inputs_read']
    selected = [row for row in intake['rows'] if row['eligible']]
    assert len(selected) == intake['applicable'] == 2
    assert sha(args.reader) == READER_SHA and sha(args.official_score) == SCORE_SHA
    intake_plan = read(intake_root / 'PLAN.json')
    assert intake_plan['sources']['serial_feedback.py'] == qualified_spec['source_hashes']['serial_feedback.py']
    for name, digest in binding['source_sha256'].items():
        relative = Path(name)
        assert not relative.is_absolute() and '..' not in relative.parts
        assert (qualified / relative).resolve().is_relative_to(qualified)
        assert not (qualified / relative).is_symlink() and sha(qualified / relative) == digest
    root.mkdir()
    save(root / 'PREPARATION_INTENT.json', dict(model_max=0, eda_max=0, fifo_max=0,
        intake_result_sha256=INTAKE_SHA, pure_result_sha256=PURE_SHA,
        binding_result_sha256=args.qualification_result_sha256,
        qualification_spec_sha256=sha(qualified / 'RUN_SPEC.json')))
    # All worker/runtime/skill/queue/official-arm bytes come from the passed
    # binding qualification. No table worker or old mechanical producer enters.
    for name in binding['source_sha256']:
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(qualified / name, dest)
    assert sha(root / 'comparison_result.py') == sha(args.reader) == READER_SHA
    # Preserve the old qualified preparer; never execute it or overwrite its bytes.
    new_preparer = 'prepare_structural_comparison.py'
    assert new_preparer not in binding['source_sha256'] and not (root / new_preparer).exists()
    shutil.copyfile(__file__, root / new_preparer)
    source_hashes = dict(binding['source_sha256'], **{new_preparer: sha(root / new_preparer)})
    assert len(source_hashes) == 37
    spec = dict(schema='serial_scalar_driver_feedback_model_comparison_v1', identity=root.name,
        cloud_root=str(root), model=peer_spec['model'], model_generated_rtl_only=True,
        dependencies_cloud=str(root / 'dependencies'), dependency_hashes=qualified_spec['dependency_hashes'],
        source_hashes=source_hashes, routing_changes=peer_spec['routing_changes'],
        original_baseline_worker_sha256=peer_spec['original_baseline_worker_sha256'],
        parent_comparison_spec_sha256=PEER_SPEC_SHA, parent_qualification_spec_sha256=sha(qualified / 'RUN_SPEC.json'),
        parent_serial_spec_sha256=qualified_spec['parent_serial_spec_sha256'],
        native_controls_result_sha256=qualified_spec['native_controls_result_sha256'],
        parent_serial_binding_result_sha256=qualified_spec['binding_controls_result_sha256'],
        structural_pure_controls_result_sha256=PURE_SHA,
        structural_binding_controls_result_sha256=args.qualification_result_sha256,
        intake_result_sha256=INTAKE_SHA,
        factor='Append candidate-source scalar multi-process driver facts to existing measured serial failure feedback only',
        arm_definitions=dict(A='131 original P serial feedback; internal C unchanged',
            P='Same serial feedback plus source-derived scalar driver facts', B='Untouched official baseline'))
    save(root / 'RUN_SPEC.json', spec)
    tasks = []
    for row in selected:
        task = row['task']
        assert Path(task).name == task and task not in ('.', '..')
        source, target = kit / 'bench/tasks_veval' / task, root / 'inputs' / task
        target.mkdir(parents=True)
        assert set(row['input_sha256']) <= {'prompt.txt', 'interface.txt'}
        for name, digest in row['input_sha256'].items():
            assert sha(source / name) == digest
            shutil.copyfile(source / name, target / name)
        assert not any(p.is_symlink() for p in source.rglob('*'))
        # These are evaluator identities only; evaluator content is never copied
        # into prompt_only or appended to a model request.
        evaluator_hashes = {p.name: sha(p) for p in source.iterdir() if p.is_file()}
        tasks.append(dict(dataset='verilogeval_seen_development', task=task,
            family='prompt_serial_protocol_family_dependence_unknown', use='development',
            task_dir=str(target), hashes=row['input_sha256'], evaluator_dir=str(source),
            evaluator_hashes=evaluator_hashes))
    sys.path.insert(0, str(root))
    loader = importlib.util.spec_from_file_location('serial_existing_queue', root / 'three_arm_queue_20261005.py')
    queue = importlib.util.module_from_spec(loader); loader.loader.exec_module(queue)
    sources = dict(root=str(root), model_feedback=True, files={
        **{str(root / name): digest for name, digest in source_hashes.items()},
        str(root / 'RUN_SPEC.json'): sha(root / 'RUN_SPEC.json')})
    plan = queue.build_plan(tasks, 5, sources, root / 'official_baseline_arm_20261005.py', kit, 50, 21600)
    plan.update(execution_authorized=args.admit_execution, model_generated_rtl_only=True,
        intake_result_sha256=INTAKE_SHA, independent_unseen=0, formal_adoption=False, full156=False,
        arm_definitions=spec['arm_definitions'], factor=spec['factor'],
        structural_binding_controls_result_sha256=args.qualification_result_sha256,
        structural_pure_controls_result_sha256=PURE_SHA,
        data_selection='Every eligible row of the frozen full156 prompt-only intake; no outcome selection',
        selection_policy='Report the unchanged official subset summary and all cost/regression diagnostics. '
                         'This subset does not satisfy or replace the active full156 completion gates.',
        full_goal_complete=False, active_full156_completion_gates_evaluated=False)
    assert len(plan['rows']) == 30 and plan['required_reserved_calls'] == 50
    assert (plan['solve_deadline_s'], plan['solve_supervisor_s'], plan['judge_supervisor_s'],
            plan['row_reservation_s']) == (300, 310, 360, 670)
    queue.validate(plan)
    save(root / 'PLAN.json', plan)
    assert all(sha(root / n) == h for n, h in source_hashes.items())
    assert all(sha(qualified / n) == h for n, h in binding['source_sha256'].items())
    assert sha(qualified / 'RUN_SPEC.json') == QUALIFIED_SPEC_SHA
    assert sha(binding_path) == args.qualification_result_sha256
    save(root / 'PREPARATION_RESULT.json', dict(complete=True, prepared=True, submitted=False,
        model_calls=0, eda_calls=0, fifo_calls=0, tasks=len(tasks), outputs=30, max_calls=50,
        spec_sha256=sha(root / 'RUN_SPEC.json'), plan_sha256=sha(root / 'PLAN.json'),
        sources_held=all(sha(root / n) == h for n, h in source_hashes.items()),
        qualification_sources_held=True, qualification_spec_held=True,
        admission_requires_root_review=True, execution_authorized=args.admit_execution,
        safety_caps=dict(queue_wall_s=21600, proposed_stage_cap_s=21720,
                         proposed_guard_s=21900, proposed_fifo_slot_minutes=370),
        terminal_reader_sha256=READER_SHA, official_score_sha256=SCORE_SHA,
        terminal_reader=str(root / 'comparison_result.py'), official_score=str(args.official_score.resolve())))


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    p = argparse.ArgumentParser()
    for name in ('out', 'qualified-root', 'intake-root', 'peer-root', 'kit', 'reader', 'official-score'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--qualification-result-sha256', required=True,
                   help='SHA256 of passed 11-control results/RESULT.json at qualified-root')
    p.add_argument('--admit-execution', action='store_true', help='Root-reviewed freeze only; still never submits or runs')
    prepare(p.parse_args())
