"""Once-only synthetic checks on AMD: no real model POST and nine native tools."""
import argparse
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import types
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
KIT = Path('/workspace/team/tasks/autodl-rtl-kit/project')
MODEL = 'SIMULATED_NO_MODEL'
HEADER = ('I would like you to implement a module named TopModule with the following\n'
          'interface. All input and output ports are one bit unless otherwise specified.\n'
          '- input a\n- input b\n- output y\n\n')
PROMPT = HEADER + ('The module should implement the Karnaugh map below.\n'
                   'b\na 0 1\n0 | 0 | 1 |\n1 | 1 | 0 |\n')
GOOD = 'module TopModule(input a, input b, output y); assign y=a^b; endmodule\n'
BAD = GOOD.replace('a^b', 'a&b')
UNKNOWN = GOOD.replace('a^b', "1'bx")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen():
    for rel, digest in json.loads((ROOT / 'SOURCE_MANIFEST.json').read_text()).items():
        assert sha(ROOT / rel) == digest, rel


def rejects(call, error=ValueError):
    try:
        call()
    except error:
        return
    raise AssertionError('expected rejection')


def pure(feedback):
    parsed = feedback.parse(PROMPT)
    assert parsed['checks'] == 8
    assert [r['expected'] for r in parsed['table']['rows']] == [0, 1, 1, 0]
    tb = feedback.render_tb(parsed, 'synthetic')
    assert 'module TopModule' not in tb and 'TopModule _tf_dut' in tb
    assert tb.count('_tf_checks=_tf_checks+1;') == 8
    point = feedback.counterexample('TABLE_FIRST row=1 expected=1 observed=0\n', parsed)
    assert point == dict(inputs={'a': 0, 'b': 1}, output='y', expected=1, observed='0')
    for log in ('', 'TABLE_FIRST row=1 expected=0 observed=1\n',
                'TABLE_FIRST row=9 expected=1 observed=0\n',
                'TABLE_FIRST row=1 expected=1 observed=1\n',
                'TABLE_FIRST row=1 expected=1 observed=0\n' * 2):
        rejects(lambda: feedback.counterexample(log, parsed))
    for prompt in (PROMPT + 'Also register the output.\n', PROMPT.replace('1 | 1 | 0 |\n', ''),
                   PROMPT.replace('- input a', '- input always').replace('\na 0 1', '\nalways 0 1'),
                   PROMPT.replace('- input a', '- input clk').replace('\na 0 1', '\nclk 0 1')):
        assert feedback.parse(prompt) is None
    wave = HEADER + ('The module should implement a combinational circuit. Read the simulation\n'
                     'waveforms to determine what the circuit does, then implement it.\n'
                     'time a b y\n0ns 0 0 0\n1ns 0 1 1\n2ns 1 0 1\n3ns 1 1 0\n')
    assert feedback.parse(wave)['checks'] == 8
    assert feedback.parse(wave.replace(wave[len(HEADER):wave.index('time')],
                                      'The module can be described by the following simulation waveform:\n')) is None
    dc = PROMPT.replace('below.', "below. d is don't-care, which means you may choose to output whatever value is convenient.")
    dc = dc.replace('0 | 0 | 1 |', '0 | d | 1 |')
    assert feedback.parse(dc)['checks'] == 6
    assert 'row=0 expected=' not in feedback.render_tb(feedback.parse(dc), 'synthetic')
    rejects(lambda: feedback.counterexample('TABLE_FIRST row=0 expected=0 observed=1\n', feedback.parse(dc)))
    # User ports that look like checker internals do not collide with local wires.
    collision = PROMPT.replace('- output y', '- output _tf_checks')
    assert '._tf_checks(_tf_o)' in feedback.render_tb(feedback.parse(collision), 'synthetic')
    return dict(passed=True, categories=['complete_table', 'feedback_binding', 'abstention',
                                       'explicit_combinational_only', 'dontcare', 'identifier_isolation'])


