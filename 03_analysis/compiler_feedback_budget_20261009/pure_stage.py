"""AMD-only retained-log replay and simulated worker wiring, never model/EDA."""
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

assert sys.platform == 'linux' and sys.dont_write_bytecode
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results'
OUT.mkdir(exist_ok=False)
sha = lambda b: hashlib.sha256(b).hexdigest()
manifest = json.loads((ROOT / 'SOURCE_MANIFEST.json').read_bytes())
assert all(sha((ROOT / n).read_bytes()) == h for n, h in manifest.items())
old = ast.parse((ROOT / 'runtime_original.py').read_bytes())
new = ast.parse((ROOT / 'runtime.py').read_bytes())
old_worker = next(n for n in old.body if isinstance(n, ast.FunctionDef) and n.name == 'worker')
new_worker = next(n for n in new.body if isinstance(n, ast.FunctionDef) and n.name == 'worker')
old_text = ast.unparse(old_worker)
expected = old_text.replace(
    "lines = [s for s in result.stdout.splitlines() if re.search('ERROR|WARNING|FATAL', s)]\n        feedback = '\\n'.join(lines)[:2048] or result.stdout[-2048:]",
    'feedback = compiler_feedback(result.stdout)')
assert expected != old_text and ast.dump(ast.parse(expected)) == ast.dump(ast.parse(ast.unparse(new_worker)))
new_without = ast.Module(body=[n for n in new.body if not (isinstance(n, ast.FunctionDef) and n.name in ('worker', 'compiler_feedback'))], type_ignores=[])
old_without = ast.Module(body=[n for n in old.body if not (isinstance(n, ast.FunctionDef) and n.name == 'worker')], type_ignores=[])
assert ast.dump(new_without) == ast.dump(old_without)


def forbidden(*args, **kwargs):
    raise RuntimeError('No real model, EDA, subprocess or network in this stage')


