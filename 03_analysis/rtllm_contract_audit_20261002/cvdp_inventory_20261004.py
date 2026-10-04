"""AMD-only full-source static admission inventory; never execute harness code."""
import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
import time
import zipfile


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode()


def entrypoint_map(row):
    files = row['harness']['files']
    env, problems = {}, []
    for path, content in files.items():
        if path.endswith('.env'):
            for line in content.splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    key, value = key.strip(), value.strip()
                    if key in env and env[key] != value:
                        problems.append('conflicting_env_' + key)
                    env[key] = value
    runners = {p:c for p,c in files.items() if Path(p).name == 'test_runner.py'}
    runner_trees = [ast.parse(c) for c in runners.values()]
    assignments = defaultdict(list)
    for tree in runner_trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id].append(node.value)

    def resolve(node, seen=()):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.Name) and node.id not in seen:
            values = [resolve(v, seen + (node.id,)) for v in assignments[node.id]]
            if values and all(v is not None for v in values):
                return set().union(*values)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'os'
                and node.func.attr == 'getenv' and node.args
                and isinstance(node.args[0], ast.Constant)):
            key = node.args[0].value
            if key in env:
                return {env[key]}
            if len(node.args) == 2:
                return resolve(node.args[1], seen)
        return None

    test_calls, build_calls = [], []
    for tree in runner_trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                kwargs = {k.arg:k.value for k in node.keywords}
                if node.func.attr == 'test' and 'test_module' in kwargs:
                    test_calls.append({k:sorted(v) if (v := resolve(kwargs[k])) is not None else None
                                       for k in ['test_module', 'hdl_toplevel'] if k in kwargs})
                if node.func.attr == 'build' and 'hdl_toplevel' in kwargs:
                    values = resolve(kwargs['hdl_toplevel'])
                    build_calls.append(sorted(values) if values is not None else None)
    if not test_calls:
        problems.append('no_static_runner_test_call')
    if any(c.get('test_module') is None or c.get('hdl_toplevel') is None for c in test_calls):
        problems.append('unresolved_runner_test_arguments')
    modules = sorted({m for c in test_calls for m in (c.get('test_module') or [])})
    tops = sorted({t for c in test_calls for t in (c.get('hdl_toplevel') or [])})
    if len(tops) != 1 or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', tops[0]):
        problems.append('top_not_unique_simple_identifier')
    if not build_calls or any(v != tops for v in build_calls):
        problems.append('build_test_top_not_statically_matched')
    mapped, decorated = {}, 0
    for item in modules:
        for module in item.split(','):
            module = module.strip()
            if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', module):
                problems.append('test_module_not_import_identifier')
                continue
            suffix = module.replace('.', '/') + '.py'
            matches = [p for p in files if p == suffix or p.endswith('/' + suffix)]
            if len(matches) != 1:
                problems.append('test_module_not_unique_file')
                continue
            path = matches[0]
            mapped[path] = files[path]
            tree = ast.parse(files[path])
            for function in ast.walk(tree):
                if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in function.decorator_list:
                        target = decorator.func if isinstance(decorator, ast.Call) else decorator
                        if (isinstance(target, ast.Attribute) and target.attr == 'test'
                                and isinstance(target.value, ast.Name) and target.value.id == 'cocotb'):
                            decorated += 1
    if not mapped:
        problems.append('no_declared_test_file_resolved')
    source_paths = []
    if 'VERILOG_SOURCES' in env:
        try:
            source_paths = shlex.split(env['VERILOG_SOURCES'])
        except ValueError:
            problems.append('source_env_not_literal_shell_words')
    known = set(row['input']['context']) | set(row['output']['context']) | set(files)
    missing = [p for p in source_paths if p.removeprefix('/code/') not in known]
    if missing:
        problems.append('declared_source_not_in_materials')
    if not source_paths:
        problems.append('source_list_requires_runner_review')
    top = tops[0] if len(tops) == 1 else None
    prompt = row['input']['prompt']
    return dict(entrypoint_problems=sorted(set(problems)), runner_test_calls=test_calls,
        declared_test_files=sorted(mapped), declared_test_files_sha256=digest(encoded(mapped)) if mapped else None,
        direct_cocotb_test_decorators=decorated, declared_verilog_sources=source_paths,
        unresolved_verilog_sources=missing, resolved_top=top,
        top_requires_official_name_conversion=top is not None and top != 'TopModule',
        top_exact_token_present_in_prompt=bool(top and re.search(r'(?<![A-Za-z0-9_$])'+re.escape(top)+r'(?![A-Za-z0-9_$])', prompt)),
        static_entrypoint_resolved=not problems,
        entrypoint_limit='Static dataflow only; does not execute runner, prove import resolution, or certify behavior')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--materials', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resource-check', type=Path, required=True)
    args = parser.parse_args()
    assert sys.platform == 'linux'
    check = json.loads(args.resource_check.read_text())
    assert check['resource_idle'] is True
    assert digest(Path(check['slot_lock_path']).read_bytes()) == check['slot_lock_sha256']
    tick = time.monotonic()
    raw = (args.materials / 'cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl').read_bytes()
    assert digest(raw) == 'cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert len(rows) == len({r['id'] for r in rows}) == 302
    toolzip = args.materials / 'cvdp_tooling_8e894cf.zip'
    assert digest(toolzip.read_bytes()) == '632b2602206db3eda090bc2c4390d83b2cb09f1dc214bae98a9f37871a463590'
    with zipfile.ZipFile(toolzip) as z:
        suffix = '/example_dataset/cvdp_v1.1.0_example_nonagentic_code_generation_no_commercial_with_solutions.jsonl'
        names = [n for n in z.namelist() if n.endswith(suffix)]
        assert len(names) == 1
        examples = [json.loads(line) for line in z.read(names[0]).splitlines() if line.strip()]
    assert len(examples) == 1
    example = examples[0]
    records, duplicates, declared_duplicates = [], defaultdict(list), defaultdict(list)
    for row in rows:
        family = re.sub(r'_\d{4}$', '', row['id'].removeprefix('cvdp_copilot_'))
        files = row['harness']['files']
        env = {}
        for name, content in files.items():
            if name.endswith('.env'):
                for line in content.splitlines():
                    if '=' in line and not line.lstrip().startswith('#'):
                        k, v = line.split('=', 1)
                        env[k.strip()] = v.strip()
        python = []
        for name, content in files.items():
            if not name.endswith('.py'):
                continue
            item = dict(path=name, sha256=digest(content.encode()), syntax_valid=False)
            try:
                tree = ast.parse(content, filename=name)
                imports = set()
                handles = []
                tests = 0
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(a.name.split('.')[0] for a in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.add(node.module.split('.')[0])
                    elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
                        # Flag aliases to a DUT handle only; this does not prove a failing assertion.
                        if (isinstance(node.value.value, ast.Name) and node.value.value.id == 'dut'
                                and node.value.attr != '_log'):
                            handles.append(node.lineno)
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        tests += node.name.startswith('test_')
                item.update(syntax_valid=True, imports=sorted(imports),
                            assertions=sum(isinstance(n, ast.Assert) for n in ast.walk(tree)),
                            test_named_functions=tests, possible_handle_alias_lines=handles)
            except SyntaxError as exc:
                item.update(error_type='SyntaxError', error_line=exc.lineno)
            python.append(item)
        test_files = {n:c for n,c in files.items()
                      if Path(n).name.startswith('test_') and Path(n).name != 'test_runner.py'}
        test_hash = digest(encoded(test_files))
        if test_files:
            duplicates[test_hash].append(row['id'])
        norm_family = re.sub('[^a-z0-9]', '', family.lower())
        collision = norm_family in {'barrelshifter', 'lfsr', 'radix2div'}
        same_id = row['id'] == example['id']
        records.append(dict(id=row['id'], named_family=family,
            categories=row['categories'], input_sha256=digest(encoded(row['input'])),
            harness_sha256=digest(encoded(files)), test_files_sha256=test_hash,
            file_hashes={n:digest(c.encode()) for n,c in files.items()},
            input_files=sorted(row['input']['context']), output_files=sorted(row['output']['context']),
            sim=env.get('SIM'), top=env.get('TOPLEVEL'), module=env.get('MODULE'),
            reference_available=any(c.strip() for c in row['output']['context'].values()),
            no_input_single_output=not row['input']['context'] and len(row['output']['context']) == 1,
            rtllm_name_collision=collision, source_example_same_id=same_id,
            example_prompt_equal=row['input']['prompt'] == example['input']['prompt'] if same_id else None,
            example_harness_equal=files == example['harness']['files'] if same_id else None,
            example_family_development=norm_family == 'lfsr', python=python,
            admitted=False, solver_candidate_unchanged=True))
        records[-1].update(entrypoint_map(row))
        if records[-1]['declared_test_files_sha256']:
            declared_duplicates[records[-1]['declared_test_files_sha256']].append(row['id'])
    private = dict(schema='cvdp_static_admission_inventory_v2', rows=records,
                   duplicate_test_file_groups=[v for v in duplicates.values() if len(v) > 1],
                   declared_test_file_duplicate_groups=[v for v in declared_duplicates.values() if len(v) > 1])
    public = dict(schema=private['schema'], complete=True, records=len(records),
        source_commit=(Path(__file__).resolve().parents[2] / 'DELIVERY_COMMIT').read_text().strip(),
        source_sha256=digest(raw), named_families=len({r['named_family'] for r in records}),
        model_calls=0, eda_calls=0, harnesses_executed=0, independent_tasks_admitted=0,
        full_experiment_complete=False,
        no_input_single_output=sum(r['no_input_single_output'] for r in records),
        no_reference_records=sum(not r['reference_available'] for r in records),
        python_files=sum(len(r['python']) for r in records),
        syntax_error_records=sum(any(not p['syntax_valid'] for p in r['python']) for r in records),
        possible_handle_alias_records=sum(any(p.get('possible_handle_alias_lines') for p in r['python']) for r in records),
        duplicate_test_file_groups=len(private['duplicate_test_file_groups']),
        records_in_duplicate_test_file_groups=sum(len(g) for g in private['duplicate_test_file_groups']),
        rtllm_name_collision_records=sum(r['rtllm_name_collision'] for r in records),
        example_family_development_records=sum(r['example_family_development'] for r in records),
        example_same_id_records=[{k:r[k] for k in ('id','example_prompt_equal','example_harness_equal')} for r in records if r['source_example_same_id']],
        declared_test_file_mapped_records=sum(bool(r['declared_test_files']) for r in records),
        static_entrypoint_resolved_records=sum(r['static_entrypoint_resolved'] for r in records),
        entrypoint_problem_counts=dict(sorted(Counter(p for r in records for p in r['entrypoint_problems']).items())),
        records_without_direct_cocotb_decorators=sum(not r['direct_cocotb_test_decorators'] for r in records),
        declared_test_file_duplicate_groups=len(private['declared_test_file_duplicate_groups']),
        declared_test_file_duplicate_records=sum(len(g) for g in private['declared_test_file_duplicate_groups']),
        official_top_name_conversion_records=sum(r['top_requires_official_name_conversion'] for r in records),
        resolved_top_absent_from_prompt_records=sum(r['resolved_top'] is not None and not r['top_exact_token_present_in_prompt'] for r in records),
        simple_interface_static_resolved_records=sum(r['no_input_single_output'] and r['static_entrypoint_resolved'] for r in records),
        imports=dict(sorted(Counter(i for r in records for p in r['python'] for i in p.get('imports',[])).items())),
        private_inventory_sha256=digest(encoded(private)),
        limitations=['Syntax validity and handle aliases do not prove functional validity or invalidity',
                    'Name collisions and equal test files do not establish semantic independence',
                    'No task admitted without contract/control and exposure review',
                    'Candidate frozen; audit information is evaluator-only'],
        elapsed_s=time.monotonic()-tick)
    args.out.mkdir(parents=True, exist_ok=False)
    assert digest(Path(check['slot_lock_path']).read_bytes()) == check['slot_lock_sha256']
    (args.out/'PRIVATE_INVENTORY.json').write_bytes(encoded(private))
    (args.out/'PUBLIC_RESULT.json').write_text(json.dumps(public,indent=2)+'\n')
    print(json.dumps(public))


if __name__ == '__main__':
    main()
