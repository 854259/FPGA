"""Freeze and generate six paired repairs; no EDA, judging, or answer selection.

Uses the unchanged official baseline's post_json/extract helpers, matching the
runtime repair request parameters. The sole treatment is candidate-only xelab
diagnostic text. Run only while holding the existing shared model slot.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlparse

TASK = 'Prob156_review2015_fancytimer'
EXPECTED = {
    'prompt.txt': '262f49e7ee666f52dd73fcc4077f172b7c50b549c9657e54cfc0849d419bd9f9',
    'candidate.sv': 'ddda812b46cc944ca265f7cb0ef70af68877b9e73cf345a4a2dea7fa1ea3e0fb',
    'detect.json': 'bb1bfa40308fe4df5665d8cd52f6a0339817ff77134eb6560c4d6ba8cc1aec63',
}
PINNED_PACKAGE = {
    'baseline.py': '537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51',
    'skill/rtl-generation/SKILL.md': 'f4c4c8e2d97ec476b1282dd517f5c5008a497c4a03b36996fdabb27cf1cabd01',
    'skill/rtl-feedback-repair/SKILL.md': 'aee81f188b3717ce10dc72efd11b01f009acc0d27211e7dcd4ce02cbf0802f74',
}
ORDER = [(0, 'diagnostic'), (0, 'control'), (1, 'control'),
         (1, 'diagnostic'), (2, 'diagnostic'), (2, 'control')]
MODEL = 'Qwen3.6-27B-Q4_K_M'
CALL_SECONDS = 300


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8', newline='\n')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify_files(root, identities):
    for name, expected in identities.items():
        if digest(Path(root) / name) != expected:
            raise ValueError('hash mismatch: ' + name)


def baseline_module(package):
    verify_files(package, PINNED_PACKAGE)
    spec = importlib.util.spec_from_file_location('pilot_baseline', Path(package) / 'baseline.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def freeze(args):
    inputs, package, out = map(lambda p: Path(p).resolve(),
                               (args.inputs, args.package, args.out))
    verify_files(inputs, EXPECTED)
    verify_files(package, PINNED_PACKAGE)
    provenance = read_json(inputs / 'provenance.json')
    if provenance['detector_dut_sha256'] != EXPECTED['candidate.sv']:
        raise ValueError('detector did not inspect the frozen candidate')
    parsed = urlparse(args.endpoint)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('use the existing loopback model service')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('model endpoint must not contain credentials, query or fragment')
    rows = [r for r in read_json(inputs / 'detect.json') if r['task'] == TASK]
    if len(rows) != 1 or rows[0]['xvlog_rc'] != 0 or rows[0]['xelab_rc'] != 1:
        raise ValueError('expected exactly one candidate-only elaboration failure')
    errors = rows[0]['multi_driver']
    # The historical detector clipped each line at 150 chars; remove only the
    # clipped absolute filename suffix, retaining the actual diagnostic wording.
    diagnostics = '\n'.join(re.sub(r'\s+\[/workspace/.*$', '', line) for line in errors)
    if len(errors) != 5 or any('[VRFC 10-3818]' not in line for line in errors):
        raise ValueError('unexpected archived diagnostics; review before changing design')
    prompt = (inputs / 'prompt.txt').read_text(encoding='utf-8')
    candidate = (inputs / 'candidate.sv').read_text(encoding='utf-8')
    skill = (package / 'skill/rtl-generation/SKILL.md').read_text(encoding='utf-8')
    repair = (package / 'skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8')
    # An already existing directory is never overwritten, even if empty.
    out.mkdir(parents=True, exist_ok=False)
    (out / 'inputs').mkdir()
    for name in (*EXPECTED, 'provenance.json'):
        (out / 'inputs' / name).write_bytes((inputs / name).read_bytes())
    (out / 'inputs/diagnostics.txt').write_text(diagnostics + '\n', encoding='utf-8', newline='\n')
    records = []
    for seq, (pair, arm) in enumerate(ORDER):
        name = f'{seq:02d}_pair{pair}_{arm}'
        sample = out / name
        sample.mkdir()
        feedback = diagnostics if arm == 'diagnostic' else 'No diagnostic text is provided.'
        user = (prompt + '\nPrevious candidate:\n' + candidate +
                '\nCandidate diagnostics:\n' + feedback +
                '\nReview the candidate against the specification. Return one complete corrected '
                'TopModule. Preserve the required interface and behaviour; output only code.')
        body = dict(model=MODEL, messages=[dict(role='system', content=skill + '\n' + repair),
                                          dict(role='user', content=user)],
                    temperature=0.0, top_p=1.0, max_tokens=8192)
        write_json(sample / 'request.json', body)
        records.append(dict(sequence=seq, pair=pair, arm=arm, directory=name,
                            request_sha256=digest(sample / 'request.json')))
    plan = dict(schema='r1-diagnostic-pilot-v1', task_id=TASK, status='frozen_not_run',
                package=str(package), package_sha256=PINNED_PACKAGE,
                harness_sha256=digest(__file__), model=MODEL, endpoint=args.endpoint.rstrip('/'),
                input_sha256={p.name: digest(p) for p in (out / 'inputs').iterdir()},
                repetitions=3, planned_calls=6, per_call_wall_limit_s=CALL_SECONDS,
                max_output_tokens_per_call=8192, temperature=0.0, seed=None,
                seed_note='No seed is sent, matching runtime; three repetitions are not independent tasks.',
                sole_treatment='candidate-only xelab diagnostics vs no diagnostic text',
                budget_note='Same call/token/time caps; actual input/output tokens and time can differ.',
                evaluation='External pinned official judge after all six candidates exist; never select best.',
                inputs_exclude=['task.json', 'testbench', 'reference', 'mismatch', 'official verdict'],
                records=records)
    write_json(out / 'plan.json', plan)
    print(json.dumps(dict(status='frozen_not_run', out=str(out), calls=6,
                          plan_sha256=digest(out / 'plan.json'))))


def child_call(out, name):
    plan = read_json(out / 'plan.json')
    baseline = baseline_module(plan['package'])
    sample = out / name
    body = read_json(sample / 'request.json')
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
    payload = baseline.post_json(plan['endpoint'] + '/chat/completions', body)
    write_json(sample / 'response.json', payload)
    choice = payload['choices'][0]
    reply = choice['message'].get('content') or ''
    if not isinstance(reply, str):
        raise ValueError('non-string completion content')
    (sample / 'reply.txt').write_text(reply, encoding='utf-8', newline='\n')
    # Empty replies remain empty candidates and must be graded L0, not removed.
    (sample / 'solution.v').write_text(baseline.extract(reply, 'rtl') if reply else '',
                                     encoding='utf-8', newline='\n')


def check_slot(path, owner, expected=None):
    raw = Path(path).read_bytes()
    lines = raw.decode().splitlines()
    if not lines or lines[0] != owner or (expected is not None and raw != expected):
        raise ValueError('shared slot ownership changed; stop without releasing someone else\'s slot')
    return raw


def run(args):
    out = Path(args.out).resolve()
    plan = read_json(out / 'plan.json')
    if digest(__file__) != plan['harness_sha256']:
        raise ValueError('harness changed after freeze; prepare a new run')
    verify_files(out / 'inputs', plan['input_sha256'])
    verify_files(plan['package'], plan['package_sha256'])
    if [(r['pair'], r['arm']) for r in plan['records']] != ORDER:
        raise ValueError('frozen order changed')
    for row in plan['records']:
        if digest(out / row['directory'] / 'request.json') != row['request_sha256']:
            raise ValueError('frozen request changed')
    slot_bytes = check_slot(args.slot_file, args.slot_owner)
    # No resume/retry: an interrupted run remains incomplete with its evidence.
    with (out / '.started').open('x', encoding='utf-8') as f:
        f.write(str(time.time()))
    report = dict(complete=False, status='preflight', plan_sha256=digest(out / 'plan.json'),
                  model_slot_owner=args.slot_owner, slot_sha256=hashlib.sha256(slot_bytes).hexdigest(),
                  calls_attempted=0, records=[], grading_performed=False)
    write_json(out / 'generation.json', report)
    baseline = baseline_module(plan['package'])
    baseline.BASE_URL = plan['endpoint']
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
    served = baseline.served_model()
    report['served_model_before'] = served
    if served != MODEL:
        report.update(status='invalid_model_identity', error='expected served model unavailable')
        write_json(out / 'generation.json', report)
        return 1
    for row in plan['records']:
        try:
            check_slot(args.slot_file, args.slot_owner, slot_bytes)
            verify_files(plan['package'], plan['package_sha256'])
        except (OSError, ValueError) as exc:
            report.update(status='invalid_precondition', error=str(exc))
            write_json(out / 'generation.json', report)
            return 1
        sample = out / row['directory']
        started = time.monotonic()
        error = None
        report['calls_attempted'] += 1
        with (sample / 'client.log').open('w', encoding='utf-8') as log:
            try:
                proc = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                                       '_call', '--out', str(out), '--sample', row['directory']],
                                      stdout=log, stderr=subprocess.STDOUT, timeout=CALL_SECONDS)
                if proc.returncode:
                    error = 'model_client_exit_' + str(proc.returncode)
            except subprocess.TimeoutExpired:
                # subprocess.run kills and waits for this child only. It launches
                # no descendants and does not manage the shared model server.
                error = 'model_client_wall_deadline'
        elapsed = time.monotonic() - started
        rec = dict(row, wall_seconds=elapsed, error=error)
        if error is None:
            response = read_json(sample / 'response.json')
            choice = response['choices'][0]
            rec.update(solution_sha256=digest(sample / 'solution.v'),
                       empty=not (sample / 'solution.v').read_text(encoding='utf-8').strip(),
                       finish_reason=choice.get('finish_reason'), usage=response.get('usage'),
                       response_model=response.get('model'))
            if response.get('model') not in (None, MODEL):
                error = rec['error'] = 'response_model_identity_changed'
        write_json(sample / 'generation.json', rec)
        report['records'].append(rec)
        report['status'] = 'invalid_client_failure' if error else 'running'
        write_json(out / 'generation.json', report)
        print(json.dumps(rec), flush=True)
        if error:
            # A timed-out server may still be processing: stop and inspect,
            # never launch replacement calls or kill the shared server.
            return 1
    report.update(complete=True, status='generated_ungraded',
                  total_call_wall_s=sum(r['wall_seconds'] for r in report['records']))
    write_json(out / 'generation.json', report)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('freeze')
    prep.add_argument('--inputs', required=True)
    prep.add_argument('--package', required=True)
    prep.add_argument('--out', required=True)
    prep.add_argument('--endpoint', default='http://127.0.0.1:8000/v1')
    execute = sub.add_parser('run')
    execute.add_argument('--out', required=True)
    execute.add_argument('--slot-owner', required=True)
    execute.add_argument('--slot-file', default='/workspace/team/SLOT.lock')
    child = sub.add_parser('_call', help=argparse.SUPPRESS)
    child.add_argument('--out', required=True)
    child.add_argument('--sample', required=True)
    args = parser.parse_args()
    if args.command == 'freeze':
        freeze(args)
        return 0
    if args.command == '_call':
        child_call(Path(args.out).resolve(), args.sample)
        return 0
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
