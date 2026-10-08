"""Prepare the table-parent comparison without granting a scoring budget."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
PARENT_SPEC_SHA = '0b9c1c07ed275eff5ba81d9281c86575db7f89b729d7951491dcafea73df6702'
# Replace only in a reviewed execution freeze backed by the actual authorization.
# A JSON file with approved=true cannot open this preparation by itself.
EXECUTION_AUTHORIZATION_SHA = 'dddba0c0b90a3d98bf0e0b5c1b65819b3af131f9efc3cc5fd1b7aae9f3dd14b4'
LIMITS = dict(max_actual_model_requests=624, max_worker_requests_per_arm=2,
              retries=0, max_tokens=8192, solve_deadline_s=300,
              judge_timeout_s=300, judge_supervisor_timeout_s=360,
              stage_timeout_s=43200, guard_timeout_s=43600, slot_minutes=740)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write('\n')


def route(recipe):
    assert recipe['input_hashes_bound'] is True
    assert all(type(recipe[k]) is int and recipe[k] == 0
               for k in ('actual_model_requests', 'actual_eda_calls', 'external_io_calls'))
    return dict(route='mechanical_' + recipe['selected_provider'] if recipe['emitted'] else 'model',
                prompt_sha256=recipe['prompt_sha256'],
                interface_sha256=recipe['interface_sha256'],
                contract_sha256=recipe['contract_sha256'],
                generated_solution_sha256=recipe['rtl_sha256'],
                recipe_sha256=hashlib.sha256(json.dumps(recipe, sort_keys=True,
                    separators=(',', ':'), ensure_ascii=True).encode()).hexdigest())


def intake(root, kit):
    import composition
    root, kit = Path(root), Path(kit)
    assert not (root/'COMPARISON_INPUT_PLAN.json').exists()
    manifest = read(root/'INPUT_MANIFEST.json')
    tasks = read(root/'upstream/RUN_SPEC.json')['task_ids']
    assert len(tasks) == len(set(tasks)) == 156 and tasks == sorted(tasks)
    rows = {}
    for task in tasks:
        source = kit/'bench/tasks_veval'/task
        raw = {}
        for name in ('prompt.txt', 'interface.txt'):
            key = task + '/' + name
            path = source/name
            assert path.exists() == (key in manifest['input_sha256'])
            if path.exists():
                raw[name] = path.read_bytes()
                assert hashlib.sha256(raw[name]).hexdigest() == manifest['input_sha256'][key]
        prompt = raw['prompt.txt'].decode('utf-8')
        interface = raw.get('interface.txt', b'').decode('utf-8')
        parent = composition.parent(prompt, interface)
        candidate = composition.synthesize(prompt, interface)
        if parent['emitted']:
            assert candidate == parent, 'Vector extension altered an admitted parent recipe'
        pair = dict(C=route(parent), P=route(candidate))
        assert pair['C']['route'] in ('model', 'mechanical_table')
        if pair['C']['route'] == 'mechanical_table':
            assert pair['C'] == pair['P']
        rows[task] = pair
        for name, content in raw.items():
            assert (source/name).read_bytes() == content
    counts = {arm: {name: sum(pair[arm]['route'] == name for pair in rows.values())
                   for name in ('model', 'mechanical_table', 'mechanical_vector')}
              for arm in ('C', 'P')}
    result = dict(schema='table_parent_vector_input_plan_v1', task_count=156,
                  tasks=rows, route_counts=counts,
                  changed_routes=sum(pair['C'] != pair['P'] for pair in rows.values()),
                  model_calls=0, eda_calls=0, not_quality_evidence=True,
                  production_input_scope='Original prompt/interface bytes only; no judge/reference content',
                  data_use='Previously seen development; no independent validation')
    save(root/'COMPARISON_INPUT_PLAN.json', result)
    return result


def task_groups(root, kit=None):
    root = Path(root)
    tasks = read(root/'upstream/RUN_SPEC.json')['task_ids']
    baseline = read(root/'FULL_BASELINE_REFERENCE.json')['levels']
    plan = read(root/'COMPARISON_INPUT_PLAN.json')
    assert len(tasks) == len(set(tasks)) == 156 and tasks == sorted(tasks)
    assert set(tasks) == set(baseline) == set(plan['tasks']) and plan['task_count'] == 156
    guards = [task for task in tasks if baseline[task] == 3]
    assert len(guards) == 113
    if kit is not None:
        manifest = read(root/'INPUT_MANIFEST.json')
        for task in tasks:
            for name in ('prompt.txt', 'interface.txt'):
                path = Path(kit)/'bench/tasks_veval'/task/name
                key = task+'/'+name
                assert path.exists() == (key in manifest['input_sha256'])
                if path.exists():
                    assert sha(path) == manifest['input_sha256'][key]
    return dict(task_ids=tasks, guard_tasks=guards,
                target_tasks=[task for task in tasks if task not in guards],
                abstention_tasks=[task for task in tasks if all(
                    plan['tasks'][task][arm]['route'] == 'model' for arm in ('C', 'P'))],
                expected_samples=312)


def validate_authorization(root, spec):
    root = Path(root)
    assert isinstance(EXECUTION_AUTHORIZATION_SHA, str) and re.fullmatch(
        '[0-9a-f]{64}', EXECUTION_AUTHORIZATION_SHA), 'No reviewed scoring-budget authorization'
    assert spec['execution_authorization_sha256'] == EXECUTION_AUTHORIZATION_SHA
    path = root/'EXECUTION_AUTHORIZATION.json'
    assert sha(path) == EXECUTION_AUTHORIZATION_SHA
    auth = read(path)
    assert auth['schema'] == 'table_parent_vector_execution_authorization_v1'
    assert auth['approved'] is True and auth['run_identity'] == spec['identity']
    assert auth['authorization_source'] and auth['actual_resource_allocation']
    assert auth['input_plan_sha256'] == sha(root/'COMPARISON_INPUT_PLAN.json')
    assert auth['source_factor_proof_sha256'] == sha(root/'SOURCE_FACTOR_PROOF.json')
    assert auth['limits'] == LIMITS
    assert auth['maximum_submissions'] == 1 and auth['resampling'] is False
    assert all(spec[key] == value for key, value in LIMITS.items())
    return auth


def prepare(base_commit, kit):
    import factor_proof
    assert sys.platform == 'linux' and sys.version_info[:2] == (3, 12)
    assert re.fullmatch('[0-9a-f]{40}', base_commit)
    assert not (ROOT/'RUN_SPEC.json').exists()
    assert not (ROOT/'PREPARATION_RECEIPT.json').exists()
    assert sha(ROOT/'PARENT90_RUN_SPEC.json') == PARENT_SPEC_SHA
    proof = factor_proof.verify(ROOT)
    save(ROOT/'SOURCE_FACTOR_PROOF.json', proof)
    plan = intake(ROOT, kit)
    groups = task_groups(ROOT, kit)
    parent = read(ROOT/'PARENT90_RUN_SPEC.json')
    capture = read(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json')
    protected = read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
    import protected_sources
    checked = protected_sources.check(protected)
    assert checked['verified'] and checked['source_assets'] == protected['source_assets']
    # Import only after the input plan exists. No production execution is performed.
    import pilot
    env = pilot.validate_environment()
    assert env['tools'] == capture['compiler_tools']
    assert env['compiler_env'] == capture['compiler_env'] and env['udev_files'] == capture['udev_files']
    manifest = read(ROOT/'INPUT_MANIFEST.json')
    for name, digest in manifest['input_sha256'].items():
        assert sha(kit/'bench/tasks_veval'/name) == digest
    for name, digest in manifest['official_sha256'].items():
        assert sha(kit/'official_reference'/name) == digest
    spec = {key: parent[key] for key in
            ('kit', 'model', 'model_pid', 'python_major_minor', 'dependency_hashes', 'minimum_disk_free_bytes')}
    spec.update(schema='table_parent_vector_full156_frozen_v1',
                identity=ROOT.name, cloud_root=str(ROOT), base_commit=base_commit,
                dependencies_cloud=str(ROOT/'dependencies'), **groups, **LIMITS,
                arms=['C', 'P'], samples_per_arm_per_task=1, first_generation_replayed=False,
                original_phase_baseline_spec_sha256=factor_proof.ORIGINAL_SPEC_SHA,
                parent_spec_sha256=PARENT_SPEC_SHA,
                input_plan_sha256=sha(ROOT/'COMPARISON_INPUT_PLAN.json'),
                source_factor_proof_sha256=sha(ROOT/'SOURCE_FACTOR_PROOF.json'),
                environment_capture_sha256=sha(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json'),
                protected_groups_capture_sha256=sha(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),
                protected_group_count=len(protected['groups']), protected_source_assets=protected['source_assets'],
                execution_authorization_sha256=EXECUTION_AUTHORIZATION_SHA,
                prepared_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                acceptance='Original grade, historical113, paired and cost gates retained. Report shared historical failures separately. Exploration is not adoption.',
                limits=['Seen development156; no independent/official-baseline/five-sample claim.',
                        'Historical90/98 rejection unchanged. No cross-run score addition.',
                        'One prospectively budgeted run; no retries, resampling or deployment.'])
    for key in ('compiler_tools', 'compiler_env', 'udev_files', 'protected', 'model_identity'):
        spec[key] = capture[key]
    for name, digest in spec['dependency_hashes'].items():
        assert sha(ROOT/'dependencies'/name) == digest
    names = read(ROOT/'INSTALL_SOURCE_MANIFEST.json')['files']
    assert all(sha(ROOT/name) == digest for name, digest in names.items())
    spec['source_hashes'] = dict(names)
    for name in ('SOURCE_FACTOR_PROOF.json', 'COMPARISON_INPUT_PLAN.json'):
        spec['source_hashes'][name] = sha(ROOT/name)
    # Produce a concrete, non-executable draft until actual budget admission is bound.
    if EXECUTION_AUTHORIZATION_SHA is None:
        save(ROOT/'PREPARED_SPEC.json', spec)
        executable = False
    else:
        validate_authorization(ROOT, spec)
        spec['source_hashes']['EXECUTION_AUTHORIZATION.json'] = EXECUTION_AUTHORIZATION_SHA
        save(ROOT/'RUN_SPEC.json', spec)
        executable = True
    receipt = dict(schema='table_parent_vector_preparation_v1', base_commit=base_commit,
                   source_assets=len(spec['source_hashes']), input_plan_sha256=spec['input_plan_sha256'],
                   source_factor_proof_sha256=spec['source_factor_proof_sha256'],
                   route_counts=plan['route_counts'], changed_routes=plan['changed_routes'],
                   model_calls=0, eda_calls=0, fifo_submissions=0,
                   executable=executable, new_accuracy_result=False)
    save(ROOT/'PREPARATION_RECEIPT.json', receipt)
    return receipt


def promote(base_commit, kit, prepared_root):
    """Reuse the sealed intake; authorize one new run without regenerating it."""
    assert sys.platform == 'linux' and sys.version_info[:2] == (3, 12)
    assert re.fullmatch('[0-9a-f]{40}', base_commit)
    prepared_root = Path(prepared_root).resolve()
    assert ROOT.resolve() != prepared_root and not (ROOT/'RUN_SPEC.json').exists()
    assert not (ROOT/'EXECUTION_FREEZE_RECEIPT.json').exists()
    assert sha(prepared_root/'PREPARED_SPEC.json') == '2d2a46fb4945351e48126779f3b04271ee11825e5b4b9e4fce065d766b97acb5'
    spec = read(prepared_root/'PREPARED_SPEC.json')
    for name, digest in spec['source_hashes'].items():
        assert sha(prepared_root/name) == digest, name
        if name != 'prepare.py':
            assert sha(ROOT/name) == digest, name
    names = read(ROOT/'INSTALL_SOURCE_MANIFEST.json')['files']
    assert set(names) == set(spec['source_hashes']) | {'EXECUTION_AUTHORIZATION.json'}
    assert all(sha(ROOT/name) == digest for name, digest in names.items())
    spec.update(identity=ROOT.name, cloud_root=str(ROOT), base_commit=base_commit,
                dependencies_cloud=str(ROOT/'dependencies'),
                execution_authorization_sha256=EXECUTION_AUTHORIZATION_SHA,
                prepared_spec_sha256=sha(prepared_root/'PREPARED_SPEC.json'),
                prepared_root=str(prepared_root), source_hashes=names,
                execution_frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    validate_authorization(ROOT, spec)
    assert all(spec[key] == value for key, value in task_groups(ROOT, kit).items())
    import factor_proof
    assert factor_proof.verify(ROOT) == read(ROOT/'SOURCE_FACTOR_PROOF.json')
    import pilot
    env = pilot.validate_environment()
    assert env['tools'] == spec['compiler_tools']
    assert env['compiler_env'] == spec['compiler_env'] and env['udev_files'] == spec['udev_files']
    save(ROOT/'RUN_SPEC.json', spec)
    # Complete frozen entry validation performs no model/EDA or intake execution.
    assert pilot.frozen(kit) == spec
    receipt = dict(schema='table_parent_vector_execution_freeze_v1',
                   spec_sha256=sha(ROOT/'RUN_SPEC.json'), source_assets=len(names),
                   reused_input_plan_sha256=spec['input_plan_sha256'],
                   execution_authorization_sha256=EXECUTION_AUTHORIZATION_SHA,
                   model_calls=0, eda_calls=0, repeated_intake_calls=0,
                   maximum_submissions=1, executable=True)
    save(ROOT/'EXECUTION_FREEZE_RECEIPT.json', receipt)
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--base-commit', required=True)
    p.add_argument('--kit', required=True, type=Path)
    p.add_argument('--promote-prepared', type=Path)
    a = p.parse_args()
    print(json.dumps(promote(a.base_commit, a.kit, a.promote_prepared)
                     if a.promote_prepared else prepare(a.base_commit, a.kit)))
