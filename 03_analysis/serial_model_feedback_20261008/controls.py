"""AMD-only checker controls, using existing worker/oracle; no scheduling here."""
import argparse
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
import time
import unittest
import urllib.request
from unittest.mock import patch

import serial_feedback as feedback
import test_serial_feedback as pure_tests

HERE = Path(__file__).resolve().parent


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


def fixture(name):
    text = (HERE / 'fixtures' / name).read_text(encoding='utf-8')
    return text[text.index('module TopModule'):].strip() + '\n'


def flow(root, out, baseline_worker, name, arm, prompt, replies):
    """PR179's existing simulated transport pattern, with original worker loop."""
    base = load('serial_control_' + name, baseline_worker)
    if base.ROOT.resolve() != root:
        raise ValueError('baseline worker and check root must be the same frozen packet')
    spec = json.loads((root / 'RUN_SPEC.json').read_text())
    args = types.SimpleNamespace(task='SyntheticSerial', arm=arm, kit=out / 'synthetic_kit' / name,
                                 out=out / 'flow' / name, resource_check=out / 'UNUSED')
    source = args.kit / 'bench/tasks_veval' / args.task
    source.mkdir(parents=True, exist_ok=False)
    (source / 'prompt.txt').write_text(prompt, encoding='utf-8')
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
        assert body['model'] == spec['model'] and body['max_tokens'] == 8192
        assert body['temperature'] == 0 and body['top_p'] == 1
        expected = prompt
        if index:
            expected += ('\nPrevious candidate:\n' + replies[index - 1] + '\nCandidate diagnostics:\n' +
                         (args.out / 'serial_check_0/feedback.txt').read_text())
        assert body['messages'][1]['content'] == expected
        calls['http'].append(body)
        return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content=replies[index]),
                                                       finish_reason='stop')], usage={})).encode())

    def compile_owned(argv, cwd, log, cap):
        assert argv[0] == '/FAKE/xvlog' and cap == 60
        Path(log).write_text('SIMULATED compiler success\n')
        calls['compile'].append(sha(argv[-1]))
        return dict(returncode=0, timeout=False, launch_error=None, remaining_live_group=[])

    def oracle(task, source, dest):
        code = Path(source).read_text()
        assert code in replies
        parsed = feedback.parse(prompt)
        assert task['checks'] == parsed['checks'] == 69
        Path(dest).mkdir()
        mismatch = code != fixture('positive.sv')
        log = pure_tests.simulated_log(parsed, 40, bad_done='1') if mismatch else pure_tests.simulated_log(parsed)
        (dest / 'xsim.log').write_text(log)
        calls['oracle'].append(dict(code_sha256=sha(source), simulated=True))
        return dict(status='fail' if mismatch else 'pass', inputs_unchanged=True, checks=69,
                    failure_kind='semantic_mismatch' if mismatch else None, mismatches=1 if mismatch else 0)

    paired = types.SimpleNamespace(save=save, sha=sha, oracle=oracle, owned_command=compile_owned,
                                   check_resource=lambda *a: None, model_idle=lambda *a: None)

    def unexpected(*a, **k):
        raise AssertionError('unexpected real subprocess in simulated worker check')

    with patch.dict(os.environ, dict(MODEL_NAME=spec['model'], RTL_REPAIRS='1', RTL_MAX_TOKENS='8192',
                                    RTL_TEMPERATURE='0', LLM_BASE_URL='http://127.0.0.1:8000/v1')), \
         patch.object(base, 'load', runtime_load), patch.object(urllib.request, 'urlopen', transport), \
         patch.object(subprocess, 'run', unexpected), \
         patch.dict(sys.modules, {'activity': types.SimpleNamespace(append=lambda *a, **k: None)}):
        feedback.run_worker(base, args, paired)
    assert (Path.cwd(), urllib.request.urlopen, subprocess.run, base.functional_feedback) == previous
    assert len(calls['http']) == len(replies)
    assert (args.out / 'solution.v').read_text() == replies[-1]
    expected_oracles = len(replies) if arm == 'P' and prompt == pure_tests.prompt() else 0
    assert len(calls['oracle']) == expected_oracles
    result = dict(passed=True, simulated=True, real_model_calls=0, real_eda_calls=0, calls=calls,
                  original_worker_sha256=sha(baseline_worker), hook_restored=True)
    save(args.out / 'CONTROL_RESULT.json', result)
    return result


