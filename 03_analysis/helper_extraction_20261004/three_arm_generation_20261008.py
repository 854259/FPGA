"""Pinned table90/vector123 source copies and prompt-only generation binding.

The queue caller still owns experiment admission. Source preparation neither
admits a candidate nor authorizes a new evaluation. B never uses this module.
"""
import argparse
import ast
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


ORIGINAL = {
    'A': ('/workspace/team/runs/fpga_owner/prompt_table_full156_20261006_v1',
          '0b9c1c07ed275eff5ba81d9281c86575db7f89b729d7951491dcafea73df6702'),
    'P': ('/workspace/team/runs/fpga_teammate/table_parent_vector_full156_20261008_v1',
          '8e80d776b3df21399fb66a4c99698a794a049527e4c5634e57900ed0c4b9e31c'),
}
CHANGES = {
    'worker.py': [
        ('import argparse\n', 'import argparse\nimport os\n'),
        ("source = args.kit / 'bench/tasks_veval' / args.task",
         "source = Path(os.environ['PAIRED_TASK_DIR']).resolve()"),
    ],
    'baseline_worker.py': [
        ("source = args.kit/'bench/tasks_veval'/args.task",
         "source = Path(os.environ['PAIRED_TASK_DIR']).resolve()"),
        ("ledger=Path('/workspace/team/activity/fpga_owner')", "ledger=ROOT/'activity'"),
        ("event_id='functional-fresh:'+spec['identity']+':'+args.task+':'+args.arm+':'+str(index)",
         "event_id='paired-fresh:'+spec['identity']+':'+str(out.resolve())+':'+str(index)"),
    ],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    definition = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def routed(name, data):
    for before, after in CHANGES.get(name, []):
        before, after = before.encode(), after.encode()
        assert data.count(before) == 1, (name, before)
        data = data.replace(before, after)
    return data


def source_spec(selected_arm, root):
    original, digest = ORIGINAL[selected_arm]
    original, root = Path(original), Path(root).resolve()
    assert root != original and not root.is_relative_to(original)
    assert sha(original/'RUN_SPEC.json') == digest
    spec = json.loads((original/'RUN_SPEC.json').read_bytes())
    for name, expected in spec['source_hashes'].items():
        assert sha(original/name) == expected, name
        spec['source_hashes'][name] = hashlib.sha256(routed(name, (original/name).read_bytes())).hexdigest()
    spec.update(identity=root.name, cloud_root=str(root), paired_route_only=True,
                three_arm_label=selected_arm, internal_worker_arm='P', parent_spec_sha256=digest)
    return spec


def prepare(root, selected_arm):
    root = Path(root).resolve()
    assert not root.exists()
    spec = source_spec(selected_arm, root)
    original = Path(ORIGINAL[selected_arm][0])
    root.mkdir(parents=True)
    for name in spec['source_hashes']:
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(routed(name, (original/name).read_bytes()))
    (root/'RUN_SPEC.json').write_text(json.dumps(spec, sort_keys=True, indent=2)+'\n')
    validate(root, selected_arm)
    return dict(root=str(root), outer_arm=selected_arm, worker_arm='P',
                original_spec_sha256=ORIGINAL[selected_arm][1],
                spec_sha256=sha(root/'RUN_SPEC.json'),
                files={str(root/name): digest for name, digest in spec['source_hashes'].items()} |
                      {str(root/'RUN_SPEC.json'): sha(root/'RUN_SPEC.json')} |
                      {str(Path(spec['dependencies_cloud'])/name): digest
                       for name, digest in spec['dependency_hashes'].items()})


def validate(root, selected_arm):
    root = Path(root).resolve()
    expected = source_spec(selected_arm, root)
    assert json.loads((root/'RUN_SPEC.json').read_bytes()) == expected
    for name, digest in expected['source_hashes'].items():
        assert sha(root/name) == digest, name
    for name, digest in expected['dependency_hashes'].items():
        assert sha(Path(expected['dependencies_cloud'])/name) == digest, name
    return expected


def bind(root, solve, task, selected_arm):
    """Run in a fresh process: the two original producers share module names."""
    root, solve, task = map(lambda p: Path(p).resolve(), (root, solve, task))
    spec = validate(root, selected_arm)
    sys.path.insert(0, str(root))
    synthesis = load('paired_generation_producer', root/('synthesis.py' if selected_arm == 'A' else 'composition.py'))
    # Reuse exactly the original check body; do not import an old stage runner.
    tree = ast.parse((root/'pilot.py').read_bytes())
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'generation_binding']
    assert len(body) == 1
    namespace = dict(ROOT=root, sha=sha, hashlib=hashlib, json=json, synthesis=synthesis)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(root/'pilot.py'), 'exec'), namespace)
    journal = json.loads((solve/'requests.json').read_bytes())
    inputs = {n: sha(task/n) for n in ('prompt.txt', 'interface.txt') if (task/n).is_file()}
    assert 'prompt.txt' in inputs
    assert {p.name: sha(p) for p in (solve/'prompt_only').iterdir()} == inputs
    result = namespace['generation_binding'](solve, task, 'P', journal, spec)
    validate(root, selected_arm)
    return result | dict(outer_arm=selected_arm, worker_arm='P', source_root=str(root),
                         source_spec_sha256=sha(root/'RUN_SPEC.json'),
                         original_spec_sha256=ORIGINAL[selected_arm][1], input_sha256=inputs)


def worker(args):
    spec = validate(args.source_root, args.arm)
    assert not args.out.exists()
    assert sys.platform == 'linux' and ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    sys.path.insert(0, str(args.source_root))
    implementation = load('paired_pinned_worker', args.source_root/'worker.py')
    assert implementation.frozen() == spec
    paired = load('paired_owned', Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    os.environ['PAIRED_TASK_DIR'] = str(args.task.resolve())
    args.task, args.arm = args.task.name, 'P'
    implementation.run_worker(args, paired)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['bind', 'worker'])
    parser.add_argument('--arm', choices=['A', 'P'], required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--task', type=Path, required=True)
    for name in ['solve', 'out', 'kit', 'resource-check']:
        parser.add_argument('--'+name, type=Path)
    args = parser.parse_args()
    if args.phase == 'bind':
        print(json.dumps(bind(args.source_root, args.solve, args.task, args.arm), sort_keys=True))
    else:
        worker(args)
