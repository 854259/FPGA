"""Separate, source-bound terminal auditor for the unchanged waveform104 run.

The frozen auditor remains untouched. Only its dependency-capture path assertion
is replaced by a parent-copy proof; execution attribution is updated explicitly.
No model, judge, score, acceptance or replay behavior is changed.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

SPEC_SHA = '216637107d75156c6ad4c1db13656e6ea94f7fce225a8df9da03b7b2f6db25cb'
ORIGINAL_AUDITOR_SHA = 'a1cb51aca23bde8aa3f09879b58711f257b72e010acc681c4503009356883715'
OLD_CHECK = "assert capture['dependency_hashes']==spec['dependency_hashes'] and capture['dependencies_cloud']==spec['dependencies_cloud']"
NEW_CHECK = "relocation_proof = verify_dependency_relocation(run, spec, capture, root/'dependencies')"
OLD_IDENTITY = 'auditor_sha256=sha(Path(__file__)),'
NEW_IDENTITY = "auditor_sha256=AUDIT_EXECUTION['wrapper_sha256'],audit_execution=AUDIT_EXECUTION,dependency_relocation=relocation_proof,"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def read(path):
    return json.loads(Path(path).read_bytes())


def verify_dependency_relocation(run, spec, capture, archived_dependencies):
    """Prove preserved parent capture plus exact child copies; no live old-path reads."""
    run, archived_dependencies = Path(run), Path(archived_dependencies)
    parent_path = run/'PARENT_RUN_SPEC.json'
    assert sha(parent_path) == spec['parent_spec_sha256'] == spec['source_hashes']['PARENT_RUN_SPEC.json']
    parent = read(parent_path)
    capture_path = run/'raw_evidence/ENVIRONMENT_CAPTURE.json'
    assert read(capture_path) == capture
    assert sha(capture_path) == spec['environment_capture_sha256'] == parent['environment_capture_sha256']
    assert sha(capture_path) == spec['source_hashes']['raw_evidence/ENVIRONMENT_CAPTURE.json'] == parent['source_hashes']['raw_evidence/ENVIRONMENT_CAPTURE.json']
    for obj in (spec, parent):
        cloud = PurePosixPath(obj['cloud_root'])
        assert cloud.is_absolute() and '..' not in cloud.parts
        assert obj['dependencies_cloud'] == str(cloud/'dependencies')
    assert parent['cloud_root'] != spec['cloud_root']
    assert capture['dependencies_cloud'] == parent['dependencies_cloud']
    hashes = spec['dependency_hashes']
    assert hashes == parent['dependency_hashes'] == capture['dependency_hashes']
    assert set(hashes) == {'paired_checkpoint.py', 'probe_runner.py'}
    for name, expected in hashes.items():
        key = 'dependencies/'+name
        assert spec['source_hashes'][key] == parent['source_hashes'][key] == expected
        for path in (run/key, archived_dependencies/name):
            assert path.is_file() and not path.is_symlink() and sha(path) == expected
    for key in ('compiler_tools', 'compiler_env', 'udev_files', 'model_identity', 'protected'):
        assert capture[key] == parent[key] == spec[key], key
    admission_path = run/'RESOURCE_LIFECYCLE_ADMISSION.json'
    assert sha(admission_path) == spec['source_hashes']['RESOURCE_LIFECYCLE_ADMISSION.json'] == spec['resource_lifecycle_admission_sha256']
    admission = read(admission_path)
    assert admission['parent_spec_sha256'] == sha(parent_path)
    assert admission['source_commit'] == spec['resource_fix_source_commit']
    assert admission['parent_was_unstarted'] and admission['stage_and_checker_unchanged']
    assert admission['model_calls'] == admission['eda_calls'] == 0
    assert admission['worker_sha256'] == sha(run/'worker.py') == spec['source_hashes']['worker.py']
    # These statements are inspected inside sources already bound to the frozen run.
    expected_statements = {
        'worker.py': [
            "spec = json.loads((ROOT / 'RUN_SPEC.json').read_bytes())",
            "paired = baseline_worker.load('waveform_original_resource', Path(spec['dependencies_cloud']) / 'paired_checkpoint.py')",
            "paired.INHERITED_ORACLE = Path(spec['dependencies_cloud']) / 'probe_runner.py'",
        ],
        'pilot.py': [
            'spec = frozen(args.kit)',
            "paired = load('table_original_owned', Path(spec['dependencies_cloud'])/'paired_checkpoint.py')",
            "paired.INHERITED_ORACLE = Path(spec['dependencies_cloud'])/'probe_runner.py'",
        ],
        'refreeze_resource.py': [
            "shutil.copyfile(parent/n, target)",
            "shutil.copyfile(parent/'RUN_SPEC.json', out/'PARENT_RUN_SPEC.json')",
        ],
    }
    for name, statements in expected_statements.items():
        assert sha(run/name) == spec['source_hashes'][name]
        nodes = {ast.dump(node) for node in ast.walk(ast.parse((run/name).read_bytes()))}
        for statement in statements:
            assert ast.dump(ast.parse(statement).body[0]) in nodes, (name, statement)
    assert spec['source_hashes']['pilot.py'] == parent['source_hashes']['pilot.py']
    return dict(parent_spec_sha256=sha(parent_path), capture_sha256=sha(capture_path),
                dependency_count=len(hashes), parent_capture_preserved=True,
                copies_and_import_source_bound=True, original_path_equality=False,
                historical_execution_proved_by_this_check_alone=False)


def build_auditor(source):
    source = Path(source).resolve()
    assert sha(source/'RUN_SPEC.json') == SPEC_SHA
    spec = read(source/'RUN_SPEC.json')
    for name, expected in spec['source_hashes'].items():
        assert sha(source/name) == expected, name
    raw = (source/'audit.py').read_bytes()
    assert digest(raw) == ORIGINAL_AUDITOR_SHA
    code = raw.decode('utf-8')
    assert code.count(OLD_CHECK) == code.count(OLD_IDENTITY) == 1
    patched = code.replace(OLD_CHECK, NEW_CHECK).replace(OLD_IDENTITY, NEW_IDENTITY)
    identity = dict(wrapper_sha256=sha(__file__), original_auditor_sha256=digest(raw),
                    effective_source_sha256=digest(patched.encode('utf-8')),
                    substitution='one dependency path predicate and explicit execution attribution',
                    frozen_source_modified=False)
    namespace = dict(__name__='separate_waveform104_auditor', __file__=str(source/'audit.py'),
                     verify_dependency_relocation=verify_dependency_relocation, AUDIT_EXECUTION=identity)
    # __file__ locates/verifies the original frozen helpers; identity above records
    # the effective executed source and this wrapper rather than claiming it is original.
    exec(compile(patched, '<source-bound-waveform104-audit>', 'exec'), namespace)
    return namespace, identity


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    assert sys.platform == 'linux' and sys.version_info[:2] == (3, 12) and sys.dont_write_bytecode
    assert args.preflight != (args.archive is not None)
    assert not args.out.exists() and not args.out.resolve().is_relative_to(args.source.resolve())
    namespace, identity = build_auditor(args.source)
    if args.preflight:
        spec = read(args.source/'RUN_SPEC.json')
        proof = verify_dependency_relocation(args.source, spec, read(args.source/'raw_evidence/ENVIRONMENT_CAPTURE.json'), args.source/'dependencies')
        result = dict(schema='waveform104_relocation_preflight_v1', execution=identity, proof=proof,
                      terminal_audit_executed=False, model_calls=0, eda_calls=0)
        args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    else:
        result = namespace['audit'](args.archive, args.out, SPEC_SHA)
    print(json.dumps({'preflight':args.preflight, 'terminal_audit_executed':not args.preflight,
                      'auditor_sha256':identity['wrapper_sha256']}))
