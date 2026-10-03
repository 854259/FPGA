"""Independent local integration tests. Fake HTTP/EDA never imply RTL quality."""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PACKAGE = HERE.parent/'package'
FORMAL = ROOT/'04_project/amd_rtl_agent/submission'
INPUT = ROOT/'03_analysis/r2_signedness_20261003/input/Prob115_shift18'
PROMPT = (INPUT/'prompt.txt').read_text(encoding='utf-8')
ORIGINAL = (INPUT/'candidate.sv').read_text(encoding='utf-8')
FIXED = ORIGINAL.replace('q_reg >>>', '$signed(q_reg) >>>')
RECEIPTS = []


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runtime = load('isolated_runtime', PACKAGE/'agent/runtime.py')
old_runtime = load('unchanged_runtime', FORMAL/'agent/runtime.py')


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def alive(pid):
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    stat = Path(f'/proc/{pid}/stat')
    if stat.exists():
        return stat.read_text().split(') ', 1)[1].split()[0] != 'Z'
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class Model(BaseHTTPRequestHandler):
    lock = threading.Lock()
    specs = []
    requests = []

    def log_message(self, *args):
        pass

    def emit(self, raw, status=200):
        self.send_response(status)
        self.send_header('Content-Length', str(len(raw)))
        try:
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        self.emit(json.dumps({'data': [{'id': 'local-review-test-model'}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with self.lock:
            index = len(self.requests)
            self.requests.append(body)
            spec = dict(self.specs[index]) if index < len(self.specs) else {'status': 500}
        time.sleep(spec.get('delay', 0))
        raw = spec.get('raw')
        if raw is None:
            payload = spec.get('payload', {'model': 'local-review-test-model',
                'choices': [{'finish_reason': spec.get('finish', 'stop'),
                    'message': {'content': spec.get('source', ORIGINAL)}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 20,
                          'prompt_tokens_details': {'cached_tokens': 3}},
                'timings': {'predicted_ms': 1}})
            raw = json.dumps(payload).encode()
        self.emit(raw, spec.get('status', 200))


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
        cls.model.daemon_threads = True
        cls.thread = threading.Thread(target=cls.model.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.model.shutdown()
        cls.model.server_close()
        cls.thread.join()
        dest = os.environ.get('LOCAL_INTEGRATION_RECEIPTS')
        if dest:
            Path(dest).write_text(json.dumps(RECEIPTS, indent=2), encoding='utf-8', newline='\n')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='local-selective-')
        self.base = Path(self.temp.name)
        self.bin = self.base/'bin'
        self.bin.mkdir()
        compiler = HERE/'fake_compiler.py'
        tool = self.bin/('xvlog.bat' if os.name == 'nt' else 'xvlog')
        if os.name == 'nt':
            tool.write_text(f'@echo off\n"{sys.executable}" "{compiler}" %*\nexit /b %errorlevel%\n')
        else:
            tool.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{compiler}" "$@"\n')
            tool.chmod(0o755)
        self.compiler_log = self.base/'compiler.jsonl'
        self.env = mock.patch.dict(os.environ, {
            'LLM_BASE_URL': f'http://127.0.0.1:{self.model.server_port}/v1',
            'MODEL_NAME': 'local-review-test-model', 'RTL_PROFILE': 'development',
            'VIVADO_BIN': str(self.bin), 'RTL_REPAIRS': '1', 'RTL_REVIEW_MODE': 'checklist',
            'RTL_REVIEW_LLM_CAP_S': '3', 'RTL_REVIEW_COMPILE_CAP_S': '3',
            'RTL_REVIEW_CLEANUP_RESERVE_S': '1', 'RTL_REVIEW_SOCKET_CAP_S': '3',
            'RTL_TEMPERATURE': '0', 'RTL_MAX_TOKENS': '8192',
            'FAKE_COMPILER_LOG': str(self.compiler_log),
            'FPGACHINA_TOKEN': 'local-fixture-token', 'EDA_TMP': str(self.base/'scratch'),
        })
        self.env.start()
        with Model.lock:
            Model.requests = []
            Model.specs = []
        self.serial = 0

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def run_case(self, specs, source=ORIGINAL, prompt=PROMPT, mode='agent',
                 review='checklist', seconds=20, interface=None, module=runtime):
        with Model.lock:
            Model.requests = []
            Model.specs = [{'source': source}] + specs
        os.environ['RTL_REVIEW_MODE'] = review
        self.serial += 1
        task, out = self.base/f'task-{self.serial}', self.base/f'out-{self.serial}'
        task.mkdir()
        runtime.write(task/'prompt.txt', prompt)
        if interface is not None:
            runtime.write(task/'interface.txt', interface)
        for name in ('ref.sv', 'test.sv', 'feedback.txt', 'task.json'):
            runtime.write(task/name, 'PRIVATE_INPUT_BOUNDARY_CANARY')
        compiler_before = len(self.compiler_log.read_text().splitlines()) if self.compiler_log.exists() else 0
        started = time.monotonic()
        solution, trace = module.run_job(mode, task, out, seconds)
        elapsed = time.monotonic()-started
        events = [json.loads(line) for line in trace.splitlines()]
        with Model.lock:
            requests = list(Model.requests)
        compiler = [json.loads(line) for line in self.compiler_log.read_text().splitlines()[compiler_before:]] if self.compiler_log.exists() else []
        RECEIPTS.append({'test': self.id(), 'case': self.serial, 'review': review, 'mode': mode,
            'seconds': seconds, 'elapsed_s': elapsed, 'solution_sha256': digest(solution),
            'requests_received': len(requests), 'requests': requests, 'events': events,
            'compiler_records': compiler})
        self.assertNotIn('PRIVATE_INPUT_BOUNDARY_CANARY', json.dumps(requests))
        return solution, events, requests, out, elapsed

    def commit(self, events):
        commits = [e for e in events if e['tool'] == 'review_commit']
        self.assertEqual(len(commits), 1)
        return commits[0]

    def retained(self, result, original=ORIGINAL, calls=2):
        solution, events, requests, out, _ = result
        self.assertEqual(solution, original)
        self.assertEqual((out/'solution.v').read_text(), original)
        self.assertEqual(len(requests), calls)
        commit = self.commit(events)
        self.assertEqual(commit['final_sha256'], digest(original))
        self.assertNotEqual(commit['status'], 'accepted')
        self.assertEqual(events[-1]['tool'], 'worker_done')
        self.assertLessEqual(events[-1]['model_calls'], 2)
        return commit

    def test_01_package_identity_and_default_off(self):
        for name in ('baseline.py', 'run_baseline.sh', 'upstream.json',
                     'skill/rtl-generation/SKILL.md', 'skill/rtl-feedback-repair/SKILL.md'):
            self.assertEqual((PACKAGE/name).read_bytes(), (FORMAL/name).read_bytes())
        self.assertTrue(runtime.baseline_integrity())
        with mock.patch.dict(os.environ):
            os.environ.pop('RTL_REVIEW_MODE', None)
            self.assertEqual(runtime._review_config()['mode'], 'off')
        before = self.run_case([], review='off', module=old_runtime)
        after = self.run_case([], review='off')
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[2], after[2])
        self.assertEqual(self.commit(after[1])['reason'], 'off')

    def test_02_baseline_unchanged_no_review(self):
        result = self.run_case([{'source': FIXED}], mode='baseline')
        self.assertEqual(result[0], ORIGINAL)
        self.assertEqual(len(result[2]), 1)
        self.assertFalse(any(e['tool'].startswith('review_') for e in result[1]))
        self.assertEqual(result[2][0]['messages'][1]['content'], PROMPT)

    def test_03_observe_records_but_does_not_call(self):
        result = self.run_case([], review='observe')
        self.retained(result, calls=1)
        self.assertEqual(next(e for e in result[1] if e['tool']=='review_select')['decision'], 'review')
        self.assertEqual(self.commit(result[1])['reason'], 'observe')

    def test_04_control_and_checklist_only_prompt_delta(self):
        c = self.run_case([{'source': FIXED}], review='control')
        d = self.run_case([{'source': FIXED}], review='checklist')
        for result in (c, d):
            self.assertEqual(result[0], FIXED)
            self.assertEqual(len(result[2]), 2)
            self.assertEqual(self.commit(result[1])['status'], 'accepted')
            self.assertEqual(self.commit(result[1])['functional_improvement'], 'unverified')
            self.assertEqual(result[1][-1]['model_calls'], 2)
        # Compare copies; never mutate the actual received-request evidence.
        cp, dp = json.loads(json.dumps(c[2][1])), json.loads(json.dumps(d[2][1]))
        self.assertEqual(dp['messages'][1]['content'], cp['messages'][1]['content']+runtime.REVIEW_CHECKLIST)
        cp['messages'][1]['content'] = dp['messages'][1]['content']
        self.assertEqual(cp, dp)
        meta = next(e for e in d[1] if e['tool']=='review_meta')
        self.assertEqual(meta['runtime_sha256'], digest((PACKAGE/'agent/runtime.py').read_bytes()))
        self.assertEqual(meta['selector_sha256'], digest((PACKAGE/'agent/signedness_selector.py').read_bytes()))
        llm_end = next(e for e in d[1] if e['tool']=='review_llm_end')
        self.assertEqual(llm_end['usage']['prompt_tokens_details']['cached_tokens'], 3)

    def test_05_skip_and_abstain_use_no_extra_call(self):
        cases = [(FIXED, 'skip'), (ORIGINAL.replace('q_reg >>> 1', 'q_reg[63:0] >>> 1'), 'abstain'),
                 ('module TopModule(input a, output y); assign y=a; endmodule\n', 'skip')]
        for source, decision in cases:
            with self.subTest(decision=decision, source=digest(source)):
                result = self.run_case([], source=source)
                self.retained(result, original=source, calls=1)
                self.assertEqual(next(e for e in result[1] if e['tool']=='review_select')['decision'], decision)

    def test_06_call_budget_zero_and_consumed_by_compile_repair(self):
        os.environ['RTL_REPAIRS'] = '0'
        result = self.run_case([])
        self.assertEqual(self.retained(result, calls=1)['reason'], 'call_budget')
        os.environ['RTL_REPAIRS'] = '1'
        result = self.run_case([{'source': ORIGINAL}], source=ORIGINAL.replace('endmodule','// FAKE_COMPILE_FAIL\nendmodule'))
        self.assertEqual(self.retained(result)['reason'], 'call_budget')
        self.assertIn('controlled candidate compiler failure', result[2][1]['messages'][1]['content'])

    def test_07_time_admission_preserves_original(self):
        result = self.run_case([], seconds=4)
        self.assertEqual(self.retained(result, calls=1)['reason'], 'time_budget')

    def test_08_invalid_configuration_preserves_original(self):
        for key, value in [('RTL_REVIEW_MODE','typo'), ('RTL_REVIEW_LLM_CAP_S','nan'),
                           ('RTL_REVIEW_COMPILE_CAP_S','0')]:
            with self.subTest(key=key), mock.patch.dict(os.environ, {key:value}):
                result = self.run_case([], review=value if key=='RTL_REVIEW_MODE' else 'checklist')
                self.assertEqual(self.retained(result, calls=1)['reason'], 'exception:ValueError')

    def test_09_candidate_rejection_matrix(self):
        cases = [('empty', {'source':''}, 'nonempty'),
            ('truncated', {'source':FIXED, 'finish':'length'}, 'nonlength'),
            ('missing_end', {'source':FIXED.replace('endmodule','')}, 'complete_module'),
            ('wrong_width', {'source':FIXED.replace('output [63:0] q','output [31:0] q')}, 'same_interface'),
            ('signed_port', {'source':FIXED.replace('output [63:0] q','output signed [63:0] q')}, 'same_interface'),
            ('wrong_direction', {'source':FIXED.replace('input  load','output load')}, 'same_interface'),
            ('reverse_range', {'source':FIXED.replace('output [63:0] q','output [0:63] q')}, 'same_interface'),
            ('rename_port', {'source':FIXED.replace('output [63:0] q','output [63:0] q_new')}, 'same_interface'),
            ('signed_input', {'source':FIXED.replace('input  [63:0] data','input signed [63:0] data')}, 'same_interface'),
            ('include', {'source':FIXED.replace('endmodule','`include "other.sv"\nendmodule')}, 'no_file_io'),
            ('file_read', {'source':FIXED.replace('endmodule','initial $fread(q); endmodule')}, 'no_file_io'),
            ('missing_submodule', {'source':FIXED.replace('endmodule','Missing unit0(.q(q)); endmodule')}, 'self_contained')]
        for name, spec, gate in cases:
            with self.subTest(name=name):
                result = self.run_case([spec])
                commit = self.retained(result)
                self.assertIn(gate, commit['reason'])

    def test_10_malformed_http_and_payload_keep_original(self):
        for spec in ({'raw':b'not json'}, {'status':500}, {'payload':{'choices':[]}}, {'payload':{}}):
            with self.subTest(spec=str(spec)):
                commit = self.retained(self.run_case([spec]))
                self.assertTrue(commit['reason'].startswith(('llm_error', 'exception:')))

    def test_11_compiler_rejection_keeps_original(self):
        result = self.run_case([{'source':FIXED.replace('endmodule','// FAKE_COMPILE_FAIL\nendmodule')}])
        self.assertEqual(self.retained(result)['reason'], 'compile_failed')
        records = [json.loads(line) for line in self.compiler_log.read_text().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertNotEqual(records[0]['cwd'], records[1]['cwd'])

    def test_12_model_timeout_keeps_original_then_service_recovers(self):
        os.environ['RTL_REVIEW_LLM_CAP_S'] = '.5'
        result = self.run_case([{'source':FIXED, 'delay':2}])
        self.retained(result)
        self.assertLess(result[4], 3)
        end = next(e for e in result[1] if e['tool']=='review_llm_end')
        self.assertEqual(end['shared_model_cancellation'], 'unknown')
        self.assertEqual(self.run_case([], review='off')[0], ORIGINAL)

    def test_13_compile_timeout_kills_owned_process_tree(self):
        os.environ['RTL_REVIEW_COMPILE_CAP_S'] = '.5'
        result = self.run_case([{'source':FIXED.replace('endmodule','// FAKE_COMPILE_SLEEP FAKE_COMPILE_SPAWN_CHILD\nendmodule')}])
        self.assertEqual(self.retained(result)['reason'], 'compile_timeout')
        self.assertLess(result[4], 3)
        records = [json.loads(line) for line in self.compiler_log.read_text().splitlines()]
        target = records[-1]
        self.assertIn('child_pid', target)
        for pid in (target['pid'], target['child_pid']):
            self.assertFalse(alive(pid), f'owned process {pid} survived')

    def test_14_identical_reply_uses_one_review_and_no_compile(self):
        result = self.run_case([{'source':ORIGINAL}])
        self.assertEqual(self.retained(result)['status'], 'unchanged')
        self.assertEqual(len(self.compiler_log.read_text().splitlines()), 1)

    def test_15_declared_fix_success_reviews_actual_accepted_source(self):
        prompt = 'Implement an 8-bit arithmetic shift register. Load data when load is high; otherwise arithmetic right shift by one. q is the shift register state.'
        source = ('module TopModule(input clk, input load, input [7:0] data, output [7:0] q);\n'
                  'always @(posedge clk) if(load) q <= data; else q <= q >>> 1;\n'
                  '// FAKE_DECLARATION_CASE\nendmodule\n')
        patched = source.replace('output [7:0] q','output reg [7:0] q')
        fixed = patched.replace('q >>> 1','$signed(q) >>> 1')
        result = self.run_case([{'source':fixed}], source=source, prompt=prompt)
        self.assertEqual(result[0], fixed)
        self.assertEqual(len(result[2]), 2)
        self.assertIn(patched, result[2][1]['messages'][1]['content'])
        self.assertEqual(self.commit(result[1])['original_sha256'], digest(patched))
        self.assertEqual(len(self.compiler_log.read_text().splitlines()), 3)

    def test_16_interface_file_mismatch_rejects_before_review_call(self):
        interface = ORIGINAL.split(');',1)[0]+'); endmodule'
        good = self.run_case([{'source':FIXED}], interface=interface)
        self.assertEqual(good[0], FIXED)
        bad = self.run_case([], interface=interface.replace('output [63:0] q','output [31:0] q'))
        self.assertEqual(self.retained(bad, calls=1)['reason'], 'accepted_interface_unparseable_or_mismatch')

    def test_17_static_acceptance_is_not_functional_success(self):
        wrong = ORIGINAL.replace('>>>', '>>')
        result = self.run_case([{'source':wrong}])
        self.assertEqual(result[0], wrong)
        self.assertEqual(self.commit(result[1])['functional_improvement'], 'unverified')
        self.assertEqual(self.commit(result[1])['reason'], 'static_and_compile_gates_only')

    def test_18_selector_exception_retains_original(self):
        isolated = self.base/'fault-package'
        shutil.copytree(PACKAGE, isolated, ignore=shutil.ignore_patterns('__pycache__'))
        runtime.write(isolated/'agent/signedness_selector.py', 'def analyze(*args): raise RuntimeError("fixture")\n')
        faulty = load('fault_selector_runtime', isolated/'agent/runtime.py')
        result = self.run_case([], module=faulty)
        self.assertEqual(self.retained(result, calls=1)['reason'], 'selector_exception')

    def test_19_atomic_replace_failure_keeps_complete_original(self):
        task, out = self.base/'direct-task', self.base/'direct-out'
        task.mkdir(); out.mkdir()
        runtime.write(task/'prompt.txt', PROMPT)
        with Model.lock:
            Model.requests = []
            Model.specs = [{'source':ORIGINAL}, {'source':FIXED}]
        replace = os.replace
        def fail_final(src, dest):
            if Path(dest) == out/'solution.v':
                raise OSError('controlled commit failure')
            return replace(src, dest)
        with mock.patch.object(sys, 'path', [str(PACKAGE/'agent'), str(PACKAGE)]+sys.path), \
             mock.patch.object(runtime.os, 'replace', side_effect=fail_final), \
             mock.patch.object(runtime.Path, 'cwd', return_value=self.base):
            runtime.worker(task, out, time.monotonic()+20)
        self.assertEqual((out/'solution.v').read_text(), ORIGINAL)
        self.assertEqual((out/'solution.review.tmp').read_text(), FIXED)
        events = [json.loads(line) for line in (out/'trace.jsonl').read_text().splitlines()]
        self.assertEqual(self.commit(events)['reason'], 'exception:OSError')
        RECEIPTS.append({'test':self.id(), 'events':events, 'solution_sha256':digest((out/'solution.v').read_bytes()),
                         'requests_received':len(Model.requests)})

    def test_20_real_http_response_contract_and_recovery(self):
        with Model.lock:
            Model.specs = [{'source':ORIGINAL}, {'source':FIXED}, {'source':ORIGINAL}]
        server = ThreadingHTTPServer(('127.0.0.1',0), runtime.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def call(deadline):
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v1/solve',
                data=json.dumps({'task_id':'local-opaque-id', 'prompt':PROMPT, 'interface':'',
                                 'mode':'agent', 'deadline_s':deadline}).encode(),
                headers={'Authorization':'Bearer local-fixture-token'})
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)
        try:
            result = call(20)
            self.assertEqual(set(result), {'task_id','solution','trace','elapsed_s'})
            self.assertEqual(result['solution'], FIXED)
            os.environ['RTL_REVIEW_MODE'] = 'off'
            again = call(10)
            self.assertEqual(again['solution'], ORIGINAL)
            self.assertLess(again['elapsed_s'], 10)
            RECEIPTS.append({'test':self.id(), 'http_responses':[result,again], 'requests_received':len(Model.requests)})
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_21_outer_deadline_retains_answer_when_inner_deadline_is_faulted(self):
        # Simulate a faulty inner budget; only run_job's real outer supervisor acts.
        # The fault lives in the test, never in the submitted runtime.
        popen = subprocess.Popen
        launched = []
        def faulty_inner_deadline(args, *pos, **kw):
            command = list(args)
            if 'worker' in command and '--deadline-mono' in command:
                command[command.index('--deadline-mono')+1] = str(time.monotonic()+100)
            proc = popen(command, *pos, **kw)
            launched.append(proc.pid)
            return proc
        with mock.patch.object(runtime.subprocess, 'Popen', side_effect=faulty_inner_deadline):
            result = self.run_case([{'source':FIXED,'delay':2}], seconds=1)
        self.assertEqual(result[0], ORIGINAL)
        self.assertEqual(len(result[2]), 2)
        self.assertTrue(any(e['tool']=='supervisor' and e.get('event')=='deadline' for e in result[1]))
        self.assertLess(result[4], 3)
        self.assertFalse(alive(launched[0]))

    def test_22_baseline_bypasses_invalid_review_configuration(self):
        result = self.run_case([], mode='baseline', review='invalid')
        self.assertEqual(result[0], ORIGINAL)
        self.assertEqual(len(result[2]),1)
        self.assertEqual([e['tool'] for e in result[1]], ['baseline_meta','llm'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
