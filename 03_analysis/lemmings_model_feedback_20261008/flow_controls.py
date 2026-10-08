"""AMD-only Lemmings adaptation of the already-qualified serial 3-flow harness.

All HTTP, compile and functional-oracle observations in this file are explicitly
SIMULATED. This verifies integration, never candidate correctness or score gain.
The actual worker/runtime/skills/extractor execute unchanged under those stubs.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import urllib.request
from unittest.mock import patch

import lemmings_feedback as feedback

HERE = Path(__file__).resolve().parent
CHECKER_SHA256 = 'e178d62a61bd279bb3dfcf4a17357a90e8a26b4537da83ba0f6e3714ae0a753a'
WORKER_SHA256 = {
    '7ff7ed6e397caedee071a7f46015d81370c92f2579bd61dd2cc3337458467742': 'original_serial130_worker',
    'a4d212f06d16079d45cb79eb2843e7163cf8745d211706c4534e534a84b7fb66': 'peer129_same_worker_with_three_prequalified_path_routes',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(name):
    text = (HERE / 'flow_fixtures' / name).read_text(encoding='utf-8')
    # Untouched official extractor returns only the first TopModule. These
    # purpose-specific single-module fixtures contain no helper modules.
    return text[text.index('module TopModule'):].strip() + '\n'


def _simulated_native_log(parsed, bad_event):
    lines = ['SIMULATED_FLOW_ORACLE_NOT_NATIVE_NOT_MODEL_EVIDENCE']
    for row in parsed['rows']:
        outputs = '0100' if row['event'] == bad_event else row['expected']
        lines.append(f"LEMMINGS_STEP event={row['event']} kind={row['kind']} clock={row['clock']} "
                     f"reset={row['reset']} left={row['bump_left']} right={row['bump_right']} "
                     f"ground={row['ground']} dig={row['dig']} outputs={outputs}")
        if row['event'] == bad_event:
            lines.append(f'LEMMINGS_FIRST event={bad_event}')
    lines.append(f'R2_PROBE_RESULT task=SyntheticLemmings checks={parsed["checks"]} mismatches={int(bad_event is not None)}')
    return '\n'.join(lines) + '\n'


def flow(root, out, baseline_worker, name, arm, prompt, replies, expect_fallback):
    """Reuse the original worker and serial transport pattern; no live tools."""
    if sys.platform != 'linux' or not sys.dont_write_bytecode:
        raise RuntimeError('AMD-only controls require Python -B')
    root, out, baseline_worker = Path(root).resolve(), Path(out).resolve(), Path(baseline_worker).resolve()
    out.relative_to(root)
    if sha(baseline_worker) not in WORKER_SHA256:
        raise RuntimeError('unreviewed worker revision')
    if sha(feedback.__file__) != CHECKER_SHA256:
        raise RuntimeError('checker is not this control draft\'s frozen revision')
    base = load('lemmings_flow_' + name, baseline_worker)
    if base.ROOT.resolve() != root:
        raise ValueError('worker and checker must use the same frozen packet root')
    spec = json.loads((root / 'RUN_SPEC.json').read_text())
    args = types.SimpleNamespace(task='SyntheticLemmings', arm=arm, kit=out / 'synthetic_kit' / name,
                                 out=out / 'flow' / name, resource_check=out / 'UNUSED')
    source = args.kit / 'bench/tasks_veval' / args.task
    source.mkdir(parents=True, exist_ok=False)
    (source / 'prompt.txt').write_text(prompt, encoding='utf-8', newline='\n')
    calls = dict(http=[], oracle=[], compile=[], original_feedback=[], simulated_activity=[])
    previous = (Path.cwd(), urllib.request.urlopen, subprocess.run, subprocess.Popen, base.functional_feedback)
    original_load, original_feedback = base.load, base.functional_feedback
    loaded = []

    def runtime_load(label, path):
        runtime = original_load(label, path)
        runtime.vivado_tool = lambda tool: '/FAKE/' + tool
        skill, repair = runtime.skill_texts()
        loaded.append(dict(module=runtime, path=Path(path), sha256=sha(path),
                           generation_skill=skill, repair_skill=repair))
        return runtime

    def tracked_original(prompt_text, code, target, attempt, tools, task, candidate=False):
        calls['original_feedback'].append(dict(prompt_sha256=hashlib.sha256(prompt_text.encode()).hexdigest(),
                                               attempt=attempt, candidate=candidate, task=task))
        # Record, then call the actual original function without changing result.
        return original_feedback(prompt_text, code, target, attempt, tools, task, candidate=candidate)

    def transport(request, **kwargs):
        assert request.full_url == 'http://127.0.0.1:8000/v1/chat/completions'
        assert request.get_method() == 'POST' and kwargs == dict(timeout=300)
        index = len(calls['http'])
        assert index < len(replies) <= 2 and len(loaded) == 1
        body = json.loads(request.data)
        assert body['model'] == spec['model'] and body['max_tokens'] == 8192
        assert body['temperature'] == 0 and body['top_p'] == 1
        expected_system = loaded[0]['generation_skill']
        if index:
            expected_system += '\n' + loaded[0]['repair_skill']
        assert body['messages'][0] == dict(role='system', content=expected_system)
        expected = prompt
        if index:
            actual_feedback = (args.out / 'lemmings_check_0/feedback.txt').read_text(encoding='utf-8')
            expected += ('\nPrevious candidate:\n' + replies[index - 1] +
                         '\nCandidate diagnostics:\n' + actual_feedback)
        assert body['messages'][1] == dict(role='user', content=expected)
        assert len(body['messages']) == 2
        calls['http'].append(dict(body=body, timeout=kwargs['timeout'], simulated=True))
        return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content=replies[index]),
                                                       finish_reason='stop')], usage={})).encode())

    def compile_owned(argv, cwd, log, cap):
        assert argv[0] == '/FAKE/xvlog' and cap == 60
        Path(log).write_text('SIMULATED_FLOW compiler success; no EDA was executed\n', encoding='utf-8')
        calls['compile'].append(dict(source_sha256=sha(argv[-1]), cap_seconds=cap, simulated=True))
        return dict(returncode=0, timeout=False, launch_error=None, remaining_live_group=[])

    def oracle(task, candidate_source, dest):
        code = Path(candidate_source).read_text(encoding='utf-8')
        assert code in replies and arm == 'P'
        parsed = feedback.parse(prompt)
        assert parsed is not None and task['checks'] == parsed['checks']
        dest = Path(dest)
        dest.mkdir()
        mismatch = code == fixture('bad_right_double_bump.sv')
        assert mismatch or code == fixture('good_entry1.sv')
        bad_event = next(row['event'] for row in parsed['rows']
                         if row['tag'] == 'walking_bump' and row['bump_left'] == row['bump_right'] == 1
                         and row['expected'] == '1000') if mismatch else None
        stages = []
        for stage_name in ('xvlog', 'xelab', 'xsim'):
            stage_log = dest / (stage_name + '.log')
            stage_log.write_text(_simulated_native_log(parsed, bad_event) if stage_name == 'xsim' else
                                 'SIMULATED_FLOW native stage success; not actual EDA\n',
                                 encoding='utf-8', newline='\n')
            stages.append(dict(name=stage_name, returncode=0, timeout=False, launch_error=None,
                               remaining_live_group=[], log=str(stage_log), log_sha256=sha(stage_log),
                               log_bytes=stage_log.stat().st_size, simulated=True))
        result = dict(status='fail' if mismatch else 'pass', inputs_unchanged=True, checks=parsed['checks'],
                      failure_kind='semantic_mismatch' if mismatch else None,
                      mismatches=int(mismatch), stages=stages, solution_sha256=sha(candidate_source),
                      tb_sha256=sha(root / task['tb']), simulated=True,
                      evidence_class='synthetic_worker_flow_only_not_native')
        save(dest / 'result.json', result)
        result.update(inherited_result_path=str(dest / 'result.json'), inherited_result_sha256=sha(dest / 'result.json'))
        save(dest / 'adapter_receipt.json', result)
        calls['oracle'].append(dict(code_sha256=sha(candidate_source), bad_event=bad_event,
                                    simulated=True, result_sha256=sha(dest / 'result.json')))
        return result

    paired = types.SimpleNamespace(save=save, sha=sha, oracle=oracle, owned_command=compile_owned,
                                   check_resource=lambda *a: None, model_idle=lambda *a: None)

    def unexpected(*args, **kwargs):
        raise AssertionError('real subprocess/network activity is forbidden in simulated flow controls')

    def simulated_activity(*args, **kwargs):
        calls['simulated_activity'].append(dict(args=[str(x) for x in args], kwargs=kwargs, simulated=True))

    # PAIRED_TASK_DIR is ignored by the original worker and used only by the
    # already-reviewed peer route adapter; both point at the same synthetic task.
    with patch.dict(os.environ, dict(MODEL_NAME=spec['model'], RTL_REPAIRS='1', RTL_MAX_TOKENS='8192',
                                    RTL_TEMPERATURE='0', LLM_BASE_URL='http://127.0.0.1:8000/v1',
                                    PAIRED_TASK_DIR=str(source))), \
         patch.object(base, 'load', runtime_load), patch.object(base, 'functional_feedback', tracked_original), \
         patch.object(urllib.request, 'urlopen', transport), patch.object(subprocess, 'run', unexpected), \
         patch.object(subprocess, 'Popen', unexpected), \
         patch.dict(sys.modules, {'activity': types.SimpleNamespace(append=simulated_activity)}):
        feedback.run_worker(base, args, paired)
        assert base.functional_feedback is tracked_original
    assert (Path.cwd(), urllib.request.urlopen, subprocess.run, subprocess.Popen, base.functional_feedback) == previous
    assert len(calls['http']) == len(replies)
    assert (args.out / 'solution.v').read_text(encoding='utf-8') == replies[-1]
    assert len(calls['compile']) == len(replies)
    assert len(calls['original_feedback']) == expect_fallback
    expected_oracles = len(replies) if name == 'candidate_repairs_once' else 0
    assert len(calls['oracle']) == expected_oracles
    result = json.loads((args.out / 'worker_result.json').read_text())
    # Original worker field names are retained; these counts describe simulated
    # logical requests in this harness, not real service/model invocations.
    assert result['requests'] == result['actual_model_requests'] == len(replies)
    events = [json.loads(line) for line in (args.out / 'trace.jsonl').read_text().splitlines()]
    metadata = [event for event in events if event['tool'] == 'agent_meta']
    assert len(metadata) == 1 and metadata[0]['repairs'] == 1
    assert metadata[0]['skill_sha256'] == hashlib.sha256(loaded[0]['generation_skill'].encode()).hexdigest()
    assert metadata[0]['repair_skill_sha256'] == hashlib.sha256(loaded[0]['repair_skill'].encode()).hexdigest()
    mapping = [event for event in events if event['tool'] == 'map_feedback']
    if expected_oracles:
        text = (args.out / 'lemmings_check_0/feedback.txt').read_text(encoding='utf-8')
        assert len(mapping) == 1 and mapping[0]['round'] == 0 and mapping[0]['excerpt'] == text
        assert mapping[0]['repair_available'] is True
    else:
        assert not mapping and not list(args.out.glob('lemmings_check_*'))
    assert sha(baseline_worker) in WORKER_SHA256 and sha(loaded[0]['path']) == loaded[0]['sha256']
    summary = dict(passed=True, simulated=True, real_model_calls=0, real_eda_calls=0,
                   original_worker_sha256=sha(baseline_worker), checker_sha256=sha(feedback.__file__),
                   runtime_sha256=loaded[0]['sha256'], hook_restored=True, calls=calls,
                   source_sha256=sha(args.out / 'solution.v'), original_budget=dict(
                       max_tokens=8192, max_requests=2, repairs=1, transport_timeout_seconds=300,
                       compile_cap_seconds=60, external_solve_300='unchanged_but_not_exercised_by_this_direct_flow'))
    save(args.out / 'CONTROL_RESULT.json', summary)
    return summary


def run_all(root, out, baseline_worker):
    if sys.platform != 'linux' or not sys.dont_write_bytecode:
        raise RuntimeError('AMD-only controls require Python -B')
    root, out = Path(root).resolve(), Path(out).resolve()
    out.relative_to(root)
    out.mkdir(parents=True, exist_ok=False)
    prompt = (Path(feedback.__file__).resolve().parent / 'prompts/death.txt').read_text(encoding='utf-8')
    good, bad = fixture('good_entry1.sv'), fixture('bad_right_double_bump.sv')
    reports = {}
    for name, arm, text, replies, fallback in (
            ('control_unchanged', 'C', prompt, [bad], 1),
            ('candidate_abstains', 'P', 'Return a self-contained TopModule.', [good], 1),
            ('candidate_repairs_once', 'P', prompt, [bad, good], 0)):
        reports[name] = flow(root, out, baseline_worker, name, arm, text, replies, fallback)
    first_c = reports['control_unchanged']['calls']['http'][0]['body']
    first_p = reports['candidate_repairs_once']['calls']['http'][0]['body']
    assert first_c == first_p
    summary = dict(complete=True, passed=True, simulated=True, reports=reports,
                   simulated_http_calls=4, simulated_compiles=4, simulated_oracles=2,
                   actual_model_calls=0, actual_eda_calls=0, score_measured=False,
                   first_C_P_request_identical=True)
    save(out / 'FLOW_RESULT.json', summary)
    return summary