def flow(feedback, name, arm, replies, oracle_mode='normal', prompt=PROMPT):
    base = load('table_control_' + name, ROOT / 'baseline_worker.py')
    args = types.SimpleNamespace(task='synthetic', arm=arm, kit=ROOT / 'synthetic_kit',
                                 out=ROOT / 'results/flow' / name, resource_check=ROOT / 'UNUSED')
    source = args.kit / 'bench/tasks_veval/synthetic'
    source.mkdir(parents=True, exist_ok=True)
    (source / 'prompt.txt').write_text(prompt)
    calls = dict(http=[], oracle=[], compile=[])
    previous = (Path.cwd(), urllib.request.urlopen, subprocess.run, base.functional_feedback)
    original_load = base.load

    def runtime_load(label, path):
        runtime = original_load(label, path)
        runtime.vivado_tool = lambda tool: '/FAKE/' + tool
        return runtime

    def transport(request, **kwargs):
        assert request.full_url == 'http://127.0.0.1:8000/v1/chat/completions'
        assert request.get_method() == 'POST' and kwargs == dict(timeout=300)
        index = len(calls['http'])
        assert index < len(replies) <= 2
        body = json.loads(request.data)
        assert body['model'] == MODEL and body['max_tokens'] == 8192
        assert body['temperature'] == 0 and body['top_p'] == 1
        expected = prompt
        if index:
            expected += ('\nPrevious candidate:\n' + replies[index - 1] + '\nCandidate diagnostics:\n' +
                         (args.out / 'table_check_0/feedback.txt').read_text())
        assert body['messages'][1]['content'] == expected
        calls['http'].append(body)
        return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content=replies[index]),
                                                       finish_reason='stop')], usage={})).encode())

    def compile_owned(argv, cwd, log, cap):
        assert argv[0] == '/FAKE/xvlog' and cap == 60
        Path(log).write_text('FAKE compiler success\n')
        calls['compile'].append(sha(argv[-1]))
        return dict(returncode=0, timeout=False, launch_error=None, remaining_live_group=[])

    def oracle(task, source, out):
        code = Path(source).read_text()
        assert code in replies and task['checks'] == 8
        Path(out).mkdir()
        mismatch = code != GOOD
        (out / 'xsim.log').write_text('TABLE_FIRST row=1 expected=1 observed=0\n' if mismatch else '')
        calls['oracle'].append(dict(code_sha256=sha(source), mode=oracle_mode))
        if oracle_mode == 'error':
            return dict(status='environment_error', inputs_unchanged=True, checks=None)
        if oracle_mode == 'mutation':
            Path(source).write_text('changed')
        return dict(status='fail' if mismatch else 'pass', inputs_unchanged=True, checks=8,
                    failure_kind='semantic_mismatch' if mismatch else None, mismatches=4 if mismatch else 0)

    paired = types.SimpleNamespace(save=save, sha=sha, oracle=oracle, owned_command=compile_owned,
                                   check_resource=lambda *a: None, model_idle=lambda *a: None)
    def unexpected(*a, **k):
        raise AssertionError('unexpected real subprocess')
    error = None
    with patch.dict(os.environ, dict(MODEL_NAME=MODEL, RTL_REPAIRS='1', RTL_MAX_TOKENS='8192',
                                    RTL_TEMPERATURE='0', LLM_BASE_URL='http://127.0.0.1:8000/v1')), \
         patch.object(base, 'load', runtime_load), patch.object(urllib.request, 'urlopen', transport), \
         patch.object(subprocess, 'run', unexpected), \
         patch.dict(sys.modules, {'activity': types.SimpleNamespace(append=lambda *a, **k: None)}):
        try:
            feedback.run_worker(base, args, paired)
        except RuntimeError as exc:
            error = str(exc)
    assert (Path.cwd(), urllib.request.urlopen, subprocess.run, base.functional_feedback) == previous
    assert len(calls['http']) == len(replies)
    assert (error is not None) == (oracle_mode != 'normal'), error
    assert (args.out / 'solution.v').read_text() == replies[-1]
    assert len(calls['oracle']) == (0 if arm == 'C' or prompt != PROMPT else len(replies))
    report = dict(passed=True, simulated=True, real_model_calls=0, real_eda_calls=0,
                  expected_failure=error, calls=calls)
    save(args.out / 'CONTROL_RESULT.json', report)
    return report