def stage(args):
    started = time.monotonic()
    root, out = args.root.resolve(), args.out.resolve()
    out.relative_to(root)
    if out == root:
        raise ValueError('use a separate results directory beneath the packet root')
    out.mkdir(parents=True, exist_ok=False)
    reports, commands, failure = {}, [], None
    assert root == HERE and 0 < args.stage_cap_s == 900
    assert sha(root / 'SOURCE_MANIFEST.json') == args.manifest_sha256
    source_hashes = json.loads((root / 'SOURCE_MANIFEST.json').read_text())
    def frozen():
        assert sha(root / 'SOURCE_MANIFEST.json') == args.manifest_sha256
        assert all(sha(root / name) == digest for name, digest in source_hashes.items())
    frozen()
    save(out / 'CONTROL_INTENT.json', dict(real_model_max=0, real_eda_max=12, simulated_http_max=4,
                                          source_hashes=source_hashes, retries=0,
                                          paired_sha256=sha(args.paired), oracle_sha256=sha(args.oracle)))
    paired = load('serial_native_paired', args.paired)
    paired.REPO, paired.INHERITED_ORACLE = root, args.oracle.resolve()
    original_owned = paired.owned_command
    import bounded_owned_exec
    (out / 'native_processes').mkdir()

    def owned(argv, cwd, log, cap):
        frozen()
        paired.check_resource(args.resource_check, args.kit)
        assert len(commands) < 12 and cap == 60
        assert time.monotonic() - started + cap + 30 < args.stage_cap_s
        assert Path(argv[0]).name in ('xvlog', 'xelab', 'xsim')
        rec = dict(index=len(commands), argv=[str(x) for x in argv], cap_s=cap)
        commands.append(rec)
        try:
            prefix = out / 'native_processes' / str(rec['index'])
            bounded = bounded_owned_exec.run(argv, cwd, prefix, cap)
            rec['bounded_receipt'] = bounded
            rec['bounded_receipt_path'] = str(prefix / 'COMPLETE.json')
            rec['bounded_receipt_sha256'] = sha(prefix / 'COMPLETE.json')
            Path(log).write_bytes((prefix / 'stdout.bin').read_bytes())
            assert bounded['normal_completion'] and bounded['exec_confirmed'] and bounded['leader_reaped']
            assert not bounded['timeout'] and not bounded['exec_error'] and not bounded['error'] and not bounded['remaining_group']
            result = dict(returncode=bounded['returncode'], timeout=bounded['timeout'],
                          launch_error=bounded['exec_error'], remaining_live_group=bounded['remaining_group'],
                          log=str(log), log_sha256=sha(log), elapsed_s=bounded['elapsed_s'])
            rec['legacy_adapter_result'] = result
            return result
        except BaseException as exc:
            rec['error'] = dict(type=type(exc).__name__, message=str(exc))
            raise
        finally:
            save(out / f'NATIVE_COMMAND_{rec["index"]}.json', rec)

    def no_network(*a, **k):
        raise AssertionError('native controls must make zero real HTTP/model calls')

    paired.owned_command = owned
    try:
        paired.check_resource(args.resource_check, args.kit, first=True)
        with patch.object(urllib.request, 'urlopen', no_network):
            stream = io.StringIO()
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(pure_tests.SerialFeedbackTests)
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
            (out / 'pure_tests.log').write_text(stream.getvalue(), encoding='utf-8')
            reports['pure'] = dict(tests=result.testsRun, passed=result.wasSuccessful())
            assert result.testsRun == 8 and result.wasSuccessful()
            good, bad = fixture('positive.sv'), fixture('late_stop_mutant.sv')
            reports['flow'] = {}
            for name, arm, prompt, replies in (
                    ('control_unchanged', 'C', pure_tests.prompt(), [bad]),
                    ('candidate_abstains', 'P', 'Return a self-contained TopModule.', [good]),
                    ('candidate_repairs_once', 'P', pure_tests.prompt(), [bad, good])):
                reports['flow'][name] = flow(root, out, args.baseline_worker, name, arm, prompt, replies)
            a = reports['flow']['control_unchanged']['calls']['http'][0]
            b = reports['flow']['candidate_repairs_once']['calls']['http'][0]
            assert a == b
            reports['native'] = {}
            for name, expected_cycle in (('positive', None), ('late_stop_mutant', 40),
                                         ('reversed_data_mutant', 18), ('unknown_done_mutant', 0)):
                target = out / 'native' / name
                text = feedback.check(pure_tests.prompt(), fixture(name + '.sv'), target,
                                      0, paired, 'SyntheticSerial', root)
                probe = target / 'serial_check_0/probe'
                receipt = probe / 'adapter_receipt.json'
                assert receipt.is_file()
                actual = json.loads(receipt.read_text())
                assert actual['checks'] == 69 and actual['inputs_unchanged'] is True
                if expected_cycle is None:
                    assert text == '' and actual['status'] == 'pass' and actual['mismatches'] == 0
                else:
                    point = json.loads((target / 'serial_check_0/counterexample.json').read_text())
                    assert point['cycle'] == expected_cycle and text == feedback.feedback_text(point)
                    if name == 'late_stop_mutant':
                        assert point['expected_done'] == 0 and point['observed_done'] == '1'
                    elif name == 'reversed_data_mutant':
                        assert point['expected_data'] == 1 and point['observed_data'] == '100'
                    else:
                        assert point['observed_done'] == 'x'
                reports['native'][name] = dict(passed=True, feedback=text,
                                              oracle_receipt=str(receipt), oracle_receipt_sha256=sha(receipt),
                                              result=actual)
            assert len(commands) == 12
            frozen()
            paired.check_resource(args.resource_check, args.kit)
            assert time.monotonic() - started < args.stage_cap_s
    except BaseException as exc:
        failure = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    finally:
        paired.owned_command = original_owned
    summary = dict(complete=True, passed=failure is None, reports=reports, error=failure,
                   real_model_calls=0, real_eda_commands=len(commands), native_commands=commands,
                   simulated_http_calls=sum(len(x['calls']['http']) for x in reports.get('flow', {}).values()),
                   elapsed_s=time.monotonic()-started, stage_cap_s=args.stage_cap_s,
                   source_manifest_sha256=args.manifest_sha256,
                   scoring_run=False, accuracy_measured=False)
    save(out / 'CONTROL_RESULT.json', summary)
    print(json.dumps(dict(passed=summary['passed'], real_eda_commands=len(commands), error=failure)))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    parser = argparse.ArgumentParser()
    for name in ('root', 'out', 'paired', 'oracle', 'baseline-worker', 'kit', 'resource-check'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--stage-cap-s', type=int, default=900)
    sys.exit(stage(parser.parse_args()))
