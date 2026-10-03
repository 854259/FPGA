"""Freeze and generate twelve signedness-review repairs; no EDA or judging.

Uses the unchanged official baseline's post_json/extract helpers, matching the
runtime repair request parameters. The sole treatment is a generic specification-derived signedness checklist. Run only while holding the existing shared model slot.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse

TASKS = ['Prob115_shift18', 'Prob042_vector4', 'Prob055_conditional']
EXPECTED = {
    'Prob115_shift18/prompt.txt': '2b1406045f6a92c759dc6b0de75ce7ffe7b44028c84e49534c9f4a2ce346566b',
    'Prob115_shift18/candidate.sv': '086739fb357f61bfc0e11cff6169af47f9d1da76dc1bc66f7416c31f782d2ae5',
    'Prob042_vector4/prompt.txt': '8d2ef1d00ecc693bcf3b1438fb20676ed098d3dd52660618f78a0a02a225d7da',
    'Prob042_vector4/candidate.sv': 'aa9fe811a0a7d67efffa1584f8c43e7e10bc6f5854d2c3e7441c5970d09d0509',
    'Prob055_conditional/prompt.txt': 'a4cb1a6391988c0c0661808b8bafb625160c70dab00c917bc970be65aa9b34c7',
    'Prob055_conditional/candidate.sv': '6ca243642c6efbaf8e88c8b3618d3af97f9406f86329921a72daa617bdebd5ce',
}
PINNED_PACKAGE = {
    'baseline.py': '537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51',
    'skill/rtl-generation/SKILL.md': 'f4c4c8e2d97ec476b1282dd517f5c5008a497c4a03b36996fdabb27cf1cabd01',
    'skill/rtl-feedback-repair/SKILL.md': 'aee81f188b3717ce10dc72efd11b01f009acc0d27211e7dcd4ce02cbf0802f74',
}
ORDER = [(task, pair, arm) for task in TASKS for pair, arm in
         [(0, 'diagnostic'), (0, 'control'), (1, 'control'), (1, 'diagnostic')]]
CHECKLIST = (
    'Before finalizing, infer the required bit widths, signed or unsigned '
    'interpretation, extension behaviour and shift semantics from the explicit '
    'specification. Check that operand declarations and expression types implement '
    'those requirements. Correct only what the specification requires; do not add '
    'unspecified initialization or change the required interface.'
)
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
    parsed = urlparse(args.endpoint)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('use the existing loopback model service')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('model endpoint must not contain credentials, query or fragment')
    validation = Path(args.probe_validation).resolve()
    validation_data = read_json(validation)
    if not all(validation_data.get(k) is True for k in ('complete', 'valid', 'assets_unchanged')):
        raise ValueError('all positive and semantic-negative probe controls must pass first')
    probes = Path(args.probe_runner).resolve().parent
    identities = validation_data.get('probe_files', {})
    expected_assets = {'probe_runner.py'} | {task + '/' + name for task in TASKS
                                            for name in ('tb.sv', 'positive.sv', 'negative.sv')}
    if set(identities) != expected_assets:
        raise ValueError('probe validation asset manifest incomplete')
    verify_files(probes, identities)
    if set(validation_data.get('tasks', {})) != set(TASKS):
        raise ValueError('probe validation task set incomplete')
    for task in TASKS:
        row = validation_data['tasks'][task]
        if (row.get('valid') is not True or row['positive'].get('status') != 'pass'
                or row['negative'].get('status') != 'fail'
                or row['negative'].get('failure_kind') != 'semantic_mismatch'):
            raise ValueError('positive/negative control not validated: ' + task)
        for mode in ('positive', 'negative'):
            result = row[mode]
            if (result.get('solution_sha256') != identities[task + '/' + mode + '.sv']
                    or result.get('tb_sha256') != identities[task + '/tb.sv']
                    or result.get('runner_sha256') != identities['probe_runner.py']):
                raise ValueError('control receipt does not match frozen source: ' + task)
    auxiliary = {str(Path(p).resolve()): digest(p) for p in args.freeze_file}
    for name, sha in identities.items():
        if auxiliary.get(str(probes / name)) != sha:
            raise ValueError('freeze all validated probe assets: ' + name)
    skill = (package / 'skill/rtl-generation/SKILL.md').read_text(encoding='utf-8')
    repair = (package / 'skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8')
    out.mkdir(parents=True, exist_ok=False)
    for name in (*EXPECTED, 'provenance.json'):
        dst = out / 'inputs' / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((inputs / name).read_bytes())
    records = []
    for seq, (task, pair, arm) in enumerate(ORDER):
        prompt = (inputs / task / 'prompt.txt').read_text(encoding='utf-8')
        candidate = (inputs / task / 'candidate.sv').read_text(encoding='utf-8')
        name = f'{seq:02d}_{task}_pair{pair}_{arm}'
        sample = out / name
        sample.mkdir()
        user = (prompt + '\nPrevious candidate:\n' + candidate +
                '\nReview the candidate against the specification. Return one complete corrected '
                'TopModule. Preserve the required interface and behaviour; output only code.')
        if arm == 'diagnostic':
            user += '\nReview checklist:\n' + CHECKLIST
        body = dict(model=MODEL, messages=[dict(role='system', content=skill + '\n' + repair),
                                          dict(role='user', content=user)],
                    temperature=0.0, top_p=1.0, max_tokens=8192)
        write_json(sample / 'request.json', body)
        records.append(dict(sequence=seq, task_id=task, pair=pair, arm=arm, directory=name,
                            request_sha256=digest(sample / 'request.json')))
    plan = dict(schema='r2-signedness-pilot-v1', task_ids=TASKS, status='frozen_not_run',
                package=str(package), package_sha256=PINNED_PACKAGE,
                harness_path=str(Path(__file__).resolve()), harness_sha256=digest(__file__), model=MODEL, endpoint=args.endpoint.rstrip('/'),
                input_sha256={p.relative_to(out / 'inputs').as_posix(): digest(p)
                              for p in (out / 'inputs').rglob('*') if p.is_file()},
                probe_validation=dict(path=str(validation), sha256=digest(validation)),
                auxiliary_sha256=auxiliary,
                repetitions=2, planned_calls=12, per_call_wall_limit_s=CALL_SECONDS,
                max_output_tokens_per_call=8192, temperature=0.0, seed=None,
                seed_note='No seed is sent, matching runtime; repetitions are not independent tasks.',
                sole_treatment='generic specification-derived signedness checklist vs generic review',
                budget_note='Same call/token/time caps; actual tokens and time can differ.',
                promotion='115 D mean > C mean; both 115 D probe pass; both guards D all L3. Expand only, no deployment.',
                conflict_stop='Any official L3 with failed prompt probe blocks promotion for evidence review.',
                evaluation='Pinned official judge and separate probes only after all twelve candidates exist.',
                inputs_exclude=['task.json', 'testbench', 'reference', 'mismatch', 'official verdict', 'probe feedback'],
                records=records)
    write_json(out / 'plan.json', plan)
    print(json.dumps(dict(status='frozen_not_run', out=str(out), calls=12,
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
    if [(r['task_id'], r['pair'], r['arm']) for r in plan['records']] != ORDER:
        raise ValueError('frozen order changed')
    for row in plan['records']:
        if digest(out / row['directory'] / 'request.json') != row['request_sha256']:
            raise ValueError('frozen request changed')
    verify_files(Path('/'), plan['auxiliary_sha256'])
    if digest(plan['probe_validation']['path']) != plan['probe_validation']['sha256']:
        raise ValueError('probe validation changed after freeze')
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
            verify_files(out / 'inputs', plan['input_sha256'])
            verify_files(Path('/'), plan['auxiliary_sha256'])
            if digest(out / row['directory'] / 'request.json') != row['request_sha256']:
                raise ValueError('request changed after freeze')
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
    prep.add_argument('--probe-validation', required=True)
    prep.add_argument('--probe-runner', required=True)
    prep.add_argument('--freeze-file', action='append', required=True)
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
