"""AMD-only serial postflight: pinned original provenance audit, then statistics."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def stability_postflight(root, plan, args, resource, paired):
    """One terminal-only stage: both checks, original audit if absent, statistics."""
    assert plan['model_calls'] == plan['eda_calls'] == 0
    assert plan['stage_cap_s'] == 360 and not plan['runtime_and_gates_changed']
    pins = {
        'analysis.py': '44586ba92e7a842107d5a1bc0c3467b2944b3dd475c7418c6bcea7a230a2591b',
        'inputs/RUN_SPEC.json': '589ee0f566d708924370ad5b051ff23fce41df4891853e3ce8abf153104a4f15',
        'owner_audit/stability_audit.py': '4004a32ef28d5b32513ebc5cd762fa959ead197a7005176c36602da0dd92f612',
        'owner_audit/stability_metrics.py': '06c23bda97bfa868133ea56dc738095aee931a9d1a25dd731b38989198a0830c',
        'owner_audit/stability_protected.py': '1deebc61c919f483ef592287a7cf7d3702699b97777ddcc025c27898e532f446',
        'owner_audit/replay.py': 'fc5f1d2bb1f81825a4b31bee3dc4a84d7182361c24eb4644a0835420cc308ac6',
        'full156_postflight_20261004/audit.py': '6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3',
    }
    assert all(plan['files'][name] == digest for name, digest in pins.items())
    assert plan['spec_sha256'] == pins['inputs/RUN_SPEC.json']
    assert plan['files']['run.py'] == sha(Path(__file__))
    assert all(name in plan['files'] for name in ['INPUT.zip', 'inputs/summary.json', 'inputs/guard.json'])
    summary = json.loads((root/'inputs/summary.json').read_text())
    guard = json.loads((root/'inputs/guard.json').read_text())
    assert summary['complete'] and summary['passed'] and len(summary['rows']) == 780
    assert summary['spec_sha256'] == plan['spec_sha256']
    assert all(guard[k] for k in ['complete', 'passed', 'model_unchanged',
                                  'protected_files_unchanged', 'own_slot_released'])
    assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
    out = root/'results'
    out.mkdir(exist_ok=False)
    common = ['--resource-check', str(args.resource_check), '--paired', str(paired), '--kit', plan['kit']]
    base = [sys.executable, '-B', str(root/'analysis.py')]
    commands = [
        ('legacy_selfcheck', 30, base+['--self-check', '--out', str(out/'LEGACY_CHECK.json')]+common),
        ('stability_selfcheck', 30, base+['--stability-self-check', '--out', str(out/'STABILITY_CHECK.json')]+common),
    ]
    reuse = plan['reuse_original_audit']
    assert type(reuse) is bool
    if reuse:
        assert 'inputs/AUDIT.json' in plan['files']
        audit_path = root/'inputs/AUDIT.json'
        audit = json.loads(audit_path.read_text())
        assert audit['auditor_sha256'] == pins['owner_audit/stability_audit.py']
        assert audit['archive_sha256'] == plan['files']['INPUT.zip']
        assert audit['spec_sha256'] == plan['spec_sha256'] and audit['stability780_evidence_valid']
    else:
        audit_path = out/'audit/RESULTS.json'
        commands.append(('original_audit', 180, [sys.executable, '-B', str(root/'owner_audit/stability_audit.py'),
            '--archive', str(root/'INPUT.zip'), '--out', str(out/'audit'), '--spec-sha', plan['spec_sha256']]))
    commands.append(('statistics', 60, base+['--stability', '--archive', str(root/'INPUT.zip'),
        '--spec', str(root/'inputs/RUN_SPEC.json'), '--summary', str(root/'inputs/summary.json'),
        '--guard', str(root/'inputs/guard.json'), '--audit', str(audit_path),
        '--out', str(out/'STATISTICS.json')]+common))
    started = time.monotonic()
    for label, budget, command in commands:
        resource.check_resource(args.resource_check, Path(plan['kit']))
        assert time.monotonic()-started+budget <= 360, 'Whole stage budget exhausted'
        tick = time.monotonic()
        with (out/(label+'.log')).open('xb') as log:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=budget, check=False)
        (out/(label+'.json')).write_text(json.dumps(dict(argv=command, returncode=result.returncode,
            elapsed_s=time.monotonic()-tick), indent=2)+'\n')
        if result.returncode:
            raise RuntimeError('Terminal step failed; preserve evidence: '+label)
    resource.check_resource(args.resource_check, Path(plan['kit']))
    (out/'COMPLETE.json').write_text(json.dumps(dict(complete=True, elapsed_s=time.monotonic()-started,
        model_calls=0, eda_calls=0, plan_sha256=args.plan_sha, original_audit_reused=reuse,
        full_batch_complete=False, promotion_decision_changed=False), indent=2)+'\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--plan-sha', required=True)
    p.add_argument('--resource-check', type=Path, required=True)
    a = p.parse_args()
    assert sys.platform == 'linux', 'Execution stays on authorized AMD'
    assert sha(a.plan) == a.plan_sha, 'Preparation changed'
    plan = json.loads(a.plan.read_text())
    root = a.plan.parent
    for name, digest in plan['files'].items():
        assert sha(root / name) == digest, name
    paired = Path(plan['paired'])
    assert sha(paired) == '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    spec = importlib.util.spec_from_file_location('postflight_resource', paired)
    resource = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resource)
    resource.check_resource(a.resource_check, Path(plan['kit']), first=True)
    if plan.get('mode') == 'phaseP_stability_terminal_v1':
        stability_postflight(root, plan, a, resource, paired)
        raise SystemExit(0)
    assert plan.get('mode') in (None, 'paired_terminal_v1'), 'Unknown postflight mode'
    prior = Path(plan['selfcheck_root'])
    prior_guard = json.loads((prior / 'guard/status.json').read_text())
    prior_result = json.loads((prior / 'results/SELF_CHECK.json').read_text())
    assert all(prior_guard[k] for k in ['complete', 'passed', 'model_unchanged',
                                       'protected_files_unchanged', 'own_slot_released'])
    assert prior_guard['owned_cleanup']['verified'] and not prior_guard['owned_cleanup']['remaining']
    assert prior_result['complete'] and prior_result['passed']
    assert sha(prior / plan['selfcheck_source']) == plan['analysis_sha256']
    out = root / 'results'
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    commands = [
        [sys.executable, '-B', str(root / 'owner_audit/audit.py'),
         '--archive', str(root / 'INPUT.zip'), '--out', str(out / 'audit'),
         '--spec-sha', plan['spec_sha256']],
        [sys.executable, '-B', str(root / 'analysis.py'),
         '--archive', str(root / 'INPUT.zip'), '--spec', str(root / 'inputs/RUN_SPEC.json'),
         '--summary', str(root / 'inputs/summary.json'), '--guard', str(root / 'inputs/guard.json'),
         '--audit', str(out / 'audit/RESULTS.json'), '--out', str(out / 'STATISTICS.json'),
         '--resource-check', str(a.resource_check), '--paired', str(paired), '--kit', plan['kit']],
    ]
    for i, command in enumerate(commands):
        resource.check_resource(a.resource_check, Path(plan['kit']))
        tick = time.monotonic()
        with (out / f'step_{i}.log').open('xb') as log:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=120, check=False)
        (out / f'step_{i}.json').write_text(json.dumps(dict(
            argv=command, returncode=result.returncode,
            elapsed_s=time.monotonic()-tick), indent=2)+'\n')
        if result.returncode:
            raise RuntimeError(f'Postflight step {i} failed; preserve evidence, do not regenerate')
    resource.check_resource(a.resource_check, Path(plan['kit']))
    (out / 'COMPLETE.json').write_text(json.dumps(dict(
        complete=True, elapsed_s=time.monotonic()-started, model_calls=0, eda_calls=0,
        plan_sha256=a.plan_sha, full_batch_complete=False), indent=2)+'\n')