spec = importlib.util.spec_from_file_location('budget_runtime', ROOT / 'runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class DiagnosticControls(unittest.TestCase):
    def test_short_mixed_log_is_exact(self):
        log = 'INFO: hello\nWARNING: width\nERROR: declaration\n'
        self.assertEqual(runtime.compiler_feedback(log), 'WARNING: width\nERROR: declaration')

    def test_unstructured_fallback_is_exact(self):
        log = 'unstructured\n' * 700
        self.assertEqual(runtime.compiler_feedback(log), log[-2048:])

    def test_exact_character_boundary_is_unchanged(self):
        log = 'ERROR: ' + 'x' * (2048 - 7)
        self.assertEqual(runtime.compiler_feedback(log), log)

    def test_overflow_keeps_distinct_errors(self):
        repeats = ['WARNING: many warnings [' + '/tmp/long/path/candidate.sv:' + str(i) + ']' for i in range(80)]
        errors = ['ERROR: [VRFC 10-1280] non-register ' + s + ' [/tmp/candidate.sv:99]' for s in ('next_value', 'result_bit', 'input_pin')]
        answer = runtime.compiler_feedback('\n'.join(repeats + errors))
        self.assertTrue(all(e in answer for e in errors))
        self.assertTrue(answer.startswith(errors[0]))
        self.assertLessEqual(len(answer), 2048)

    def test_identical_errors_in_different_files_are_retained(self):
        errors = ['ERROR: [VRFC 10-1280] non-register v [' + f + ':9]' for f in ('/tmp/a.sv', '/tmp/b.sv')]
        answer = runtime.compiler_feedback('\n'.join(['WARNING: noise ' + 'x' * 2100] + errors))
        self.assertTrue(all(e in answer for e in errors))

    def test_repeated_locations_keep_first_original_line(self):
        errors = ['ERROR: [VRFC 10-1280] non-register v [/tmp/a.sv:' + str(i) + ']' for i in range(80)]
        answer = runtime.compiler_feedback('\n'.join(errors))
        self.assertEqual(answer, errors[0])

    def test_single_huge_error_is_bounded(self):
        error = 'FATAL: ' + 'x' * 3000
        self.assertEqual(runtime.compiler_feedback(error), error[:2048])

    def test_reordered_lines_are_original_facts(self):
        lines = ['WARNING: repeated [/tmp/a.sv:' + str(i) + ']' for i in range(100)] + ['FATAL: genuine failure']
        answer = runtime.compiler_feedback('\n'.join(lines))
        self.assertTrue(set(answer.splitlines()).issubset(set(lines)))
        self.assertEqual(answer.splitlines()[0], lines[-1])


archive = Path('/workspace/team/runs/fpga_owner/waveform_first_request_full156_20261007_v1_terminal_review_v2/terminal_v1.zip')
archive_hash = '997e65f38eeb1f03fbb20b15fddd8c0f11b4110d28616a5eedfcacbafe6924b1'
assert sha(archive.read_bytes()) == archive_hash
bindings, changed, replays = {}, [], []
stream = io.StringIO()
with patch.object(subprocess, 'Popen', forbidden), patch.object(subprocess, 'run', forbidden), patch.object(socket, 'socket', forbidden), patch.object(urllib.request, 'urlopen', forbidden):
    tests = unittest.defaultTestLoader.loadTestsFromTestCase(DiagnosticControls)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(tests)
    assert result.wasSuccessful(), stream.getvalue()
    with zipfile.ZipFile(archive) as z:
        def retained(name):
            data = z.read(name)
            bindings[name] = sha(data)
            return data
        for name in z.namelist():
            if not name.startswith('run/results/samples/') or '/worker/compile_receipts/' not in name or not name.endswith('/owned_compile.log'):
                continue
            text = retained(name).decode(errors='replace')
            lines = [s for s in text.splitlines() if runtime.re.search('ERROR|WARNING|FATAL', s)]
            old_feedback = '\n'.join(lines)[:2048] or text[-2048:]
            feedback = runtime.compiler_feedback(text)
            assert len(feedback) <= 2048
            if len('\n'.join(lines)) <= 2048:
                assert old_feedback == feedback
            if feedback != old_feedback:
                changed.append(dict(member=name,old_sha256=sha(old_feedback.encode()),new_sha256=sha(feedback.encode())))
            replays.append(dict(member=name,input_sha256=sha(text.encode()),changed=feedback != old_feedback))

        # Retained actual compiler facts: all three failing signals must survive.
        base = 'run/results/samples/C/Prob134_2014_q3c/worker/'
        log0 = retained(base + 'compile_receipts/0/owned_compile.log').decode()
        old_request = json.loads(retained(base + 'requests/1/request.json'))
        old_diagnostic = old_request['messages'][-1]['content'].rsplit('Candidate diagnostics:\n', 1)[1]
        feedback = runtime.compiler_feedback(log0)
        targets = ['non-register next_state ', 'non-register z_comb ', 'non-register y ']
        assert all(t in feedback for t in targets)
        assert targets[0] in old_diagnostic and all(t not in old_diagnostic for t in targets[1:])

        # Run the actual changed worker with retained replies and fake compilation.
        # This tests request wiring, not a new successful model repair.
        first_request = json.loads(retained(base + 'requests/0/request.json'))
        response_bytes = [retained(base + 'requests/' + str(i) + '/response.json') for i in (0, 1)]
        logs = [retained(base + 'compile_receipts/' + str(i) + '/owned_compile.log').decode() for i in (0, 1)]
        candidates = [retained(base + 'compile_receipts/' + str(i) + '/source_before.sv') for i in (0, 1)]
        requests, compiler_calls = [], []
        skill = first_request['messages'][0]['content']
        second_system = old_request['messages'][0]['content']
        assert second_system.startswith(skill + '\n')

        def fake_model(request, **kwargs):
            assert len(requests) < 2
            requests.append(json.loads(request.data))
            return io.BytesIO(response_bytes[len(requests)-1])

        def fake_compile(argv, **kwargs):
            index = len(compiler_calls)
            assert index < 2 and argv[1] == '--sv'
            assert Path(argv[2]).read_bytes() == candidates[index]
            compiler_calls.append(index)
            return subprocess.CompletedProcess(argv, 1, logs[index])

        env = dict(MODEL_NAME=first_request['model'], RTL_REPAIRS='1', RTL_MAX_TOKENS='8192', RTL_TEMPERATURE='0')
        with tempfile.TemporaryDirectory(dir=OUT) as directory:
            folder = Path(directory)
            task = folder / 'prompt_only'
            task.mkdir()
            (task / 'prompt.txt').write_text(first_request['messages'][-1]['content'])
            output = folder / 'worker'
            output.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(output)
                with patch.dict(os.environ, env), patch.object(runtime, 'skill_texts', lambda: (skill, second_system[len(skill)+1:])), patch.object(runtime, 'vivado_tool', lambda name: '/fake/xvlog'), patch.object(urllib.request, 'urlopen', fake_model), patch.object(subprocess, 'run', fake_compile):
                    runtime.worker(task, output)
            finally:
                os.chdir(previous)
        assert len(requests) == len(compiler_calls) == 2
        assert requests[0] == first_request
        expected_request = json.loads(json.dumps(old_request))
        prefix = expected_request['messages'][-1]['content'].rsplit('Candidate diagnostics:\n', 1)[0]
        expected_request['messages'][-1]['content'] = prefix + 'Candidate diagnostics:\n' + feedback
        assert requests[1] == expected_request
        assert all(r['max_tokens'] == 8192 and r['temperature'] == 0 and r['top_p'] == 1 for r in requests)
        assert all(sha(z.read(n)) == h for n, h in bindings.items())

assert sha(archive.read_bytes()) == archive_hash
assert all(sha((ROOT / n).read_bytes()) == h for n, h in manifest.items())
(OUT / 'CONTROLS_LOG.txt').write_text(stream.getvalue())
summary = dict(passed=True,tests=result.testsRun,retained_log_replays=len(replays),changed_diagnostics=changed,
    source_hashes_held=True,original_archive_sha256=archive_hash,retained_hashes=bindings,
    actual_worker_simulated_requests=2,actual_worker_simulated_compiler_calls=2,
    first_request_exact=True,repair_request_only_diagnostics_changed=True,
    recovered_failing_signal_count=2,new_model_calls=0,new_eda_calls=0,new_fifo_tickets=0,
    original_runtime_other_AST_unchanged=True,score_measured=False,adoption=False,
    scope='Retained native-log formatting and actual-worker mock wiring; no native rerun, new model score or benefit claim.')
(OUT / 'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ('retained_hashes',)}))
