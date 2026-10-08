"""Once-only, disclosed compatibility closure of the completed FIFO123 evidence.

AMD only. No scoring, model, EDA or FIFO calls. Frozen run files stay unchanged.
The collector uses the actual promotion receipts; the auditor binds inherited
dependency paths to the sealed prepared specification and exact current hashes.
Preparation is permitted during scoring; collection/audit require completed123.
All scoring and decision logic is retained. No frozen run file is modified.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
import zipfile

RUN = Path('/workspace/team/runs/fpga_teammate/table_parent_vector_full156_20261008_v1')
SPEC = '8e80d776b3df21399fb66a4c99698a794a049527e4c5634e57900ed0c4b9e31c'
ROOT = Path('/workspace/team/runs/fpga_teammate/table_parent_vector123_terminal_20261008_v1')
HELPERS = Path('/workspace/team/runs/fpga_owner/framing_cp8_113_terminal_monitor_20261007_v1')
PYTHON = '8295ee25cfdb239f3e165afceda7f46de73e2b606ff0e2e3d8623e3facd30acc'
ONCE = 'COMPATIBLE_TERMINAL123_INTENT.json'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def binding():
    assert sha(RUN/'RUN_SPEC.json') == SPEC
    spec = read(RUN/'RUN_SPEC.json')
    assert len(spec['task_ids']) == len(set(spec['task_ids'])) == 156
    assert spec['expected_samples'] == 312 and spec['max_actual_model_requests'] == 624
    assert len(spec['source_hashes']) == 107
    assert {n: sha(RUN/n) for n in spec['source_hashes']} == spec['source_hashes']
    assert spec['source_hashes']['audit.py'] == '0f7e1244194ea5f8414e8cd3d675b8cec6c07b462daa263ac7bac4ec1bea51f6'
    assert spec['source_hashes']['collect_evidence.py'] == 'd906f10f8ab3a26cf7c577fdebab0ccb0c2314d9793ba5b3c6f7f0a795e8a25a'
    assert sha(RUN/'EXECUTION_FREEZE_RECEIPT.json') == '9fbe55e3cc67b927bd856b1c3ce8cb5734e32275efc80fd71377ae548d606e46'
    assert sha(RUN/'ARCHIVAL_PREPARED_SPEC.json') == spec['prepared_spec_sha256'] == '2d2a46fb4945351e48126779f3b04271ee11825e5b4b9e4fce065d766b97acb5'
    assert sha(RUN/'ARCHIVAL_PREPARATION_RECEIPT.json') == '4a22c7f3ce313ce4ae6ecca66d37605000cd1175e462a0d63908815ff2c5ebfb'
    assert not (RUN/'PREPARATION_RECEIPT.json').exists()
    return spec


def gate():
    spec = binding()
    ticket = read('/workspace/team/task_fifo/tickets/00000123.json')
    report, guard = read(RUN/'results/summary.json'), read(RUN/'guard/status.json')
    assert ticket['ticket'] == 123 and ticket['state'] == 'completed' and ticket['returncode'] == 0
    assert ticket['cwd'] == str(RUN) and ticket['completion_sha256'] == sha(RUN/'results/summary.json')
    assert report['complete'] and report['passed'] and not report.get('error') and report['spec_sha256'] == SPEC
    assert len(report['rows']) == 312 and sum(r['actual_model_requests'] for r in report['rows']) == report['actual_model_requests'] <= 624
    assert all(guard[k] for k in ['complete', 'passed', 'model_unchanged', 'protected_files_unchanged', 'own_slot_released'])
    assert guard['stage_rc'] == 0 and guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
    for identity in guard['owned_cleanup']['recorded'] + [ticket['runner'], ticket['child']]:
        p = Path('/proc')/str(identity['pid'])/'stat'
        if p.exists():
            fields = p.read_text().rsplit(')', 1)[1].split()
            assert fields[19] != identity['starttime'] or fields[0] in ('Z', 'X')
    model = Path('/proc/2013333')
    fields = (model/'stat').read_text().rsplit(')', 1)[1].split()
    assert fields[19] == '823869819' and fields[0] not in ('Z', 'X')
    assert sha(model/'cmdline') == '2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1'
    assert read(RUN/'EXECUTION_FREEZE_RECEIPT.json')['spec_sha256'] == SPEC
    assert not (RUN/'PREPARATION_RECEIPT.json').exists()
    return spec, report


def adapters():
    collector = (RUN/'collect_evidence.py').read_text()
    auditor = (RUN/'audit.py').read_text()
    changes = [("add(root/'PREPARATION_RECEIPT.json','run/PREPARATION_RECEIPT.json')",
                "add(root/'EXECUTION_FREEZE_RECEIPT.json','run/EXECUTION_FREEZE_RECEIPT.json')\n    add(root/'ARCHIVAL_PREPARED_SPEC.json','run/ARCHIVAL_PREPARED_SPEC.json')\n    add(root/'ARCHIVAL_PREPARATION_RECEIPT.json','run/ARCHIVAL_PREPARATION_RECEIPT.json')")]
    for old, new in changes:
        assert collector.count(old) == 1
        collector = collector.replace(old, new)
    old_dependency = "assert capture['dependency_hashes']==spec['dependency_hashes'] and capture['dependencies_cloud']==spec['dependencies_cloud']"
    new_dependency = """assert capture['dependency_hashes']==spec['dependency_hashes']
        prepared=read(run/'ARCHIVAL_PREPARED_SPEC.json')
        assert sha(run/'ARCHIVAL_PREPARED_SPEC.json')==spec['prepared_spec_sha256']=='2d2a46fb4945351e48126779f3b04271ee11825e5b4b9e4fce065d766b97acb5'
        assert capture['dependencies_cloud']==prepared['dependencies_cloud']
        assert prepared['dependency_hashes']==spec['dependency_hashes']
        assert spec['dependencies_cloud']==str(here/'dependencies')
        assert all(sha(here/'dependencies'/n)==h for n,h in spec['dependency_hashes'].items())"""
    edits = [(old_dependency, new_dependency),
             ('here = Path(__file__).resolve().parent', 'here = Path('+repr(str(RUN))+')'),
             ('here=Path(__file__).resolve().parent', 'here=Path('+repr(str(RUN))+')')]
    for old, new in edits:
        assert auditor.count(old) == 1
        auditor = auditor.replace(old, new)
    for generated, original, replacements in [(collector, 'collect_evidence.py', changes), (auditor, 'audit.py', edits)]:
        ast.parse(generated)
        restored = generated
        for old, new in reversed(replacements):
            assert restored.count(new) == 1
            restored = restored.replace(new, old)
        assert restored.encode() == (RUN/original).read_bytes()
    return collector, auditor, dict(collector=changes, auditor=edits)


def prepare():
    spec = binding()
    assert not ROOT.exists() and not (ROOT/ONCE).exists()
    assert shutil.disk_usage(RUN).free >= 2 * 1024**3
    collector, auditor, changes = adapters()
    expected = {'terminal_outer.py': '569b70a5881ae97267e4035a71a3371d753b3487bbf0efd4f09c3d838bc993b1',
                'bounded_owned_exec.py': '1ba65a00e4493290b3693dbbc8e50ab73dda4b17e57da9cad3c111ac67789b00',
                'owned_tree_cleanup.py': '5dd37bb39db4616b3411a51878124987ce51f0a289174b81dad0d81e34b134ad'}
    names = list(expected)
    assert all(read(HELPERS/'SOURCE_MANIFEST.json')[n] == expected[n] for n in names)
    assert all(sha(HELPERS/n) == expected[n] for n in names)
    ROOT.mkdir()
    (ROOT/'collector.py').write_text(collector)
    (ROOT/'auditor.py').write_text(auditor)
    shutil.copyfile(__file__, ROOT/'terminal123.py')
    for n in names:
        shutil.copyfile(HELPERS/n, ROOT/n)
    save(ROOT/'PLAN.json', dict(spec_sha256=SPEC, original_source_hashes=spec['source_hashes'],
         summary_binding='Bound once at completed-task observation, not while scoring is active', preparation_receipt_sha256=sha(RUN/'EXECUTION_FREEZE_RECEIPT.json'),
         disclosed_changes=changes, byte_exact_inverse_verified=True, helper_sources={n: expected[n] for n in names},
         collector_calls=1, auditor_calls=1, per_command_cap_s=180, external_cap_s=450,
         cleanup_reserve_s=20, model_calls=0, eda_calls=0, scoring_calls=0, fifo_calls=0,
         original_collector_called=False, original_auditor_called=False,
         unchanged='Original run/spec/inputs/production/score/decision/312 rows/625 receipts retained.',
         failure='Preserve attempt and stop. Never repeat an attempted collector/auditor to erase a failure.'))
    save(ROOT/'SOURCE_MANIFEST.json', {p.name: sha(p) for p in ROOT.iterdir()})
    print(json.dumps(dict(prepared=True, manifest_sha256=sha(ROOT/'SOURCE_MANIFEST.json'))))


def sealed():
    manifest = read(ROOT/'SOURCE_MANIFEST.json')
    assert {n: sha(ROOT/n) for n in manifest} == manifest
    spec = binding()
    plan = read(ROOT/'PLAN.json')
    assert plan['original_source_hashes'] == spec['source_hashes']
    assert plan['preparation_receipt_sha256'] == sha(RUN/'EXECUTION_FREEZE_RECEIPT.json')
    collector, auditor, _ = adapters()
    assert (ROOT/'collector.py').read_bytes() == collector.encode()
    assert (ROOT/'auditor.py').read_bytes() == auditor.encode()
    return spec


def child():
    import bounded_owned_exec
    result = dict(complete=False, passed=False, error=None, processes={}, model_calls=0, eda_calls=0,
                  original_collector_called=False, original_auditor_called=False, modified_entrypoints_disclosed=True)
    try:
        spec = sealed()
        gate()
        archive = ROOT/'EVIDENCE.zip'
        actions = [('collector', ['--root', str(RUN), '--guard', str(RUN/'guard'), '--archive', str(archive)]),
                   ('auditor', ['--archive', str(archive), '--out', str(ROOT/'audit_result'), '--spec-sha', SPEC])]
        assert read(ROOT/'OBSERVER_INTENT.json')['summary_sha256'] == sha(RUN/'results/summary.json')
        save(ROOT/ONCE, dict(root=str(ROOT), spec_sha256=SPEC, manifest_sha256=sha(ROOT/'SOURCE_MANIFEST.json'),
                           actions=actions, no_retry=True, modified_entrypoints=True))
        (ROOT/'processes').mkdir()
        for name, args in actions:
            sealed()
            process = bounded_owned_exec.run([sys.executable, '-B', str(ROOT/(name+'.py'))]+args,
                                            ROOT, ROOT/'processes'/name, 180)
            result['processes'][name] = process
            assert process['normal_completion'] and process['returncode'] == 0, name
        audited = read(ROOT/'audit_result/RESULTS.json')
        assert audited['evidence_valid'] and audited['full156_evidence_valid'] and audited['full_score_measured']
        assert audited['auditor_sha256'] == sha(ROOT/'auditor.py') and audited['spec_sha256'] == SPEC
        with zipfile.ZipFile(archive) as zipped:
            manifest = json.loads(zipped.read('ARCHIVE_MANIFEST.json'))
            assert len(zipped.namelist()) == len(set(zipped.namelist())) == len(manifest['files'])+1
            assert set(zipped.namelist()) == set(manifest['files'])|{'ARCHIVE_MANIFEST.json'}
            assert manifest['collector_sha256'] == sha(ROOT/'collector.py')
            bases = dict(run=RUN, guard=RUN/'guard', dependencies=Path(spec['dependencies_cloud']), kit=Path(spec['kit']))
            for n, expected in manifest['files'].items():
                prefix, relative = n.split('/', 1)
                assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
                assert hashlib.sha256(zipped.read(n)).hexdigest() == expected == sha(bases[prefix]/relative)
        gate()
        sealed()
        assert read(ROOT/'OBSERVER_INTENT.json')['summary_sha256'] == sha(RUN/'results/summary.json')
        result.update(passed=True, archive_sha256=sha(archive), archive_members=len(manifest['files'])+1,
                      every_member_matches_original=True, audit_sha256=sha(ROOT/'audit_result/RESULTS.json'),
                      qualified_for_goal=audited['qualified_for_goal'], adoption=False,
                      actual_model_requests=audited['actual_model_requests'], original_spec_sha256=SPEC)
    except BaseException as exc:
        result['error'] = type(exc).__name__+': '+str(exc)
        (ROOT/'FAILURE_TRACEBACK.txt').write_text(traceback.format_exc())
    finally:
        result['complete'] = True
        save(ROOT/'TERMINAL_RECEIPT.json', result)
    print(json.dumps({k: result.get(k) for k in ['passed', 'error', 'archive_members', 'actual_model_requests']}))
    return 0 if result['passed'] else 1


def observe(manifest_sha):
    assert Path(__file__).resolve() == ROOT/'terminal123.py'
    assert sha(ROOT/'SOURCE_MANIFEST.json') == manifest_sha
    sealed()
    gate()
    assert not (ROOT/ONCE).exists() and not (ROOT/'OBSERVER_INTENT.json').exists()
    save(ROOT/'OBSERVER_INTENT.json', dict(manifest_sha256=manifest_sha, pid=os.getpid(), summary_sha256=sha(RUN/'results/summary.json'), no_retry=True))
    import terminal_outer
    receipt = terminal_outer.run([sys.executable, '-B', str(ROOT/'terminal123.py'), 'child'], ROOT,
        ROOT/'external', 450, 20, [ROOT/'TERMINAL_RECEIPT.json', ROOT/'EVIDENCE.zip', ROOT/'audit_result/RESULTS.json'], 2013333)
    print(json.dumps(dict(passed=receipt['passed'], error=receipt['error'], elapsed_s=receipt['measured_complete_elapsed_s'])))
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode and sha(sys.executable) == PYTHON
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'observe', 'child'])
    parser.add_argument('--manifest-sha')
    args = parser.parse_args()
    if args.mode == 'prepare':
        prepare()
    else:
        sys.exit(observe(args.manifest_sha) if args.mode == 'observe' else child())
