"""Grade the frozen six-call R1 pilot; never generate, retry, or select answers.

All official judgements precede candidate-only xvlog/xelab. Each invocation
creates a fresh grading directory and preserves failures without resuming them.
The existing model slot is checked, never acquired, rewritten, or released here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time

TASK = 'Prob156_review2015_fancytimer'
ORDER = [(0, 'diagnostic'), (0, 'control'), (1, 'control'),
         (1, 'diagnostic'), (2, 'diagnostic'), (2, 'control')]
UPSTREAM_COMMIT = 'afd135e7ba5f6ec4c6d77e7c927c894327537801'
UPSTREAM_SHA = '0e47545af9001ecd884807ef6008c9c88700cf77d72f543c357103888698984b'
INPUT_SHA = {
    'prompt.txt': '262f49e7ee666f52dd73fcc4077f172b7c50b549c9657e54cfc0849d419bd9f9',
    'candidate.sv': 'ddda812b46cc944ca265f7cb0ef70af68877b9e73cf345a4a2dea7fa1ea3e0fb',
    'detect.json': 'bb1bfa40308fe4df5665d8cd52f6a0339817ff77134eb6560c4d6ba8cc1aec63',
}
PACKAGE_SHA = {
    'baseline.py': '537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51',
    'skill/rtl-generation/SKILL.md': 'f4c4c8e2d97ec476b1282dd517f5c5008a497c4a03b36996fdabb27cf1cabd01',
    'skill/rtl-feedback-repair/SKILL.md': 'aee81f188b3717ce10dc72efd11b01f009acc0d27211e7dcd4ce02cbf0802f74',
}
JUDGE_TIMEOUT_S = 600
STRUCTURE_TIMEOUT_S = 60


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8', newline='\n')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_evaluator(path, kit):
    evaluator = load_module('r1_external_evaluator', path)
    # The verified adapter is staged outside the kit. Its imports must still
    # resolve the pinned official files under the original kit, not staging.
    evaluator.ROOT = kit
    evaluator.OFFICIAL = kit / 'official_reference'
    require(evaluator.verify_upstream() == UPSTREAM_COMMIT, 'unexpected official upstream')
    return evaluator


def verify_hashes(root, hashes):
    for rel, expected in hashes.items():
        path = (root / rel).resolve()
        require(path.is_relative_to(root.resolve()), 'path escapes frozen root: ' + rel)
        require(path.is_file() and digest(path) == expected, 'hash mismatch: ' + str(path))


def files_under(root):
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            require(path.resolve().is_relative_to(root.resolve()), 'symlink escapes root: ' + str(path))
            files[str(path.relative_to(root)).replace('\\', '/')] = digest(path)
    return files


def check_slot(path, owner, expected=None):
    raw = path.read_bytes()
    lines = raw.decode('utf-8').splitlines()
    require(bool(owner) and bool(lines) and lines[0] == owner, 'model slot is not held by requested owner')
    require(expected is None or raw == expected, 'model slot contents changed; stop without modifying the lock')
    return raw


def validate_generation(run, kit):
    plan = read_json(run / 'plan.json')
    generation = read_json(run / 'generation.json')
    require(plan.get('schema') == 'r1-diagnostic-pilot-v1' and plan.get('task_id') == TASK,
            'not the frozen Prob156 R1 pilot')
    require(generation.get('complete') is True and generation.get('status') == 'generated_ungraded',
            'six generations must be complete before any judgement')
    require(plan.get('planned_calls') == 6 and plan.get('repetitions') == 3
            and generation.get('calls_attempted') == 6, 'expected exactly six calls and three pairs')
    require(plan.get('model') == 'Qwen3.6-27B-Q4_K_M'
            and generation.get('served_model_before') == plan['model'], 'generation used an unexpected model')
    require(generation.get('plan_sha256') == digest(run / 'plan.json'), 'generation plan hash mismatch')
    require(Path(plan['package']).resolve() == (kit / 'submission').resolve(), 'generation package is not this kit')
    require(plan['package_sha256'] == PACKAGE_SHA, 'unexpected baseline/skills pins')
    verify_hashes(kit / 'submission', PACKAGE_SHA)
    require(digest(kit / 'bench/diagnostic_repair_pilot.py') == plan['harness_sha256'],
            'generation harness changed after freeze')
    for name, expected in INPUT_SHA.items():
        require(plan['input_sha256'].get(name) == expected, 'unexpected frozen input: ' + name)
    verify_hashes(run / 'inputs', plan['input_sha256'])
    require(set(files_under(run / 'inputs')) == set(plan['input_sha256']), 'frozen input file set changed')
    require(len(plan['records']) == len(generation['records']) == 6, 'incomplete or extra generation records')
    require([(r['pair'], r['arm']) for r in plan['records']] == ORDER, 'paired order changed')
    baseline = load_module('r1_frozen_baseline', kit / 'submission/baseline.py')
    paths = [run / 'plan.json', run / 'generation.json']
    paths.extend(run / 'inputs' / name for name in plan['input_sha256'])
    rows = []
    for sequence, (frozen, record) in enumerate(zip(plan['records'], generation['records'])):
        pair, arm = ORDER[sequence]
        name = f'{sequence:02d}_pair{pair}_{arm}'
        require(frozen['sequence'] == sequence and frozen['directory'] == name, 'sample identity mismatch')
        require(all(record.get(k) == v for k, v in frozen.items()), 'generation record differs from frozen request')
        require(record.get('error') is None, 'generation has a client failure')
        sample = run / name
        require(read_json(sample / 'generation.json') == record, 'sample generation receipt differs from aggregate')
        require(digest(sample / 'request.json') == frozen['request_sha256'], 'request hash mismatch: ' + name)
        require(digest(sample / 'solution.v') == record['solution_sha256'], 'solution hash mismatch: ' + name)
        reply = (sample / 'reply.txt').read_text(encoding='utf-8')
        response = read_json(sample / 'response.json')
        require((response['choices'][0]['message'].get('content') or '') == reply, 'response/reply mismatch: ' + name)
        expected = baseline.extract(reply, 'rtl') if reply else ''
        solution = (sample / 'solution.v').read_text(encoding='utf-8')
        require(solution == expected and record['empty'] == (not solution.strip()), 'reply/extracted candidate mismatch: ' + name)
        wall = record.get('wall_seconds')
        require(type(wall) in (int, float) and math.isfinite(wall) and wall >= 0, 'invalid generation wall time')
        require(response.get('model') in (None, plan['model']), 'response model changed')
        paths.extend(sample / p for p in ('request.json', 'generation.json', 'response.json',
                                         'reply.txt', 'solution.v', 'client.log'))
        rows.append(dict(frozen, generation=record, solution=str(sample / 'solution.v')))
    return rows, {str(p.relative_to(run)).replace('\\', '/'): digest(p) for p in paths}


def run_tool(command, cwd, label):
    """Bound one EDA command in an owned process session; retain all logs."""
    start = time.monotonic()
    result = dict(command=command, timeout=False, returncode=None)
    try:
        with (cwd / (label + '.stdout.log')).open('wb') as stdout, (cwd / (label + '.stderr.log')).open('wb') as stderr:
            proc = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr,
                                    start_new_session=(os.name != 'nt'))
            result['pid'] = proc.pid
            try:
                result['returncode'] = proc.wait(timeout=STRUCTURE_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                result['timeout'] = True
                # Only this Popen-created session is signalled; never match
                # process names or touch shared model/Vivado processes.
                if os.name != 'nt':
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    proc.kill()
                result['returncode'] = proc.wait(timeout=10)
    except Exception as exc:
        result['error'] = repr(exc)
    result['wall_seconds'] = time.monotonic() - start
    write_json(cwd / (label + '.execution.json'), result)
    require(not result.get('error') and not result['timeout'] and result['returncode'] in (0, 1),
            label + ' infrastructure/unusual exit failure; inspect retained execution/log files')
    logs = ''.join((cwd / (label + suffix)).read_text(encoding='utf-8', errors='replace')
                   for suffix in ('.stdout.log', '.stderr.log'))
    require(not re.search(r'No space left on device|Failed to (?:acquire|obtain).*license|'
                          r'License checkout failed|FLEXnet Licensing error|Segmentation fault', logs, re.I),
            label + ' environment error in log; stop without treating it as candidate failure')
    return result


def check_structure(solution, destination, tools):
    destination.mkdir(exist_ok=False)
    shutil.copyfile(solution, destination / 'dut.sv')
    result = dict(solution_sha256=digest(solution), passed=False, empty=False,
                  xvlog=None, xelab=None, testbench_used=False)
    if not Path(solution).read_text(encoding='utf-8').strip():
        result['empty'] = True
    else:
        result['xvlog'] = run_tool([tools['xvlog'], '-sv', '--nolog', 'dut.sv'], destination, 'xvlog')
        if result['xvlog']['returncode'] == 0:
            result['xelab'] = run_tool([tools['xelab'], 'TopModule', '-s', 'snapshot', '--nolog',
                                       '-timescale', '1ps/1ps'], destination, 'xelab')
            result['passed'] = result['xelab']['returncode'] == 0
    write_json(destination / 'structure.json', result)
    return result


def validate_judge_evidence(verdict, destination):
    require(not verdict.get('tool_error'), 'official tool_error; all six must be scoreable')
    require(verdict.get('task_id') == TASK and verdict.get('judge_evidence_complete') is True
            and verdict.get('judge_rc') == 0, 'official adapter did not return complete evidence')
    receipt = read_json(destination / 'judge_receipt.json')
    require(receipt.get('judge_rc') == 0 and receipt.get('errors') == [], 'judge receipt has errors')
    require(bool(receipt.get('evidence')), 'empty judge evidence receipt')
    for name, meta in receipt['evidence'].items():
        file = destination / 'judge_work_logs' / name
        require(file.is_file() and digest(file) == meta['sha256'] and file.stat().st_size == meta['bytes'],
                'judge evidence missing or changed: ' + name)


def summarize(score, samples):
    arms = {}
    official = {}
    for arm in ('diagnostic', 'control'):
        records = sorted([r for r in samples if r['arm'] == arm], key=lambda r: r['pair'])
        require([r['pair'] for r in records] == [0, 1, 2], 'incomplete arm')
        verdicts = [r['verdict'] for r in records]
        official[arm] = score.summarize({TASK: verdicts})
        aggregation = official[arm]
        require(aggregation['tool_errors'] == 0 and aggregation['scored_tasks'] == 1
                and aggregation['per_task'][0]['scored_samples'] == 3, 'not all six planned samples were scored')
        timing = [r['generation']['wall_seconds'] for r in records]
        arms[arm] = dict(levels=[v['level'] for v in verdicts],
                         level_counts={f'L{i}': aggregation['level_counts'].get(f'L{i}', 0) for i in range(4)},
                         coefficient_mean=aggregation['set_score'], scored_samples=3, planned_samples=3,
                         elaboration_passed=sum(r['structure']['passed'] for r in records),
                         empty_answers=sum(r['generation']['empty'] for r in records),
                         truncated=sum(r['generation'].get('finish_reason') == 'length' for r in records),
                         generation_wall_s=dict(values=timing, mean=statistics.mean(timing), min=min(timing), max=max(timing)),
                         usage_by_pair=[r['generation'].get('usage') for r in records])
    d, c = arms['diagnostic'], arms['control']
    if d['coefficient_mean'] > c['coefficient_mean'] and d['elaboration_passed'] >= c['elaboration_passed']:
        decision = 'single_candidate_positive_signal_expand_to_new_tasks_and_guards_not_deploy'
    elif d['coefficient_mean'] == c['coefficient_mean'] and d['elaboration_passed'] > c['elaboration_passed']:
        decision = 'structure_improved_without_quality_score_advantage'
    else:
        decision = 'no_promotion_archive_this_implementation'
    pairs = []
    for pair in range(3):
        values = {r['arm']: r['verdict'] for r in samples if r['pair'] == pair}
        pairs.append(dict(pair=pair, diagnostic_level=values['diagnostic']['level'],
                          control_level=values['control']['level'],
                          coefficient_difference=round(values['diagnostic']['coefficient'] - values['control']['coefficient'], 10)))
    return dict(arms=arms, pairs=pairs, decision=decision, valid_samples=6, planned_samples=6,
                scoring_source='pinned official score.summarize({task_id: [v0,v1,v2]})',
                limits='One previously selected candidate, three repeats per arm, no guards; not statistical significance, formal baseline gain, full-set improvement or five-sample validation.'), official


def grade(args):
    sys.dont_write_bytecode = True
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    run, kit, evaluator_path = [Path(p).resolve() for p in (args.run, args.kit, args.evaluator)]
    require(run.is_dir(), 'generation run does not exist')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    output = run / ('grading_' + stamp)
    output.mkdir(exist_ok=False)
    started = time.monotonic()
    report = dict(complete=False, status='preflight', output=str(output), task_id=TASK,
                  samples=[], errors=[], valid_samples=0, planned_samples=6)
    initial = None
    try:
        slot = Path(args.slot_file)
        slot_bytes = check_slot(slot, args.slot_owner)
        rows, frozen_files = validate_generation(run, kit)
        require(digest(kit / 'official_reference/UPSTREAM.json') == UPSTREAM_SHA, 'official pin manifest changed')
        task = kit / 'bench/tasks_veval' / TASK
        require(read_json(task / 'task.json')['task_id'] == TASK, 'official task identity mismatch')
        require(digest(task / 'prompt.txt') == INPUT_SHA['prompt.txt'], 'official task prompt differs from frozen prompt')
        evaluator = load_evaluator(evaluator_path, kit)
        score = load_module('r1_pinned_score', kit / 'official_reference/selftest/score.py')
        tools = {name: shutil.which(name) for name in ('xvlog', 'xelab')}
        require(all(tools.values()), 'xvlog and xelab must both be available before judging')

        def snapshot():
            return dict(package=files_under(kit / 'submission'), task=files_under(task),
                        official=files_under(kit / 'official_reference'),
                        evaluator_sha256=digest(evaluator_path), grader_sha256=digest(__file__),
                        generation_files={name: digest(run / name) for name in frozen_files},
                        tools={name: dict(path=path, sha256=digest(path)) for name, path in tools.items()})

        initial = snapshot()
        require(initial['generation_files'] == frozen_files, 'generation changed during preflight')
        write_json(output / 'before.json', initial)
        shutil.copyfile(__file__, output / 'grader_source.py')
        shutil.copyfile(evaluator_path, output / 'evaluator_source.py')
        report.update(slot_owner=args.slot_owner, slot_sha256=hashlib.sha256(slot_bytes).hexdigest(),
                      upstream_commit=UPSTREAM_COMMIT, status='official_judging')

        def unchanged():
            check_slot(slot, args.slot_owner, slot_bytes)
            require(snapshot() == initial, 'package, task, official tools, evaluator, or generation changed during grading')

        # Do not inspect a structural result or select a candidate before the
        # fixed six official judgements have been attempted in frozen order.
        for row in rows:
            unchanged()
            destination = output / ('official_' + row['directory'])
            destination.mkdir(exist_ok=False)
            tick = time.monotonic()
            verdict_path = destination / 'verdict.json'
            verdict = evaluator.judge_sample(task, Path(row['solution']), destination,
                                              verdict_path, JUDGE_TIMEOUT_S)
            validate_judge_evidence(verdict, destination)
            require(read_json(verdict_path) == verdict, 'returned verdict and retained verdict differ')
            sample = dict(row, verdict=verdict, official_wall_seconds=time.monotonic() - tick,
                          official_directory=str(destination))
            report['samples'].append(sample)
            report['valid_samples'] += 1
            write_json(output / 'progress.json', report)
            print(json.dumps(dict(stage='official', sample=row['directory'], level=verdict['level'])), flush=True)

        report['status'] = 'candidate_only_structure'
        for sample in report['samples']:
            unchanged()
            tick = time.monotonic()
            sample['structure'] = check_structure(sample['solution'], output / ('structure_' + sample['directory']), tools)
            sample['structure_wall_seconds'] = time.monotonic() - tick
            write_json(output / 'progress.json', report)
            print(json.dumps(dict(stage='structure', sample=sample['directory'], passed=sample['structure']['passed'])), flush=True)
        unchanged()
        analysis, official = summarize(score, report['samples'])
        # Preserve the official output verbatim. Its generic pass@5 field is
        # not an experimental metric here; the report uses only mean scores.
        write_json(output / 'official_summaries.json', official)
        report.update(analysis, complete=True, status='graded_complete',
                      synthesis_review_samples=[r['directory'] for r in report['samples']
                                                if r['verdict'].get('suspected_silent_degradation')])
        write_json(output / 'after.json', snapshot())
    except Exception as exc:
        report.update(status='not_valid_stop', complete=False, decision='not_determinable')
        report['errors'].append(repr(exc))
        if initial is not None:
            try:
                write_json(output / 'after.json', snapshot())
            except Exception as final_exc:
                report['errors'].append('post-snapshot: ' + repr(final_exc))
    report['grading_wall_seconds'] = time.monotonic() - started
    write_json(output / 'summary.json', report)
    print(json.dumps(dict(output=str(output), complete=report['complete'], status=report['status'],
                          decision=report.get('decision'), errors=report['errors']), ensure_ascii=False), flush=True)
    return 0 if report['complete'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--kit', required=True)
    parser.add_argument('--evaluator', required=True)
    parser.add_argument('--slot-owner', required=True)
    parser.add_argument('--slot-file', default='/workspace/team/SLOT.lock')
    args = parser.parse_args()
    return grade(args)


if __name__ == '__main__':
    raise SystemExit(main())
