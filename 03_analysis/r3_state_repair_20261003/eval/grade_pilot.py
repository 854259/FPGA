"""Grade the complete frozen 12-call R3 pilot; no generation or answer selection.

Official grades and independently validated prompt probes stay external to the
model. Missing samples, tool errors and changed inputs invalidate this pilot;
they are never excluded to create a smaller denominator.
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
import statistics
import sys
import time

TASKS = ('Prob086_lfsr5', 'Prob085_shift4', 'Prob033_ece241_2014_q1c')
TASK_CHECKS = {'Prob086_lfsr5': 269, 'Prob085_shift4': 209, 'Prob033_ece241_2014_q1c': 65536}
HELPER_SHA = '954a1bcac0015e9d0d104eade9d75d111e819ad827343cc4a462e4eb055beac0'
EVALUATOR_SHA = '53d1d4ff661ca6c3e27bc1d20a2328815dc39e281abc3a93757099b6e60bf797'
TARGET, *GUARDS = TASKS
ORDER = [(task, pair, arm) for task in TASKS for pair, arm in
         ((0, 'diagnostic'), (0, 'control'), (1, 'control'), (1, 'diagnostic'))]
UPSTREAM_COMMIT = 'afd135e7ba5f6ec4c6d77e7c927c894327537801'
UPSTREAM_SHA = '0e47545af9001ecd884807ef6008c9c88700cf77d72f543c357103888698984b'
INPUT_SHA = {
    'Prob086_lfsr5/prompt.txt': '161662a2c4c0b507de98adbbf7d186a5f6239342610cc024b4f1cb8c80904860',
    'Prob086_lfsr5/candidate.sv': 'e4446e9268ab1f6113e48a39ae8706c2e3263a56e287bac3132c0eb0042b0949',
    'Prob085_shift4/prompt.txt': '3a52419d4e26618db46f28eac7b6a9d72a42aa7d7bb74c390ad0dfa86a0301af',
    'Prob085_shift4/candidate.sv': 'f7caac1fa0fea137545df455937798de74ecd4372df8e6cd00a8188bec602ea3',
    'Prob033_ece241_2014_q1c/prompt.txt': 'e0af17e9255b0a9cc227c1fc506c6def2c13a044e9422a1eae329c766772f68b',
    'Prob033_ece241_2014_q1c/candidate.sv': '31b2592943f7054ba094462981758143cf01abb435bebe09e2d5820516c7adfa',
}
PACKAGE_SHA = {
    'baseline.py': '537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51',
    'skill/rtl-generation/SKILL.md': 'f4c4c8e2d97ec476b1282dd517f5c5008a497c4a03b36996fdabb27cf1cabd01',
    'skill/rtl-feedback-repair/SKILL.md': 'aee81f188b3717ce10dc72efd11b01f009acc0d27211e7dcd4ce02cbf0802f74',
}
MODEL = 'Qwen3.6-27B-Q4_K_M'
JUDGE_TIMEOUT_S = 600


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
    evaluator = load_module('r3_external_evaluator', path)
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
        if path.is_file() and '__pycache__' not in path.parts:
            require(path.resolve().is_relative_to(root.resolve()), 'symlink escapes root: ' + str(path))
            files[path.relative_to(root).as_posix()] = digest(path)
    return files


def check_slot(path, owner, expected=None):
    raw = path.read_bytes()
    lines = raw.decode('utf-8').splitlines()
    require(bool(owner) and bool(lines) and lines[0] == owner, 'model slot is not held by requested owner')
    require(expected is None or raw == expected, 'model slot changed; stop without modifying it')
    return raw


def validate_probe_result(result, task, solution, destination, probes_path, probe_root):
    require(result.get('task') == task and result.get('inputs_unchanged') is True,
            'probe identity or input consistency failure')
    require(result.get('status') in ('pass', 'fail'), 'probe environment failure; stop and inspect logs')
    require(Path(result['outdir']).resolve() == destination.resolve(), 'probe output directory mismatch')
    require(read_json(destination / 'result.json') == result, 'returned and saved probe result differ')
    require(result.get('solution_sha256') == digest(solution)
            and result.get('tb_sha256') == digest(probe_root / task / 'tb.sv')
            and result.get('runner_sha256') == digest(probes_path), 'probe input hashes differ')
    require(digest(destination / 'dut.sv') == digest(solution)
            and digest(destination / 'tb.sv') == digest(probe_root / task / 'tb.sv'),
            'executed DUT or TB copy differs from frozen input')
    require(bool(result.get('stages')), 'probe has no tool evidence')
    for stage in result['stages']:
        log = Path(stage['log']).resolve()
        require(log.is_relative_to(destination.resolve()), 'probe log escapes owned output')
        require(log.is_file() and digest(log) == stage['log_sha256'] and log.stat().st_size == stage['log_bytes'],
                'probe tool evidence missing or changed')
        require(not stage.get('timeout') and not stage.get('launch_error'), 'probe stage environment failure')
    if result['status'] == 'pass' or result.get('failure_kind') == 'semantic_mismatch':
        require(type(result.get('checks')) is int and result['checks'] == TASK_CHECKS[task]
                and type(result.get('mismatches')) is int and 0 <= result['mismatches'] <= result['checks'],
                'invalid completed probe counts')
        require([s['name'] for s in result['stages']] == ['xvlog', 'xelab', 'xsim']
                and all(s['returncode'] == 0 for s in result['stages']), 'semantic result requires three successful stages')
        require((result['mismatches'] == 0) == (result['status'] == 'pass'), 'probe status/counts disagree')
        text = (destination / 'xsim.log').read_text(encoding='utf-8', errors='replace')
        completed = re.findall(r'^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$', text, re.M)
        require(completed == [(task, str(result['checks']), str(result['mismatches']))],
                'probe raw completion summary differs from result')
    else:
        stage_names = [stage['name'] for stage in result['stages']]
        require(result.get('failure_kind') in ('xvlog_failed', 'xelab_failed'),
                'unknown candidate failure; cannot treat an environment failure as a verdict')
        failed_stage = result['failure_kind'].split('_')[0]
        require(stage_names == (['xvlog'] if failed_stage == 'xvlog' else ['xvlog', 'xelab'])
                and all(stage['returncode'] == 0 for stage in result['stages'][:-1])
                and result['stages'][-1]['returncode'] != 0
                and result.get('checks') is None and result.get('mismatches') is None,
                'candidate compile failure lacks matching stage evidence')


def validate_probe_validation(plan, probes_path, probe_root):
    validation_path = Path(plan['probe_validation']['path']).resolve()
    require(digest(validation_path) == plan['probe_validation']['sha256'], 'probe validation changed after freeze')
    validation = read_json(validation_path)
    require(validation.get('complete') is True and validation.get('valid') is True
            and validation.get('assets_unchanged') is True, 'controls not completely validated')
    require(set(validation['tasks']) == set(TASKS), 'probe controls do not cover the fixed tasks')
    expected_assets = {'probe_runner.py'} | {task + '/' + name for task in TASKS
                                          for name in ('tb.sv', 'positive.sv', 'negative.sv')}
    require(set(validation['probe_files']) == expected_assets, 'probe validation asset set mismatch')
    verify_hashes(probe_root, validation['probe_files'])
    require(digest(probes_path) == HELPER_SHA and digest(probe_root / 'probe_runner.py') == HELPER_SHA,
            'pinned original probe helper changed')
    auxiliary = plan['auxiliary_sha256']
    require(auxiliary.get(str(Path(__file__).resolve())) == digest(__file__), 'grader was not frozen before generation')
    for relative, expected in validation['probe_files'].items():
        require(auxiliary.get(str((probe_root / relative).resolve())) == expected,
                'probe asset was not frozen before generation: ' + relative)
    for path, expected in auxiliary.items():
        require(Path(path).is_absolute() and digest(path) == expected, 'auxiliary tool changed: ' + path)
    validator = Path(__file__).resolve().with_name('validate_controls.py')
    require(auxiliary.get(str(validator)) == digest(validator) == validation.get('validator_sha256'),
            'control validator was not frozen before generation')
    evidence_paths = [validation_path]
    for task, controls in validation['tasks'].items():
        require(controls.get('valid') is True, 'invalid controls: ' + task)
        for role in ('positive', 'negative'):
            result = controls[role]
            destination = validation_path.parent / task / role
            validate_probe_result(result, task, probe_root / task / (role + '.sv'), destination, probes_path, probe_root)
            evidence_paths.extend(destination / name for name in ('result.json', 'dut.sv', 'tb.sv'))
            evidence_paths.extend(Path(stage['log']) for stage in result['stages'])
        require(controls['positive']['status'] == 'pass'
                and controls['negative']['status'] == 'fail'
                and controls['negative']['failure_kind'] == 'semantic_mismatch',
                'controls must pass positive and reject negative semantically')
    return validation, {str(p): digest(p) for p in evidence_paths}


def validate_generation(run, kit):
    plan, generation = read_json(run / 'plan.json'), read_json(run / 'generation.json')
    require(plan.get('schema') == 'r3-state-repair-pilot-v1' and plan.get('task_ids') == list(TASKS),
            'not the frozen three-task R3 pilot')
    require(generation.get('complete') is True and generation.get('status') == 'generated_ungraded',
            'all 12 generations must complete before any judgement')
    require(plan.get('planned_calls') == 12 and plan.get('repetitions') == 2
            and generation.get('calls_attempted') == 12, 'expected 12 calls and two pairs per task')
    require(plan.get('model') == MODEL and generation.get('served_model_before') == MODEL
            and generation.get('served_model_after') == MODEL,
            'generation used an unexpected model')
    require(generation.get('plan_sha256') == digest(run / 'plan.json'), 'generation plan hash mismatch')
    require(Path(plan['package']).resolve() == (kit / 'submission').resolve(), 'generation package is not this kit')
    require(plan['package_sha256'] == PACKAGE_SHA, 'unexpected baseline/skills pins')
    verify_hashes(kit / 'submission', PACKAGE_SHA)
    require(digest(plan['harness_path']) == plan['harness_sha256'], 'generation harness changed after freeze')
    require(plan.get('per_call_wall_limit_s') == 300 and plan.get('max_output_tokens_per_call') == 8192
            and plan.get('temperature') == 0, 'generation budget changed')
    for name, expected in INPUT_SHA.items():
        require(plan['input_sha256'].get(name) == expected, 'unexpected frozen input: ' + name)
    require(set(plan['input_sha256']) == set(INPUT_SHA) | {'provenance.json'}, 'unexpected input file set')
    verify_hashes(run / 'inputs', plan['input_sha256'])
    require(set(files_under(run / 'inputs')) == set(plan['input_sha256']), 'frozen input file set changed')
    require(len(plan['records']) == len(generation['records']) == 12, 'incomplete or extra generation records')
    require([(r['task_id'], r['pair'], r['arm']) for r in plan['records']] == ORDER, 'paired task/order changed')
    baseline = load_module('r3_frozen_baseline', kit / 'submission/baseline.py')
    paths = [run / 'plan.json', run / 'generation.json']
    paths.extend(run / 'inputs' / name for name in plan['input_sha256'])
    rows = []
    for sequence, (frozen, record) in enumerate(zip(plan['records'], generation['records'])):
        task, pair, arm = ORDER[sequence]
        name = f'{sequence:02d}_{task}_pair{pair}_{arm}'
        require(frozen['sequence'] == sequence and frozen['directory'] == name, 'sample identity mismatch')
        require(all(record.get(k) == v for k, v in frozen.items()), 'generation differs from frozen request')
        require(record.get('error') is None, 'generation has a client failure')
        sample = run / name
        require(read_json(sample / 'generation.json') == record, 'sample receipt differs from aggregate')
        require(digest(sample / 'request.json') == frozen['request_sha256'], 'request hash mismatch: ' + name)
        request = read_json(sample / 'request.json')
        require(request.get('model') == MODEL and request.get('temperature') == 0
                and request.get('top_p') == 1 and request.get('max_tokens') == 8192, 'request parameters changed')
        require(digest(sample / 'solution.v') == record['solution_sha256'], 'solution hash mismatch: ' + name)
        reply = (sample / 'reply.txt').read_text(encoding='utf-8')
        response = read_json(sample / 'response.json')
        require(len(response.get('choices', [])) == 1, 'expected exactly one response choice per call')
        choice = response['choices'][0]
        require((choice['message'].get('content') or '') == reply, 'response/reply mismatch: ' + name)
        solution = (sample / 'solution.v').read_text(encoding='utf-8')
        expected = baseline.extract(reply, 'rtl') if reply else ''
        require(solution == expected and record['empty'] == (not solution.strip()), 'extracted candidate mismatch: ' + name)
        require(record.get('finish_reason') == choice.get('finish_reason') and record.get('usage') == response.get('usage'),
                'generation usage or finish reason differs from response')
        wall = record.get('wall_seconds')
        require(type(wall) in (int, float) and math.isfinite(wall) and wall >= 0, 'invalid generation wall time')
        require(response.get('model') in (None, MODEL), 'response model changed')
        paths.extend(sample / p for p in ('request.json', 'generation.json', 'response.json',
                                         'reply.txt', 'solution.v', 'client.log'))
        rows.append(dict(frozen, generation=record, solution=str(sample / 'solution.v')))
    return plan, rows, {p.relative_to(run).as_posix(): digest(p) for p in paths}


def validate_judge_evidence(verdict, destination, task):
    require(not verdict.get('tool_error'), 'official tool_error; all 12 must be scoreable')
    require(type(verdict.get('level')) is int and verdict['level'] in (0, 1, 2, 3)
            and verdict.get('coefficient') == {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}[verdict['level']],
            'official verdict lacks valid level/coefficient')
    require(verdict.get('task_id') == task and verdict.get('judge_evidence_complete') is True
            and verdict.get('judge_rc') == 0, 'official adapter did not return complete evidence')
    receipt = read_json(destination / 'judge_receipt.json')
    require(receipt.get('judge_rc') == 0 and receipt.get('errors') == [], 'judge receipt has errors')
    require(bool(receipt.get('evidence')), 'empty judge evidence receipt')
    for name, meta in receipt['evidence'].items():
        file = (destination / 'judge_work_logs' / name).resolve()
        require(file.is_relative_to((destination / 'judge_work_logs').resolve()), 'judge evidence escapes root')
        require(file.is_file() and digest(file) == meta['sha256'] and file.stat().st_size == meta['bytes'],
                'judge evidence missing or changed: ' + name)


def summarize(score, samples):
    identities = [(r['task_id'], r['pair'], r['arm']) for r in samples]
    require(len(identities) == 12 and set(identities) == set(ORDER), 'missing, duplicate or extra sample identity')
    tasks, official, pairs = {}, {}, []
    for task in TASKS:
        tasks[task], official[task] = {}, {}
        for arm in ('diagnostic', 'control'):
            rows = sorted([r for r in samples if r['task_id'] == task and r['arm'] == arm], key=lambda r: r['pair'])
            verdicts = [r['verdict'] for r in rows]
            require(all(v.get('task_id') == task for v in verdicts), 'verdict task differs from sample')
            aggregation = score.summarize({task: verdicts})
            official[task][arm] = aggregation
            require(aggregation['tool_errors'] == 0 and aggregation['scored_tasks'] == 1
                    and aggregation['per_task'][0]['scored_samples'] == 2, 'not all 12 planned samples were scored')
            require(all(r['probe']['status'] in ('pass', 'fail') for r in rows), 'probe environment failure invalidates pilot')
            timing = [r['generation']['wall_seconds'] for r in rows]
            tasks[task][arm] = dict(levels=[v['level'] for v in verdicts], coefficient_mean=aggregation['set_score'],
                scored_samples=2, planned_samples=2, probe_statuses=[r['probe']['status'] for r in rows],
                probe_passed=sum(r['probe']['status'] == 'pass' for r in rows),
                empty_answers=sum(r['generation']['empty'] for r in rows),
                truncated=sum(r['generation'].get('finish_reason') == 'length' for r in rows),
                generation_wall_s=dict(values=timing, mean=statistics.mean(timing), min=min(timing), max=max(timing)),
                usage_by_pair=[r['generation'].get('usage') for r in rows])
        for pair in range(2):
            by_arm = {r['arm']: r for r in samples if r['task_id'] == task and r['pair'] == pair}
            pairs.append(dict(task_id=task, pair=pair,
                diagnostic_level=by_arm['diagnostic']['verdict']['level'], control_level=by_arm['control']['verdict']['level'],
                diagnostic_probe=by_arm['diagnostic']['probe']['status'], control_probe=by_arm['control']['probe']['status']))
    d, c = tasks[TARGET]['diagnostic'], tasks[TARGET]['control']
    gates = dict(target_mean_improved=d['coefficient_mean'] > c['coefficient_mean'],
                 both_target_probes_pass=d['probe_passed'] == 2,
                 all_diagnostic_guards_L3=all(tasks[t]['diagnostic']['levels'] == [3, 3] for t in GUARDS))
    # Registered before generation: contradictory external evidence blocks
    # promotion, including conflicts in the control arm. Keep the three
    # original gates unchanged so the reason for stopping stays explicit.
    conflicts = [dict(task_id=r['task_id'], pair=r['pair'], arm=r['arm'],
                      probe_failure_kind=r['probe'].get('failure_kind'))
                 for r in samples if r['verdict']['level'] == 3 and r['probe']['status'] == 'fail']
    decision = ('single_target_positive_signal_expand_not_deploy' if all(gates.values())
                else 'no_promotion_archive_this_implementation')
    if conflicts:
        decision = 'evidence_conflict_review'
    synthesis_review = [dict(task_id=r['task_id'], pair=r['pair'], arm=r['arm'])
                        for r in samples if r['verdict'].get('suspected_silent_degradation')]
    if synthesis_review and not conflicts:
        decision = 'synthesis_evidence_review_no_promotion'
    mechanism_only = d['probe_passed'] > c['probe_passed'] and not gates['target_mean_improved']
    return dict(tasks=tasks, pairs=pairs, gates=gates, decision=decision, evidence_conflicts=conflicts,
        suspected_synthesis_degradation=synthesis_review,
        mechanism_signal_without_score_advantage=mechanism_only, valid_samples=12, planned_samples=12,
        scoring_source='pinned official score.summarize, each task and arm includes both samples',
        limits='One selected target and two development guards, two repetitions per arm. Not independent tasks, statistical significance, full-set gain or the five-sample protocol.'), official


def grade(args):
    sys.dont_write_bytecode = True
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    run, kit, evaluator_path, probes_path, probe_root = [Path(p).resolve() for p in
        (args.run, args.kit, args.evaluator, args.probes, args.probe_root)]
    require(run.is_dir(), 'generation run does not exist')
    output = run / ('grading_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'))
    output.mkdir(exist_ok=False)
    started = time.monotonic()
    report = dict(complete=False, status='preflight', output=str(output), task_ids=list(TASKS),
                  samples=[], errors=[], valid_samples=0, planned_samples=12)
    initial = None
    try:
        slot = Path(args.slot_file)
        slot_bytes = check_slot(slot, args.slot_owner)
        plan, rows, frozen_files = validate_generation(run, kit)
        validation, control_evidence = validate_probe_validation(plan, probes_path, probe_root)
        require(digest(kit / 'official_reference/UPSTREAM.json') == UPSTREAM_SHA, 'official pin manifest changed')
        tasks = {task: kit / 'bench/tasks_veval' / task for task in TASKS}
        for task, path in tasks.items():
            require(read_json(path / 'task.json')['task_id'] == task, 'official task identity mismatch')
            # Observed kit copies omit boundary blank lines. Only universal
            # newlines and boundary LF characters are normalized; internal
            # lines/spaces remain exact. Retain both original byte hashes.
            require((path / 'prompt.txt').read_text(encoding='utf-8').strip('\n') ==
                    (run / 'inputs' / task / 'prompt.txt').read_text(encoding='utf-8').strip('\n'),
                    'official task prompt text differs from frozen prompt')
        require(digest(evaluator_path) == EVALUATOR_SHA, 'pinned official evaluator changed')
        require(plan['auxiliary_sha256'].get(str(evaluator_path)) == EVALUATOR_SHA,
                'official evaluator was not frozen before generation')
        evaluator = load_evaluator(evaluator_path, kit)
        score = load_module('r3_pinned_score', kit / 'official_reference/selftest/score.py')
        probes = load_module('r3_frozen_probes', probes_path)
        probes.ROOT, probes.TASK_CHECKS = probe_root, dict(TASK_CHECKS)
        tools = {name: shutil.which(name) for name in ('xvlog', 'xelab', 'xsim')}
        require(all(tools.values()), 'xvlog, xelab and xsim must be available before judging')
        tool_ids = {name: dict(path=path, sha256=digest(path)) for name, path in tools.items()}
        require(validation.get('tools_unchanged') is True
                and validation.get('tools_before') == validation.get('tools_after') == tool_ids,
                'probe controls were validated with different or unrecorded EDA executables')

        def snapshot():
            return dict(package=files_under(kit / 'submission'), tasks={t: files_under(p) for t, p in tasks.items()},
                official=files_under(kit / 'official_reference'), evaluator_sha256=digest(evaluator_path),
                grader_sha256=digest(__file__), harness_sha256=digest(plan['harness_path']),
                auxiliary={p: digest(p) for p in plan['auxiliary_sha256']},
                probe_validation_sha256=digest(plan['probe_validation']['path']),
                control_evidence_sha256={p: digest(p) for p in control_evidence},
                generation_files={name: digest(run / name) for name in frozen_files},
                tools={name: dict(path=path, sha256=digest(path)) for name, path in tools.items()})

        initial = snapshot()
        require(initial['generation_files'] == frozen_files, 'generation changed during preflight')
        write_json(output / 'before.json', initial)
        shutil.copyfile(__file__, output / 'grader_source.py')
        shutil.copyfile(evaluator_path, output / 'evaluator_source.py')
        report.update(slot_owner=args.slot_owner, slot_sha256=hashlib.sha256(slot_bytes).hexdigest(),
                      upstream_commit=UPSTREAM_COMMIT, status='official_judging',
                      prompt_comparison='exact text after universal-newline decoding and stripping boundary LF only; both original byte hashes retained')

        def unchanged():
            check_slot(slot, args.slot_owner, slot_bytes)
            require(snapshot() == initial, 'frozen package, tasks, official tools, generation or probe files changed')

        for row in rows:
            unchanged()
            destination = output / ('official_' + row['directory'])
            destination.mkdir(exist_ok=False)
            tick = time.monotonic()
            verdict_path = destination / 'verdict.json'
            verdict = evaluator.judge_sample(tasks[row['task_id']], Path(row['solution']), destination,
                                              verdict_path, JUDGE_TIMEOUT_S)
            validate_judge_evidence(verdict, destination, row['task_id'])
            require(read_json(verdict_path) == verdict, 'returned and retained verdict differ')
            report['samples'].append(dict(row, verdict=verdict, official_wall_seconds=time.monotonic() - tick,
                                          official_directory=str(destination)))
            report['valid_samples'] += 1
            write_json(output / 'progress.json', report)
            print(json.dumps(dict(stage='official', sample=row['directory'], level=verdict['level'])), flush=True)

        report['status'] = 'prompt_only_probes'
        for sample in report['samples']:
            unchanged()
            destination = output / ('probe_' + sample['directory'])
            tick = time.monotonic()
            sample['probe'] = probes.probe_candidate(sample['task_id'], sample['solution'], destination)
            validate_probe_result(sample['probe'], sample['task_id'], sample['solution'], destination, probes_path, probe_root)
            sample['probe_wall_seconds'] = time.monotonic() - tick
            write_json(output / 'progress.json', report)
            print(json.dumps(dict(stage='probe', sample=sample['directory'], status=sample['probe']['status'])), flush=True)
        unchanged()
        analysis, official = summarize(score, report['samples'])
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
    parser.add_argument('--probes', required=True, help='unchanged pinned bottom-level probe_runner.py')
    parser.add_argument('--probe-root', required=True, help='frozen root containing probe_runner.py and the three task directories')
    parser.add_argument('--slot-owner', required=True)
    parser.add_argument('--slot-file', default='/workspace/team/SLOT.lock')
    return grade(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