def stage(resource):
    frozen()
    save(ROOT / 'STAGE_INTENT.json', dict(source_manifest_sha256=sha(ROOT / 'SOURCE_MANIFEST.json'),
                                        real_model_max=0, real_eda_max=9, implicit_retries=0))
    (ROOT / 'results').mkdir()
    reports = {}; failure = None; native_commands = []
    try:
        import table_feedback as feedback
        import bounded_owned_exec
        paired = load('table_control_paired', ROOT / 'dependencies/paired_checkpoint.py')
        paired.check_resource(resource, KIT, first=True)
        reports['pure'] = pure(feedback)
        reports['flow'] = {}
        for name, arm, replies, mode, prompt in [
                ('control_unchanged', 'C', [BAD], 'normal', PROMPT),
                ('candidate_pass', 'P', [GOOD], 'normal', PROMPT),
                ('candidate_repair', 'P', [BAD, GOOD], 'normal', PROMPT),
                ('candidate_exhausted', 'P', [BAD, BAD], 'normal', PROMPT),
                ('candidate_abstain', 'P', [GOOD], 'normal', 'Return a self-contained combinational TopModule.'),
                ('tool_error', 'P', [BAD], 'error', PROMPT),
                ('input_mutation', 'P', [BAD], 'mutation', PROMPT)]:
            reports['flow'][name] = flow(feedback, name, arm, replies, mode, prompt)
        assert reports['flow']['control_unchanged']['calls']['http'][0] == reports['flow']['candidate_repair']['calls']['http'][0]
        paired.REPO = ROOT
        paired.INHERITED_ORACLE = ROOT / 'dependencies/probe_runner.py'

        def owned(argv, cwd, log, cap):
            frozen()
            paired.check_resource(resource, KIT)
            assert len(native_commands) < 9 and cap == 60
            assert Path(argv[0]).name in ('xvlog', 'xelab', 'xsim')
            rec = bounded_owned_exec.run(argv, cwd, ROOT / 'native_processes' / str(len(native_commands)), cap)
            Path(log).write_bytes((ROOT / 'native_processes' / str(len(native_commands)) / 'stdout.bin').read_bytes())
            native_commands.append(rec)
            save(ROOT / ('NATIVE_COMMAND_' + str(len(native_commands)) + '.json'), rec)
            assert rec['normal_completion'] and rec['exec_confirmed'] and rec['leader_reaped']
            assert not rec['timeout'] and not rec['exec_error'] and not rec['error'] and not rec['remaining_group']
            return dict(returncode=rec['returncode'], timeout=rec['timeout'], launch_error=rec['exec_error'],
                        remaining_live_group=rec['remaining_group'], log=str(log), log_sha256=sha(log),
                        elapsed_s=rec['elapsed_s'])
        paired.owned_command = owned
        reports['native'] = {}
        (ROOT / 'native_processes').mkdir()
        for name, code in [('positive', GOOD), ('semantic_negative', BAD), ('unknown_output', UNKNOWN)]:
            text = feedback.check(PROMPT, code, ROOT / 'results/native' / name, 0, paired, 'synthetic', ROOT)
            assert (text == '') == (name == 'positive')
            if name == 'unknown_output':
                assert 'observed y=x' in text
            reports['native'][name] = dict(passed=True, feedback=text)
        assert len(native_commands) == 9
        frozen()
        paired.check_resource(resource, KIT)
    except BaseException as exc:
        failure = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    summary = dict(complete=True, passed=failure is None, error=failure, reports=reports,
                   real_model_calls=0, real_eda_calls=len(native_commands), native_processes=native_commands,
                   scoring_run=False, accuracy_measured=False)
    save(ROOT / 'results/summary.json', summary)
    print(json.dumps(dict(passed=failure is None, real_eda_calls=len(native_commands), error=failure)))
    return 0 if failure is None else 1


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('stage', 'observe'))
    parser.add_argument('--resource-check', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'stage':
        sys.exit(stage(args.resource_check))
    frozen()
    save(ROOT / 'OBSERVE_INTENT.json', dict(cap_s=430, cleanup_reserve_s=30))
    import terminal_outer
    result = terminal_outer.run([sys.executable, '-B', str(ROOT / 'controls.py'), 'stage',
                                 '--resource-check', str(args.resource_check)], ROOT, ROOT / 'external',
                                430, 30, [ROOT / 'results/summary.json'], 2013333)
    print(json.dumps(dict(passed=result['passed'], elapsed_s=result['measured_complete_elapsed_s'], error=result['error'])))
    sys.exit(0 if result['passed'] else 1)
