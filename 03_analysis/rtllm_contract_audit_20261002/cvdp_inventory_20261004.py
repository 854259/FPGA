"""AMD-only full-source static admission inventory; never execute harness code."""
import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import zipfile


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode()


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
    records, duplicates = [], defaultdict(list)
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
                        if isinstance(node.value.value, ast.Name) and node.value.value.id == 'dut':
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
    private = dict(schema='cvdp_static_admission_inventory_v1', rows=records,
                   duplicate_test_file_groups=[v for v in duplicates.values() if len(v) > 1])
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
