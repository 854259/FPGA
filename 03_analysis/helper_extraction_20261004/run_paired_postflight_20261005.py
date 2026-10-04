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
