"""Protocol integration tests use a local fake model, never a paid endpoint."""
import importlib.util
import http.client
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import sys
import subprocess
import socket
import signal
import types
import zipfile
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runtime = load('contract_runtime', ROOT/'submission/runtime.py')
evaluation = load('contract_eval', ROOT/'official_eval.py')


class HttpEvaluationTests(unittest.TestCase):
    @staticmethod
    def metrics(running=0, waiting=0, count=0, created=10):
        return ('vllm:num_requests_running{engine="0",model_name="fixture"} '+str(running)+'\n'+
                'vllm:num_requests_waiting{engine="0",model_name="fixture"} '+str(waiting)+'\n'+
                'vllm:request_success_total{engine="0",model_name="fixture",finished_reason="stop"} '+str(count)+'\n'+
                'vllm:request_success_created{engine="0",model_name="fixture",finished_reason="stop"} '+str(created)+'\n').encode()

    def serve(self, handler):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}'

    def test_frozen_protocol_checks_hashes_and_blocks_unmet_gates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'agent-input').mkdir()
            (root/'agent-input/prompt.txt').write_bytes(b'spec')
            plan = dict(files_sha256={'agent-input\\prompt.txt': hashlib.sha256(b'spec').hexdigest()},
                        launch_ready=False, gates=[{'status': 'blocked'}])
            path = root/'plan.json'
            raw = json.dumps(plan).encode()
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError, 'protocol hash'):
                evaluation.verify_http_protocol(path, '0'*64)
            with self.assertRaisesRegex(ValueError, 'launch blocked'):
                evaluation.verify_http_protocol(path, digest)
            (root/'agent-input/prompt.txt').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'input hash'):
                evaluation.verify_http_protocol(path, digest)

    def test_slow_drip_is_absolute_timeout_preserves_partial_and_never_retries(self):
        seen = []
        class Drip(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                seen.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', '100')
                self.end_headers()
                try:
                    for _ in range(100):
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        time.sleep(.02)
                except OSError:
                    pass
        endpoint = self.serve(Drip)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)/'request'
            started = time.monotonic()
            with self.assertRaises((TimeoutError, OSError)):
                evaluation.http_exchange(endpoint, '/metrics', None, out, started + .25)
            self.assertLess(time.monotonic()-started, 1.0)
            record = json.loads((out/'transport.json').read_text())
            self.assertEqual(record['error'], 'wall_timeout')
            self.assertFalse(record['response_complete'])
            self.assertGreater((out/'response.bin').stat().st_size, 0)
            with self.assertRaises(FileExistsError):
                evaluation.http_exchange(endpoint, '/metrics', None, out, time.monotonic()+1)
            self.assertEqual(len(seen), 1)

    def test_incomplete_body_and_redirect_are_not_followed(self):
        seen = []
        class Broken(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                seen.append(self.path)
                self.send_response(302 if self.path == '/metrics' else 200)
                self.send_header('Location', 'http://invalid.example')
                self.send_header('Content-Length', '10' if self.path == '/v1/health' else '1')
                self.end_headers()
                self.wfile.write(b'x')
        endpoint = self.serve(Broken)
        with tempfile.TemporaryDirectory() as td:
            for index, route in enumerate(('/v1/health', '/metrics')):
                with self.assertRaisesRegex(ValueError, 'incomplete HTTP body|HTTP status 302'):
                    evaluation.http_exchange(endpoint, route, None, Path(td)/str(index), time.monotonic()+1)
            self.assertEqual(len(seen), 2)

    def test_solve_payload_boundary_and_response_ledger(self):
        seen = []
        events = '\n'.join(json.dumps(x) for x in (
            dict(tool='llm_start', round=0),
            dict(tool='llm', round=0, tokens_in=4, tokens_out=5, finish='stop', response_status='complete')))
        class Fixed(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append(value)
                raw = json.dumps(dict(task_id=value['task_id'], solution='module TopModule; endmodule',
                                      trace=events, elapsed_s=.01)).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        endpoint = self.serve(Fixed)
        request = dict(task_id='fixture', nonce='unique', mode='agent', prompt='only public spec',
                       interface='', deadline_s=1)
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, FPGACHINA_TOKEN='fixture-only'):
            out = Path(td)/'request'
            with self.assertRaisesRegex(ValueError, 'official solve fields'):
                evaluation.solve_http(endpoint, dict(request, reference='secret'), out, time.monotonic()+2)
            with self.assertRaises(TimeoutError):
                evaluation.solve_http(endpoint, request, out, time.monotonic()+.5)
            self.assertEqual(seen, [])
            result, ledger = evaluation.solve_http(endpoint, request, out, time.monotonic()+2)
            self.assertEqual(seen, [request])
            self.assertEqual(ledger['observed_attempts'], 1)
            self.assertEqual(ledger['tokens_out'], 5)
            self.assertTrue(ledger['accounting_complete'])
            self.assertIsNone(ledger['backend_executions'])
            started_record = json.loads((out/'started.json').read_text())
            self.assertTrue(started_record['request_attempted'])
            self.assertEqual(started_record['model_requests_reserved'], 2)
            self.assertIsNone(started_record['model_executions'])
            self.assertNotIn('fixture-only', ''.join(p.read_text() for p in out.iterdir()))

    def test_header_stall_is_bounded_and_malformed_response_is_preserved(self):
        class Invalid(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                time.sleep(.4)  # No response headers before the client's deadline.
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')
        endpoint = self.serve(Invalid)
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, FPGACHINA_TOKEN='fixture-only'):
            started = time.monotonic()
            with self.assertRaises((TimeoutError, OSError, http.client.HTTPException)):
                evaluation.http_exchange(endpoint, '/v1/health', None, Path(td)/'header', started+.1)
            self.assertLess(time.monotonic()-started, .35)
            request = dict(task_id='fixture', nonce='unique', mode='baseline', prompt='spec', interface='', deadline_s=1)
            out = Path(td)/'invalid'
            with self.assertRaisesRegex(ValueError, 'invalid solve response'):
                evaluation.solve_http(endpoint, request, out, time.monotonic()+2)
            self.assertEqual((out/'response.bin').read_bytes(), b'{}')
            self.assertFalse((out/'solution.v').exists())
            ledger = json.loads((out/'call-ledger.json').read_text())
            self.assertFalse(ledger['valid_response'])
            self.assertIsNone(ledger['observed_attempts'])

    def test_incomplete_model_ledger_is_unknown_not_zero_or_double_counted(self):
        self.assertIsNone(evaluation.trace_call_accounting('', 'baseline')['observed_attempts'])
        started = json.dumps(dict(tool='llm_start', round=0))
        ledger = evaluation.trace_call_accounting(started, 'agent')
        self.assertEqual(ledger['observed_attempts'], 1)
        self.assertFalse(ledger['accounting_complete'])
        self.assertIsNone(ledger['tokens_out'])
        with self.assertRaises(ValueError):
            evaluation.trace_call_accounting(started+'\n'+started, 'agent')
        error = json.dumps(dict(tool='llm', round=0, error='timeout'))
        self.assertFalse(evaluation.trace_call_accounting(error, 'baseline')['accounting_complete'])

    def test_no_network_for_unsafe_origin_or_expired_deadline(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                evaluation.http.client.HTTPConnection, 'connect', side_effect=AssertionError('no network')):
            for origin in ('https://api.example/v1', 'http://localhost:8000',
                           'http://user:secret@127.0.0.1:8000', 'http://127.0.0.1:8000/path'):
                with self.assertRaises(ValueError):
                    evaluation.http_exchange(origin, '/metrics', None, Path(td)/'out', time.monotonic()+1)
            with self.assertRaises(TimeoutError):
                evaluation.http_exchange('http://127.0.0.1:8000', '/metrics', None,
                                         Path(td)/'out', time.monotonic()-1)

    def test_backend_counts_include_completed_calls_only_between_idle_snapshots(self):
        before = evaluation.backend_snapshot(self.metrics(count=2), 'fixture')
        after = evaluation.backend_snapshot(self.metrics(count=4), 'fixture')
        self.assertEqual(evaluation.backend_call_delta(before, after), {'stop': 2})
        for raw in (self.metrics(running=1), self.metrics(waiting=1),
                    self.metrics(count=1), self.metrics(created=11)):
            with self.assertRaises(ValueError):
                evaluation.backend_call_delta(before, evaluation.backend_snapshot(raw, 'fixture'))
        for raw in (b'', self.metrics().replace(b'num_requests_waiting{', b'num_requests_waiting_by_reason{'),
                    self.metrics().replace(b'fixture', b'foreign'), self.metrics(count=float('nan'))):
            with self.assertRaises(ValueError):
                evaluation.backend_snapshot(raw, 'fixture')

    def test_backend_busy_then_idle_and_permanently_busy_stop(self):
        states = [self.metrics(running=1), self.metrics(waiting=1), self.metrics(count=1)]
        seen = []
        class Metrics(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                seen.append(self.path)
                raw = states.pop(0) if len(states) > 1 else states[0]
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        endpoint = self.serve(Metrics)
        with tempfile.TemporaryDirectory() as td:
            state = evaluation.wait_backend_idle(endpoint, 'fixture', Path(td)/'idle', time.monotonic()+2)
            self.assertEqual(state['counts'], {'stop': 1})
            self.assertEqual(len(seen), 3)
            states[:] = [self.metrics(running=1)]
            with self.assertRaises(TimeoutError):
                evaluation.wait_backend_idle(endpoint, 'fixture', Path(td)/'busy', time.monotonic()+.25)
            self.assertTrue(all(route == '/metrics' for route in seen))


@unittest.skipUnless(sys.platform == 'linux', 'Linux external judge process groups')
class JudgeSupervisionTests(unittest.TestCase):
    def test_outer_judge_cleanup_after_exit_timeout_and_sigterm(self):
        for action in ('normal', 'timeout', 'sigterm'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                official = root/'official'
                (official/'selftest').mkdir(parents=True)
                child_path = root/'child.pid'
                scratch_path = root/'scratch.path'
                fake = official/'selftest/judge.py'
                fake.write_text(
                    'import sys,os,signal,subprocess,time,json\nfrom pathlib import Path\n'
                    'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n'
                    f'Path({str(child_path)!r}).write_text(str(child.pid))\n'
                    f'Path({str(scratch_path)!r}).write_text(os.environ["SELFTEST_TMP"])\n'
                    'Path("child.log").write_text("synthetic diagnostic")\n'
                    + ('Path(sys.argv[sys.argv.index("--json")+1]).write_text(json.dumps({"tool_error":"fixture timeout"}))\n'
                       if action == 'normal' else
                       'os.kill(os.getppid(),signal.SIGTERM)\ntime.sleep(30)\n' if action == 'sigterm' else
                       'time.sleep(30)\n'), encoding='utf-8')
                out, result = root/'logs', root/'result.json'
                child = None
                old_handler = signal.getsignal(signal.SIGTERM)
                start = time.monotonic()
                try:
                    with mock.patch.object(evaluation, 'OFFICIAL', official):
                        if action == 'normal':
                            value = evaluation.judge_candidate(root, root/'solution.v', out, result, 2, start+5)
                            self.assertEqual(value['tool_error'], 'fixture timeout')
                        else:
                            expected = SystemExit if action == 'sigterm' else subprocess.TimeoutExpired
                            with self.assertRaises(expected):
                                evaluation.judge_candidate(root, root/'solution.v', out, result, .5, start+5)
                            self.assertFalse(result.exists())  # No invented L0 or successful result.
                    self.assertLess(time.monotonic()-start, 2)
                    self.assertEqual(signal.getsignal(signal.SIGTERM), old_handler)
                    child = int(child_path.read_text())
                    for _ in range(100):
                        stat = Path(f'/proc/{child}/stat')
                        if not stat.exists() or stat.read_text().split(') ')[1].split()[0] == 'Z':
                            break
                        time.sleep(.01)
                    else:
                        self.fail('judge child survived outer cleanup')
                    self.assertFalse(Path(scratch_path.read_text()).exists())
                    record = json.loads((out/'supervisor.json').read_text())
                    self.assertTrue(record['process_group_cleanup'])
                    if action != 'normal':
                        self.assertEqual((out/'interrupted_logs/child.log').read_text(), 'synthetic diagnostic')
                finally:
                    if child is None and child_path.exists():
                        child = int(child_path.read_text())
                    if child is not None:
                        try:
                            os.kill(child, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_deadline_and_existing_result_prevent_launch(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                evaluation.subprocess, 'Popen', side_effect=AssertionError('must not spawn')):
            root = Path(td)
            with self.assertRaises(TimeoutError):
                evaluation.judge_candidate(root, root/'solution', root/'out', root/'result',
                                           1, time.monotonic()-1)
            (root/'result').write_text('original')
            with self.assertRaises(FileExistsError):
                evaluation.judge_candidate(root, root/'solution', root/'out', root/'result',
                                           1, time.monotonic()+3)
            self.assertEqual((root/'result').read_text(), 'original')
            self.assertFalse((root/'out').exists())


@unittest.skipUnless(sys.platform == 'linux', 'Linux owned process supervision')
class BatchWatchdogTests(unittest.TestCase):
    serve = HttpEvaluationTests.serve

    def test_filesystem_rules_block_judge_reads_and_preserve_worker_outputs(self):
        script = r'''
import errno, json, os, subprocess, sys
from pathlib import Path
import official_eval as ev
root=Path(sys.argv[1]); public=root/'public'; scratch=root/'scratch'; private=root/'judge-only'
public.mkdir(); scratch.mkdir(); private.mkdir()
(public/'prompt').write_text('public'); (private/'reference').write_text('private')
(scratch/'alias').symlink_to(private/'reference')
assert (private/'reference').read_text() == (scratch/'alias').read_text() == 'private'
try:
    abi=ev.restrict_filesystem(['/usr','/lib','/lib64',public],[scratch])
except OSError as exc:
    if exc.errno in (errno.ENOSYS,errno.EOPNOTSUPP):
        print('LANDLOCK_UNAVAILABLE');sys.exit(77)
    raise
assert (public/'prompt').read_text()=='public'
(scratch/'output').write_text('candidate')
assert (scratch/'output').read_text()=='candidate'
for operation in [lambda:(private/'reference').read_text(),
                  lambda:(scratch/'alias').read_text(),
                  lambda:(public/'prompt').write_text('overwrite'),
                  lambda:(root/'escape').write_text('escape'),
                  lambda:os.link(private/'reference',scratch/'linked')]:
    try: operation()
    except OSError as exc: assert exc.errno in (errno.EACCES,errno.EPERM,errno.EXDEV),exc
    else: raise AssertionError('filesystem rule escaped')
code='from pathlib import Path;import sys;Path(sys.argv[1]).read_text()'
child=subprocess.run([sys.executable,'-B','-c',code,str(private/'reference')],capture_output=True,text=True)
assert child.returncode!=0 and 'PermissionError' in child.stderr,child.stderr
child=subprocess.run([sys.executable,'-B','-c','from pathlib import Path;import sys;Path(sys.argv[1]).write_text("child")',str(scratch/'child')],capture_output=True,text=True)
assert child.returncode==0,child.stderr
print(json.dumps({'abi':abi,'blocked_checks':6,'output_checks':3,'model_calls':0}))
'''
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run([sys.executable, '-B', '-c', script, td], cwd=ROOT,
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 77:
                self.skipTest('kernel does not provide Landlock ABI 3')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual((Path(td)/'judge-only/reference').read_text(), 'private')
            self.assertEqual((Path(td)/'public/prompt').read_text(), 'public')
            self.assertFalse((Path(td)/'escape').exists())

    def test_launcher_waits_for_http_readiness_before_starting_batch(self):
        script = r'''
import inspect, json, os, socket, subprocess, sys, time, types
from pathlib import Path
from unittest import mock
import official_eval as ev
root = Path(sys.argv[1]); mode = sys.argv[2]
with socket.socket() as port:
    port.bind(('127.0.0.1', 0)); number = port.getsockname()[1]
endpoint = f'http://127.0.0.1:{number}'
if mode == 'occupied':
    endpoint=sys.argv[3]; number=int(endpoint.rsplit(':',1)[1])
service = r"""
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
mode=sys.argv[1]; began=time.monotonic()
if mode == 'exit': sys.exit(7)
if mode == 'occupied': time.sleep(30); sys.exit(0)
class H(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if mode == 'hang': time.sleep(30)
        raw=json.dumps({'ready':mode != 'never' and time.monotonic()-began > .3,
                        'track':'rtl','model':'wrong' if mode == 'wrong' else 'fixture'}).encode()
        if mode == 'malformed': raw=b'{'
        self.send_response(200); self.send_header('Content-Length',str(len(raw)))
        self.end_headers(); self.wfile.write(raw)
HTTPServer(('127.0.0.1',int(sys.argv[2])),H).serve_forever()
"""
batch = r"""
import json, sys, time, urllib.request
from pathlib import Path
try:
    with urllib.request.urlopen(sys.argv[1]+'/v1/health',timeout=.5) as r: ready=json.load(r)['ready']
except Exception: ready=False
Path(sys.argv[2]).write_text('ready' if ready else 'too_early')
time.sleep(.1)
"""
kwargs = {}
if 'submission_endpoint' in inspect.signature(ev.launch_supervised_batch).parameters:
    kwargs = dict(submission_endpoint=endpoint, startup_timeout_s=.9)
began=time.monotonic(); failure=None
try:
    with mock.patch.object(ev,'module',return_value=types.SimpleNamespace(vram_gb=lambda:40. if mode=='vram' else 1.)), \
         mock.patch.object(ev,'wait_backend_idle',return_value={'running':0,'waiting':0}):
        ev.launch_supervised_batch([sys.executable,'-B','-c',batch,endpoint,str(root/'batch-started')],
            [sys.executable,'-B','-c',service,mode,str(number)],endpoint,'fixture',root/'owned',began+9,**kwargs)
except (ValueError, RuntimeError, TimeoutError) as exc: failure=type(exc).__name__
record=json.loads((root/'owned/ownership.json').read_text())
assert record['descendants_reaped'] and not record['formal_acceptance'], record
assert time.monotonic()-began < 4, record
if mode == 'delayed':
    assert failure is None, failure
    assert (root/'batch-started').read_text() == 'ready', 'batch ran before HTTP service ready'
else:
    assert failure is not None, 'invalid startup did not fail'
    assert not (root/'batch-started').exists(), 'batch launched despite failed readiness'
assert not Path('/proc/self/task/'+str(os.getpid())+'/children').read_text().strip()
try: os.waitpid(-1,os.WNOHANG)
except ChildProcessError: pass
else: raise AssertionError('owned child remains')
print(json.dumps({'mode':mode,'failure':failure,**record}))
'''
        class ExistingService(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                raw = b'{"ready":true,"track":"rtl","model":"fixture"}'
                self.send_response(200); self.send_header('Content-Length', str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
        occupied_endpoint = self.serve(ExistingService)
        for mode in ('delayed', 'never', 'wrong', 'malformed', 'exit', 'hang', 'vram', 'occupied'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                result = subprocess.run([sys.executable, '-B', '-c', script, td, mode, occupied_endpoint],
                                        cwd=ROOT, capture_output=True, text=True, timeout=12)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_launcher_rejects_shared_process_without_signalling(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
        try:
            with tempfile.TemporaryDirectory() as td, mock.patch.object(
                    evaluation.os, 'kill', side_effect=AssertionError('must not signal')):
                with self.assertRaisesRegex(ValueError, 'preexisting children'):
                    evaluation.launch_supervised_batch([], [], '', '', Path(td)/'out', time.monotonic()+10,
                                                       submission_endpoint='http://127.0.0.1:1')
                self.assertIsNone(child.poll())
                self.assertFalse((Path(td)/'out').exists())
        finally:
            child.terminate(); child.wait(timeout=2)

    def test_owned_launcher_reaps_detached_children_and_failed_startup(self):
        # A separate interpreter is essential: the subreaper must never adopt
        # unrelated children of the test runner (or of the eventual launcher).
        script = r'''
import json, os, signal, subprocess, sys, time, types
from pathlib import Path
from unittest import mock
import official_eval as ev
root = Path(sys.argv[1]); mode = sys.argv[2]
childfile = root/'child.pid'
code = ('import os,signal,subprocess,sys,time\nfrom pathlib import Path\n'
        'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],start_new_session=True)\n'
        f'Path({str(childfile)!r}).write_text(str(p.pid))\n'
        + ('os.kill(os.getpid(),signal.SIGSTOP)\n' if mode == 'stopped' else '')
        + ('time.sleep(.1)\n' if mode == 'normal' else 'time.sleep(30)\n'))
original = subprocess.Popen
calls = []
class Launch(original):
    def __init__(self, *a, **kw):
        if calls:
            until = time.monotonic()+2
            while not childfile.exists():
                assert time.monotonic()<until
                time.sleep(.01)
            if mode == 'startup_failure':
                raise FileNotFoundError('synthetic second launch failure')
            if mode == 'startup_sigterm':
                os.kill(os.getpid(), signal.SIGTERM)
        super().__init__(*a, **kw); calls.append(self)
started = time.monotonic()
def memory():
    if mode == 'sigterm':
        os.kill(os.getpid(), signal.SIGTERM)
    return 1. if mode == 'normal' else 40.
def get_module(name, path):
    return types.SimpleNamespace(vram_gb=(lambda:1.) if name == 'startup_runtime' else memory)
try:
    with mock.patch.object(ev.subprocess, 'Popen', Launch), \
         mock.patch.object(ev, 'module', side_effect=get_module), \
         mock.patch.object(ev, 'owns_tcp_listener', return_value=True), \
         mock.patch.object(ev, 'http_exchange', return_value=(b'{"ready":true,"track":"rtl","model":"fixture"}',{})), \
         mock.patch.object(ev, 'wait_backend_idle', return_value={'running':0,'waiting':0}):
        ev.launch_supervised_batch([sys.executable, '-c', 'import time;time.sleep(30)'],
            [sys.executable, '-c', code],
            'http://127.0.0.1:1', 'fixture', root/'owned', started+9,
            submission_endpoint='http://127.0.0.1:1')
except FileNotFoundError:
    assert mode == 'startup_failure'
except SystemExit:
    assert mode in ('sigterm','startup_sigterm')
record = json.loads((root/'owned/ownership.json').read_text())
assert record['descendants_reaped'] is True, record
assert record['formal_acceptance'] is False
assert time.monotonic()-started < 9
assert not Path('/proc/'+childfile.read_text()).exists(), 'detached descendant remains'
for p in calls:
    assert not Path(f'/proc/{p.pid}').exists()
try:
    os.waitpid(-1, os.WNOHANG)
except ChildProcessError:
    pass
else:
    raise AssertionError('owned child remains')
print(json.dumps({'mode':mode, **record}))
'''
        innocent = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
        try:
            for mode in ('stopped', 'normal', 'startup_failure', 'sigterm', 'startup_sigterm'):
                with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                    result = subprocess.run([sys.executable, '-B', '-c', script, td, mode],
                                            cwd=ROOT, capture_output=True, text=True, timeout=12)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertIsNone(innocent.poll())
        finally:
            innocent.terminate(); innocent.wait(timeout=2)

    def test_expired_budget_or_unowned_process_never_signals(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                evaluation.os, 'killpg', side_effect=AssertionError('must not signal')):
            with self.assertRaises(TimeoutError):
                evaluation.supervise_http_batch(None, None, '', '', Path(td)/'out', time.monotonic()+1)
            with self.assertRaises(ValueError):
                evaluation.supervise_http_batch(None, None, '', '', Path(td)/'out', time.monotonic()+10)
            self.assertFalse((Path(td)/'out').exists())

    def test_nonidle_backend_cannot_be_reported_as_clean(self):
        class Busy(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                raw = HttpEvaluationTests.metrics(running=1)
                self.send_response(200); self.send_header('Content-Length', str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
        endpoint = self.serve(Busy)
        with tempfile.TemporaryDirectory() as td:
            children = [subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'],
                                         start_new_session=True) for _ in range(2)]
            before = signal.getsignal(signal.SIGTERM)
            began = time.monotonic()
            try:
                with mock.patch.object(evaluation, 'module', return_value=types.SimpleNamespace(vram_gb=lambda: None)):
                    result = evaluation.supervise_http_batch(*children, endpoint, 'fixture', Path(td)/'out', began+5.1)
                self.assertFalse(result['backend_idle'])
                self.assertEqual(result['idle_error_type'], 'TimeoutError')
                self.assertFalse(result['deadline_exceeded'])
                self.assertTrue(result['owned_leaders_exited'])
                self.assertEqual(signal.getsignal(signal.SIGTERM), before)
            finally:
                for p in children:
                    try: os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    p.wait(timeout=2)

    def test_watchdog_stops_owned_work_on_resource_deadline_or_service_exit(self):
        metrics = HttpEvaluationTests.metrics
        class Idle(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                raw = metrics()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
        endpoint = self.serve(Idle)
        for mode, reason in [('spike', 'vram_limit'), ('unknown', 'vram_unavailable'),
                             ('deadline', 'batch_deadline'), ('normal', 'batch_exit'),
                             ('service', 'submission_exit'), ('stubborn', 'batch_deadline'),
                             ('sigterm', 'SystemExit')]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                processes = []
                child = root/'child.pid'
                # Independent innocent process proves cleanup is not a broad kill.
                innocent = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'], start_new_session=True)
                processes.append(innocent)
                service = subprocess.Popen([sys.executable, '-c',
                    'import time;time.sleep(.15)' if mode == 'service' else 'import time;time.sleep(30)'], start_new_session=True)
                processes.append(service)
                code = ('import time,subprocess,sys,signal\nfrom pathlib import Path\n'
                        'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\n'
                        f'Path({str(child)!r}).write_text(str(p.pid))\n'
                        + ('signal.signal(signal.SIGTERM,signal.SIG_IGN)\n' if mode == 'stubborn' else '')
                        + ('time.sleep(.15)\n' if mode == 'normal' else 'time.sleep(30)\n'))
                batch = subprocess.Popen([sys.executable, '-c', code], start_new_session=True)
                processes.append(batch)
                began = time.monotonic()
                prior = signal.getsignal(signal.SIGTERM)
                def resource():
                    if time.monotonic()-began < .15:
                        return 1.
                    if mode == 'sigterm':
                        os.kill(os.getpid(), signal.SIGTERM)
                    return 40. if mode == 'spike' else None if mode == 'unknown' else 1.
                try:
                    with mock.patch.object(evaluation, 'module', return_value=types.SimpleNamespace(vram_gb=resource)):
                        if mode == 'sigterm':
                            with self.assertRaises(SystemExit):
                                evaluation.supervise_http_batch(batch, service, endpoint, 'fixture', root/'watch', began+5.3)
                            value = json.loads((root/'watch/watchdog.json').read_text())
                        else:
                            value = evaluation.supervise_http_batch(batch, service, endpoint, 'fixture', root/'watch', began+5.3)
                    self.assertEqual(signal.getsignal(signal.SIGTERM), prior)
                    self.assertEqual(value['stop_reason'], reason)
                    self.assertTrue(value['backend_idle'])
                    self.assertTrue(value['owned_leaders_exited'])
                    self.assertIsNone(innocent.poll())
                    self.assertLess(time.monotonic()-began, 5.3)
                    if mode == 'spike':
                        self.assertEqual(value['sampled_peak_bytes'], 40*1024**3)
                    if mode == 'stubborn':
                        self.assertTrue(value['forced_group_kill'])
                    pid = int(child.read_text())
                    for _ in range(100):
                        stat = Path(f'/proc/{pid}/stat')
                        if not stat.exists() or stat.read_text().split(') ')[1].split()[0] == 'Z':
                            break
                        time.sleep(.01)
                    else:
                        self.fail('same-group descendant survived')
                    self.assertGreater(len((root/'watch/resources.jsonl').read_text().splitlines()), 1)
                finally:
                    for proc in processes:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(timeout=2)


class HttpBatchTests(unittest.TestCase):
    serve = HttpEvaluationTests.serve
    metrics = staticmethod(HttpEvaluationTests.metrics)

    def test_legacy_model_cli_is_blocked_before_tools_or_processes(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(sys, 'argv',
                ['official_eval.py', '--tasks', td, '--out', str(Path(td)/'out'), '--deadline', '300']), \
             mock.patch.object(evaluation, 'verify_upstream', side_effect=AssertionError('before tools')), \
             mock.patch.object(evaluation, 'http_exchange', side_effect=AssertionError('zero HTTP')), \
             mock.patch.object(evaluation.subprocess, 'Popen', side_effect=AssertionError('zero processes')):
            with self.assertRaises(SystemExit) as raised:
                evaluation.main()
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse((Path(td)/'out').exists())
    def make_batch(self, root, task_ids=None, **changes):
        inputs = root/'inputs'
        task_ids = task_ids or ['t']
        for tid in task_ids:
            (inputs/'agent-input'/tid).mkdir(parents=True)
            (inputs/'judge-only'/tid).mkdir(parents=True)
            (inputs/'agent-input'/tid/'prompt.txt').write_text('public synthetic spec', encoding='utf-8')
            (inputs/'judge-only'/tid/'task.json').write_text(json.dumps(
                dict(task_id=tid, private_canary='HIDDEN_REFERENCE')), encoding='utf-8')
            (inputs/'judge-only'/tid/'ref.sv').write_text('HIDDEN_REFERENCE', encoding='utf-8')
        archive = root/'candidate.zip'
        with zipfile.ZipFile(archive, 'x') as z:
            for name in ('runtime.py', 'baseline.py', 'run.sh', 'run_baseline.sh', 'LICENSE.official',
                         'README.md', 'upstream.json', 'skill/RTL_SKILL.md', 'skill/RTL_REPAIR_SKILL.md'):
                z.write(ROOT/'submission'/name, name)
        plan = dict(files_sha256={p.relative_to(inputs).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in inputs.rglob('*') if p.is_file()},
                    launch_ready=True, gates=[dict(status='passed')], official_commit=evaluation.verify_upstream(),
                    candidate_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                    selection=dict(task_ids=task_ids), samples_per_task_per_mode=2, modes=['agent', 'baseline'],
                    agent_repairs_max=1, model_retries=0, solve_requests_max=4, model_requests_max=6,
                    solve_deadline_s=1, judge_timeout_s=1, batch_wall_limit_s=60,
                    model=dict(served_name='fixture'))
        plan.update(changes)
        path = inputs/'plan.json'
        path.write_text(json.dumps(plan), encoding='utf-8')
        return path, hashlib.sha256(path.read_bytes()).hexdigest(), archive

    def server_batch(self, fault=None):
        fixture = dict(requests=[], calls=0)
        metrics = self.metrics
        class BatchServer(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def send(self, raw):
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def do_GET(self):
                self.send(metrics(count=fixture['calls']) if self.path == '/metrics' else
                          json.dumps(dict(ready=True, track='rtl', model='fixture')).encode())
            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture['requests'].append(req)
                fixture['calls'] += 2 if fault == 'count_mismatch' else 1
                if fault == 'transport':
                    return self.send(b'{}')
                events = [dict(tool='llm_start', round=0)] if req['mode'] == 'agent' else []
                if fault == 'timeout':
                    events.append(dict(tool='supervisor', event='deadline'))
                else:
                    events.append(dict(tool='llm', round=0, tokens_in=3, tokens_out=4,
                                       finish='stop', response_status='complete'))
                self.send(json.dumps(dict(task_id=req['task_id'], elapsed_s=.01,
                    solution='' if fault == 'timeout' else 'module TopModule; endmodule',
                    trace='\n'.join(json.dumps(e) for e in events))).encode())
        return self.serve(BatchServer), fixture

    def judge_fixture(self, task, solution, out, result_path, seconds, batch_deadline_at):
        # Fixed evaluator fixture only: no generated answer, real EDA or accuracy claim.
        level = 0 if not solution.read_text() else 3
        value = dict(task_id=task.name, level=level, coefficient=float(level == 3), tool_error=None)
        Path(out).mkdir(parents=True)
        Path(result_path).write_text(json.dumps(value), encoding='utf-8')
        return value

    def run_fixture(self, args, out, endpoint, **kwargs):
        real_module = evaluation.module
        def modules(name, path):
            return types.SimpleNamespace(vram_gb=lambda: 1.) if name == 'batch_runtime' else real_module(name, path)
        with mock.patch.object(evaluation, 'module', side_effect=modules), \
             mock.patch.object(evaluation, 'judge_candidate', side_effect=self.judge_fixture), \
             mock.patch.dict(os.environ, FPGACHINA_TOKEN='fixture-only'):
            return evaluation.run_http_batch(*args, out, endpoint, endpoint, kwargs.get('started_at', time.monotonic()))

    def test_batch_completed_with_original_denominator_and_separate_inputs(self):
        endpoint, state = self.server_batch()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); args = self.make_batch(root, task_ids=['a','b','c','d'],
                samples_per_task_per_mode=5, solve_requests_max=40, model_requests_max=60,
                batch_wall_limit_s=120)
            result = self.run_fixture(args, root/'out', endpoint)
            self.assertTrue(result['complete'])
            self.assertEqual(result['expected_solves'], 40)
            self.assertEqual(result['model_calls_reserved'], 60)
            self.assertEqual(result['verified_backend_calls'], 40)
            self.assertEqual([r['mode'] for r in state['requests']], ['agent', 'baseline']*20)
            self.assertEqual(len(set(r['nonce'] for r in state['requests'])), 40)
            self.assertNotIn('HIDDEN_REFERENCE', json.dumps(state['requests']))
            self.assertEqual(len(list((root/'out/results').glob('*.json'))), 40)
            with self.assertRaises(FileExistsError):
                self.run_fixture(args, root/'out', endpoint)
            self.assertEqual(len(state['requests']), 40)

    def test_batch_caps_and_failure_stops_preserve_missing_rows(self):
        for changes, fault, expected_posts, reason in [
            ({'model_requests_max': 2}, None, 1, 'request_cap'),
            ({'solve_requests_max': 1}, None, 1, 'request_cap'),
            ({'batch_wall_limit_s': 5}, None, 0, 'whole_batch_time'),
            ({}, 'timeout', 2, 'two_consecutive_timeouts'),
            ({}, 'transport', 1, 'ValueError'),
            ({}, 'count_mismatch', 1, 'ValueError')]:
            with self.subTest(changes=changes, fault=fault), tempfile.TemporaryDirectory() as td:
                endpoint, state = self.server_batch(fault)
                root = Path(td); args = self.make_batch(root, **changes)
                result = self.run_fixture(args, root/'out', endpoint)
                self.assertFalse(result['complete'])
                self.assertEqual(result['stop_reason'], reason)
                self.assertEqual(len(state['requests']), expected_posts)
                self.assertEqual(len(result['rows']), 4)
                self.assertEqual(len([r for r in result['rows'] if r['state'] == 'not_started']), 4-expected_posts)
                self.assertFalse((root/'out/graded_summary.json').exists())
                self.assertEqual(result['verified_backend_calls'], state['calls'])

    def test_batch_rejects_changed_or_blocked_inputs_without_http(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                evaluation, 'http_exchange', side_effect=AssertionError('no HTTP')):
            root = Path(td); args = self.make_batch(root, launch_ready=False)
            with self.assertRaisesRegex(ValueError, 'launch blocked'):
                self.run_fixture(args, root/'out', 'http://127.0.0.1:1')
            self.assertFalse((root/'out').exists())


class VivadoHealthTests(unittest.TestCase):
    def test_remote_model_endpoint_rejected_in_every_profile(self):
        for profile in ('development', 'submission'):
            with self.subTest(profile=profile), mock.patch.dict(os.environ, {'RTL_PROFILE': profile}):
                for url in ('https://api.example.com/v1', 'http://192.0.2.1:8000/v1'):
                    with mock.patch.dict(os.environ, LLM_BASE_URL=url):
                        with self.assertRaisesRegex(ValueError, 'server-local'):
                            runtime.endpoint()
                for url in ('http://127.0.0.1:8000/v1', 'http://localhost:8000/v1', 'http://[::1]:8000/v1'):
                    with mock.patch.dict(os.environ, LLM_BASE_URL=url):
                        self.assertEqual(runtime.endpoint(), url)

    def test_submission_memory_guard_uses_conservative_32gb_bytes(self):
        with mock.patch.dict(os.environ, {'MODEL_NAME': 'm', 'RTL_PROFILE': 'submission'}), \
             mock.patch.object(runtime, 'models', return_value=['m']), \
             mock.patch.object(runtime, 'baseline_integrity', return_value=True), \
             mock.patch.object(runtime, 'vivado_tool', return_value='tool'), \
             mock.patch.object(runtime, 'vivado_version', return_value='2026.1'):
            for size, expected in [(32_000_000_000, True), (32_000_000_001, False)]:
                with self.subTest(bytes=size), mock.patch.object(runtime, 'vram_gb', return_value=size/1024**3):
                    self.assertEqual(runtime.health()['ready'], expected)

    def test_diagnostic_rejects_changed_plan_or_replayed_run_before_network(self):
        diagnostic = load('bounded_diagnostic', ROOT/'tools/diagnose_runtime.py')
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            plan = diagnostic.make_plan()
            self.assertEqual(plan['calls_max'], len(plan['requests']))
            changed = dict(plan, calls_max=4)
            (out/'plan.json').write_text(json.dumps(changed), encoding='utf-8')
            with mock.patch.dict(os.environ), mock.patch.object(diagnostic.urllib.request, 'urlopen', side_effect=AssertionError('no network')):
                with self.assertRaisesRegex(ValueError, 'mismatch'):
                    diagnostic.run(out)
                self.assertFalse((out/'started.json').exists())
                (out/'plan.json').write_text(json.dumps(plan), encoding='utf-8')
                (out/'started.json').write_text('prior evidence', encoding='utf-8')
                with self.assertRaises(FileExistsError):
                    diagnostic.run(out)
            self.assertEqual((out/'started.json').read_text(), 'prior evidence')

    def test_health_accepts_linux_and_windows_version_banners(self):
        cases = (
            ('vivado v2026.1 (64-bit)\n', 0, True),
            ('Vivado v2026.1 (64-bit)\n', 0, True),
            ('vivado v2025.2 (64-bit)\n', 0, False),
            ('vivado v2026.1 (64-bit)\n', 1, False),
        )
        for banner, returncode, expected in cases:
            with self.subTest(banner=banner, returncode=returncode):
                runtime.vivado_version.cache_clear()
                with mock.patch.dict(os.environ, RTL_PROFILE='development', MODEL_NAME='test-model'), \
                     mock.patch.object(runtime, 'models', return_value=['test-model']), \
                     mock.patch.object(runtime, 'baseline_integrity', return_value=True), \
                     mock.patch.object(runtime, 'vivado_tool', return_value='fake-vivado'), \
                     mock.patch.object(runtime, 'vram_gb', return_value=None), \
                     mock.patch.object(runtime.subprocess, 'run', return_value=mock.Mock(
                         returncode=returncode, stdout=banner)):
                    self.assertEqual(runtime.health()['ready'], expected)
        runtime.vivado_version.cache_clear()

    def test_health_requires_candidate_elaborator(self):
        with mock.patch.dict(os.environ, RTL_PROFILE='development', MODEL_NAME='m'), \
             mock.patch.object(runtime, 'models', return_value=['m']), \
             mock.patch.object(runtime, 'baseline_integrity', return_value=True), \
             mock.patch.object(runtime, 'vivado_tool', side_effect=lambda name: None if name == 'xelab' else 'tool'), \
             mock.patch.object(runtime, 'vivado_version', return_value='2026.1'):
            self.assertFalse(runtime.health()['ready'])


class ReferenceConcurrencyTests(unittest.TestCase):
    def test_parallel_reference_checks_preserve_every_sample_and_bound_concurrency(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ids = ['a', 'b', 'c']
            tasks = []
            for tid in ids:
                task = root/'tasks'/tid
                task.mkdir(parents=True)
                (task/'ref.sv').write_text('reference-' + tid, encoding='utf-8')
                (task/'task.json').write_text(json.dumps({'reference': 'ref.sv'}), encoding='utf-8')
                tasks.append(task/'task.json')
            outputs = []
            for workers in (1, 2):
                out = root/str(workers)
                results = out/'results'
                results.mkdir(parents=True)
                lock = threading.Lock()
                barrier = threading.Barrier(2) if workers == 2 else None
                active = peak = 0

                def judge(command, **kwargs):
                    nonlocal active, peak
                    self.assertTrue(kwargs['check'])
                    self.assertTrue(Path(command[1]).as_posix().endswith('selftest/judge.py'))
                    task = Path(command[command.index('--task') + 1])
                    candidate = Path(command[command.index('--solution') + 1])
                    result = Path(command[command.index('--json') + 1])
                    self.assertEqual(candidate.read_text(), (task/'ref.sv').read_text())
                    with lock:
                        active += 1
                        peak = max(peak, active)
                    if barrier:
                        barrier.wait(timeout=5)
                    time.sleep(.01)
                    result.write_text(json.dumps({'task_id': task.name, 'level': 3}), encoding='utf-8')
                    with lock:
                        active -= 1

                with mock.patch.object(evaluation.subprocess, 'run', side_effect=judge):
                    evaluation.run_references(tasks, ids, 2, out, results, 300, workers)
                self.assertEqual(peak, workers)
                self.assertEqual(len(list(results.glob('*.json'))), 6)
                outputs.append({p.name: p.read_text() for p in results.glob('*.json')})
            self.assertEqual(outputs[0], outputs[1])

    def test_reference_process_failure_is_not_reported_as_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = root/'task'
            task.mkdir()
            (task/'ref.sv').write_text('reference', encoding='utf-8')
            (task/'task.json').write_text(json.dumps({'reference': 'ref.sv'}), encoding='utf-8')
            with mock.patch.object(evaluation.subprocess, 'run', side_effect=subprocess.CalledProcessError(2, 'judge')):
                with self.assertRaises(subprocess.CalledProcessError):
                    evaluation.run_references([task/'task.json'], ['t'], 1, root/'out', root/'results', 300, 1)


class FakeModel(BaseHTTPRequestHandler):
    requests = []
    delay = 0
    replies = []
    stream_mode = 'normal'

    def log_message(self, *args):
        pass

    def emit(self, data):
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        try:
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        self.emit({'data': [{'id': 'contract-test-model'}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append(body)
        time.sleep(self.delay)
        reply = self.replies.pop(0) if self.replies else 'module TopModule(input a, output y); assign y=a; endmodule'
        if body.get('stream'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            def event(value):
                return ('data: ' + json.dumps(value, ensure_ascii=False) + '\r\n\r\n').encode('utf-8')
            packets = [
                event({'id': 'mock-stream', 'prompt_token_ids': [9, 10], 'choices': [
                    {'index': 0, 'delta': {'reasoning': '想'}, 'token_ids': [11]}]}),
                event({'choices': [{'index': 0, 'delta': {'content': reply}, 'token_ids': [12]}]}),
                event({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                       'usage': {'prompt_tokens': 2, 'completion_tokens': 2}}),
                b'data: [DONE]\n\n']
            try:
                if self.stream_mode == 'malformed':
                    packets = [b'data: {invalid}\n\n']
                elif self.stream_mode == 'broken':
                    packets = packets[:2]
                elif self.stream_mode == 'oversized':
                    packets = [b'data: ' + b' ' * (16 * 1024 * 1024 + 1)]
                elif self.stream_mode == 'long':
                    chunk = event({'id': 'chatcmpl-00000000000000000000000000000000', 'object': 'chat.completion.chunk',
                                   'created': 1790679259, 'model': 'rtl-qwen27b-awq',
                                   'choices': [{'index': 0, 'delta': {'content': 'token_text'},
                                                'logprobs': None, 'finish_reason': None, 'token_ids': [42]}]})
                    packets = [chunk]*8192 + packets[-2:]
                for packet in packets:
                    if self.stream_mode == 'split':
                        for byte in packet:
                            self.wfile.write(bytes([byte])); self.wfile.flush()
                    else:
                        self.wfile.write(packet); self.wfile.flush()
                    if self.stream_mode == 'drip':
                        for _ in range(100):
                            self.wfile.write(b': keepalive\n\n'); self.wfile.flush()
                            time.sleep(.02)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        self.emit({'model': 'contract-test-model', 'choices': [{'finish_reason': 'stop',
                   'message': {'content': reply}}],
                   'usage': {'prompt_tokens': 10, 'completion_tokens': 20}})


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ThreadingHTTPServer(('127.0.0.1', 0), FakeModel)
        cls.thread = threading.Thread(target=cls.model.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.model.shutdown()
        cls.model.server_close()
        cls.thread.join()

    def setUp(self):
        FakeModel.requests = []
        FakeModel.delay = 0
        FakeModel.replies = []
        FakeModel.stream_mode = 'normal'
        self.env = mock.patch.dict(os.environ, {
            'LLM_BASE_URL': f'http://127.0.0.1:{self.model.server_port}/v1',
            'MODEL_NAME': 'contract-test-model', 'RTL_PROFILE': 'development',
            'VIVADO_BIN': '/missing-vivado', 'RTL_REPAIRS': '1', 'FPGACHINA_TOKEN': 'local-test-token'})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_official_sources_match_pinned_bytes(self):
        self.assertEqual(evaluation.verify_upstream(), 'afd135e7ba5f6ec4c6d77e7c927c894327537801')
        self.assertTrue(runtime.baseline_integrity())

    def test_agent_and_official_baseline_same_model_no_hidden_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)/'task'
            task.mkdir()
            (task/'prompt.txt').write_text('Implement TopModule with a and y.', encoding='utf-8')
            for name in ('test.sv', 'ref.sv', 'task.json', 'feedback.txt'):
                (task/name).write_text('HIDDEN_REFERENCE_CANARY', encoding='utf-8')
            for mode in ('agent', 'baseline'):
                solution, events = runtime.run_job(mode, task, Path(td)/mode, 10)
                self.assertIn('endmodule', solution)
                events = [json.loads(line) for line in events.splitlines()]
                self.assertEqual(len([e for e in events if e['tool'] == 'llm']), 1)
                if mode == 'baseline':
                    self.assertEqual([e['tool'] for e in events], ['baseline_meta', 'llm'])
                    self.assertEqual(events[0]['max_tokens'], 8192)
            self.assertEqual(len(FakeModel.requests), 2)
            a, b = FakeModel.requests
            self.assertEqual(a['model'], b['model'])
            self.assertEqual(b['temperature'], 0)
            self.assertEqual(b['top_p'], 1)
            self.assertEqual(b['max_tokens'], 8192)
            self.assertEqual(b['messages'][1]['content'], 'Implement TopModule with a and y.')
            self.assertNotIn('HIDDEN_REFERENCE_CANARY', json.dumps(FakeModel.requests))
            with self.assertRaises(FileExistsError):
                runtime.run_job('agent', task, Path(td)/'agent', 10)

    def test_deadline_cancels_worker_and_service_can_continue(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)/'task'
            task.mkdir()
            (task/'prompt.txt').write_text('p', encoding='utf-8')
            FakeModel.delay = 2
            started = time.monotonic()
            solution, events = runtime.run_job('agent', task, Path(td)/'slow', .3)
            self.assertLess(time.monotonic()-started, 2)
            self.assertIn('deadline', events)
            FakeModel.delay = 0
            solution, _ = runtime.run_job('baseline', task, Path(td)/'next', 10)
            self.assertIn('endmodule', solution)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux process lifecycle')
    def test_http_sigterm_stops_active_worker(self):
        self.check_http_cleanup(False)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux external watchdog')
    def test_resource_watchdog_cancels_active_http_worker(self):
        self.check_http_cleanup(True)

    def check_http_cleanup(self, watchdog):
        with tempfile.TemporaryDirectory() as td:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            FakeModel.delay = 5
            env = dict(os.environ, EDA_TMP=td, PYTHONDONTWRITEBYTECODE='1')
            server = subprocess.Popen([sys.executable, str(ROOT/'submission/runtime.py'),
                                       'serve', '--port', str(port)], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True)
            children = []
            def post():
                try:
                    req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/solve',
                        data=json.dumps(dict(task_id='lifecycle', prompt='p', deadline_s=15)).encode(),
                        headers={'Authorization': 'Bearer local-test-token'})
                    with urllib.request.urlopen(req, timeout=20) as r: r.read()
                except (OSError, http.client.HTTPException):
                    pass
            request = None
            try:
                until = time.monotonic()+5
                while True:
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.1): break
                    except OSError:
                        self.assertLess(time.monotonic(), until, 'HTTP service not ready')
                        time.sleep(.02)
                request = threading.Thread(target=post, daemon=True)
                request.start()
                until = time.monotonic()+5
                while not FakeModel.requests:
                    self.assertLess(time.monotonic(), until, 'worker never called fixture')
                    time.sleep(.02)
                for path in Path('/proc').glob('[0-9]*/stat'):
                    try:
                        fields = path.read_text().split(') ', 1)[1].split()
                        if int(fields[1]) == server.pid: children.append(int(path.parent.name))
                    except (OSError, ValueError): pass
                self.assertTrue(children, 'no worker observed')
                if watchdog:
                    # Observe actual runtime workers; metrics are a fixed local
                    # backend fixture, not a claim about vLLM cancellation.
                    class Metrics(BaseHTTPRequestHandler):
                        def log_message(self, *args): pass
                        def do_GET(self):
                            busy = any(Path(f'/proc/{pid}/stat').exists() and
                                Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1][0] != 'Z'
                                for pid in children)
                            raw = HttpEvaluationTests.metrics(running=int(busy))
                            self.send_response(200); self.send_header('Content-Length', str(len(raw)))
                            self.end_headers(); self.wfile.write(raw)
                    backend = HttpEvaluationTests.serve(self, Metrics)
                    batch = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'], start_new_session=True)
                    try:
                        with tempfile.TemporaryDirectory() as evidence, mock.patch.object(evaluation, 'module',
                                return_value=types.SimpleNamespace(vram_gb=lambda: 40.)):
                            result = evaluation.supervise_http_batch(batch, server, backend, 'fixture',
                                Path(evidence)/'out', time.monotonic()+6)
                        self.assertEqual(result['stop_reason'], 'vram_limit')
                        self.assertTrue(result['backend_idle'])
                        self.assertFalse(result['forced_group_kill'])
                    finally:
                        try: os.killpg(batch.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        batch.wait(timeout=2)
                else:
                    server.send_signal(signal.SIGTERM)
                    server.wait(timeout=3)
                live = []
                for pid in children:
                    path = Path(f'/proc/{pid}/stat')
                    if path.exists() and path.read_text().split(') ', 1)[1][0] != 'Z': live.append(pid)
                self.assertEqual(live, [], f'SIGTERM left active workers: {live}')
                self.assertEqual(list(Path(td).iterdir()), [], 'request scratch not cleaned')
            finally:
                if server.poll() is None: server.kill()
                server.wait(timeout=3)
                for pid in children:
                    try: os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                if request: request.join(timeout=2)

    def test_http_auth_validation_and_repeated_modes(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), runtime.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def request(path, data=None, authorized=True):
            headers = {'Authorization': 'Bearer local-test-token'} if authorized else {}
            req = urllib.request.Request(base+path, headers=headers,
                                         data=None if data is None else json.dumps(data).encode())
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        try:
            for path in ('/v1/health', '/v1/solve'):
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    request(path, None if path.endswith('health') else {}, False)
                self.assertEqual(cm.exception.code, 401)
            self.assertFalse(request('/v1/health')['ready'])  # tool absent: not a fake ready=True
            with self.assertRaises(urllib.error.HTTPError) as cm:
                request('/v1/solve', dict(task_id='x', prompt='p', mode='typo'))
            self.assertEqual(cm.exception.code, 400)
            for i, mode in enumerate(('baseline', 'agent') * 100):
                data = request('/v1/solve', dict(task_id='../../unsafe-id', nonce=str(i),
                              mode=mode, prompt='p', interface='', deadline_s=10))
                self.assertEqual(data['task_id'], '../../unsafe-id')
                self.assertIn('endmodule', data['solution'])
                for line in data['trace'].splitlines():
                    self.assertIsInstance(json.loads(line), dict)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_http_body_receive_time_consumes_solve_deadline(self):
        entered = threading.Event()
        class ObservedHandler(runtime.Handler):
            def do_POST(self):
                entered.set()
                super().do_POST()
        server = ThreadingHTTPServer(('127.0.0.1', 0), ObservedHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for deadline in (.05, 1.0):
                with self.subTest(deadline=deadline), mock.patch.object(runtime, 'run_job', return_value=('candidate', '')) as job:
                    entered.clear()
                    connection = runtime.http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    body = json.dumps(dict(task_id='transport-delay', prompt='p', deadline_s=deadline)).encode()
                    connection.putrequest('POST', '/v1/solve')
                    connection.putheader('Authorization', 'Bearer local-test-token')
                    connection.putheader('Content-Length', str(len(body)))
                    connection.endheaders()
                    self.assertTrue(entered.wait(2))
                    time.sleep(.15)
                    connection.send(body)
                    response = connection.getresponse()
                    data = json.load(response)
                    connection.close()
                    self.assertEqual(response.status, 200)
                    self.assertGreaterEqual(data['elapsed_s'], .14)
                    if deadline < .15:
                        self.assertEqual(data['solution'], '')
                        job.assert_not_called()
                    else:
                        self.assertEqual(data['solution'], 'candidate')
                        self.assertLess(job.call_args.args[-1], .8)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_repair_uses_only_own_compile_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            task, out = Path(td)/'task', Path(td)/'out'
            task.mkdir()
            out.mkdir()
            (task/'prompt.txt').write_text('p', encoding='utf-8')
            with mock.patch.object(runtime.Path, 'cwd', return_value=Path(td)), \
                 mock.patch.object(runtime, 'vivado_tool', return_value='fake-xvlog'), \
                 mock.patch.object(runtime.subprocess, 'run', side_effect=[
                     mock.Mock(returncode=1, stdout='ERROR: own candidate invalid wire assignment'),
                     mock.Mock(returncode=0, stdout=''),
                     mock.Mock(returncode=0, stdout='')]), \
                 mock.patch.object(sys, 'path', [str(ROOT/'submission')] + sys.path):
                runtime.worker(task, out)
            self.assertEqual(len(FakeModel.requests), 2)
            self.assertIn('own candidate invalid wire assignment', FakeModel.requests[1]['messages'][1]['content'])
            events = [json.loads(s) for s in (out/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([s['rc'] for s in events if s['tool'] == 'lint'], [1, 0])

    def test_elaboration_error_gets_one_repair_without_external_testbench(self):
        first = 'module TopModule(input a, output y); missing_cell u(.a(a),.y(y)); endmodule'
        repaired = 'module TopModule(input a, output y); assign y=a; endmodule'
        with tempfile.TemporaryDirectory() as td:
            task, out = Path(td)/'task', Path(td)/'out'
            task.mkdir(); out.mkdir()
            (task/'prompt.txt').write_text('Implement a pass-through TopModule.', encoding='utf-8')
            FakeModel.replies = [first, repaired]
            with mock.patch.object(runtime.Path, 'cwd', return_value=Path(td)), \
                 mock.patch.object(runtime, 'vivado_tool', side_effect=lambda name: 'fake-' + name), \
                 mock.patch.object(runtime.subprocess, 'run', side_effect=[
                     mock.Mock(returncode=0, stdout=''),
                     mock.Mock(returncode=1, stdout='ERROR: missing_cell not found'),
                     mock.Mock(returncode=0, stdout=''),
                     mock.Mock(returncode=0, stdout='')]) as checked, \
                 mock.patch.object(sys, 'path', [str(ROOT/'submission')] + sys.path):
                runtime.worker(task, out)
            self.assertEqual(len(FakeModel.requests), 2)
            self.assertIn('missing_cell not found', FakeModel.requests[1]['messages'][1]['content'])
            self.assertEqual((out/'solution.v').read_text().strip(), repaired)
            elab = [c.args[0] for c in checked.call_args_list if c.args[0][0] == 'fake-xelab']
            self.assertEqual(len(elab), 2)
            self.assertTrue(all('work.TopModule' in c and 'tb' not in c for c in elab))

    def test_candidate_extraction_preserves_whole_source(self):
        source = ('`default_nettype none\n'
                  'module leaf(input wire a, output wire y); assign y=a; endmodule\n'
                  'module TopModule(input wire a, output wire y); // do not stop at endmodule in a comment\n'
                  'leaf u(.a(a),.y(y)); endmodule\n`default_nettype wire')
        for reply in (source, 'Here is the code:\n```systemverilog\n' + source + '\n```'):
            with self.subTest(fenced='```' in reply), tempfile.TemporaryDirectory() as td:
                FakeModel.requests = []
                task, out = Path(td)/'task', Path(td)/'out'
                task.mkdir(); out.mkdir()
                (task/'prompt.txt').write_text('Implement TopModule.', encoding='utf-8')
                FakeModel.replies = [reply]
                with mock.patch.object(runtime.Path, 'cwd', return_value=Path(td)), \
                     mock.patch.object(runtime, 'vivado_tool', return_value='tool'), \
                     mock.patch.object(runtime.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='')), \
                     mock.patch.object(sys, 'path', [str(ROOT/'submission')] + sys.path):
                    runtime.worker(task, out)
                self.assertEqual((out/'solution.v').read_text().strip(), source)
                self.assertEqual(len(FakeModel.requests), 1)

    def test_failed_elaboration_of_repair_preserves_first_candidate(self):
        first = 'module TopModule(input a, output y); assign y=a; endmodule'
        broken = 'module TopModule(input a, output y); missing_cell u(.a(a),.y(y)); endmodule'
        with tempfile.TemporaryDirectory() as td:
            task, out = Path(td)/'task', Path(td)/'out'
            task.mkdir(); out.mkdir()
            (task/'prompt.txt').write_text('p', encoding='utf-8')
            FakeModel.replies = [first, broken]
            with mock.patch.object(runtime.Path, 'cwd', return_value=Path(td)), \
                 mock.patch.object(runtime, 'vivado_tool', return_value='tool'), \
                 mock.patch.object(runtime.subprocess, 'run', side_effect=[
                     mock.Mock(returncode=1, stdout='ERROR: first candidate check failed'),
                     mock.Mock(returncode=0, stdout=''),
                     mock.Mock(returncode=1, stdout='ERROR: missing_cell not found')]), \
                 mock.patch.object(sys, 'path', [str(ROOT/'submission')] + sys.path):
                runtime.worker(task, out)
            self.assertEqual((out/'solution.v').read_text().strip(), first)

    def test_blank_or_partial_repair_does_not_erase_complete_candidate(self):
        first = 'module TopModule(input a, output y); assign y=a; endmodule'
        for broken in (None, '', 'module TopModule(input a, output y);'):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as td:
                task, out = Path(td)/'task', Path(td)/'out'
                task.mkdir(); out.mkdir()
                (task/'prompt.txt').write_text('Implement TopModule with a and y.', encoding='utf-8')
                FakeModel.replies = [first, broken]
                with mock.patch.object(runtime.Path, 'cwd', return_value=Path(td)), \
                     mock.patch.object(runtime, 'vivado_tool', return_value='fake-xvlog'), \
                     mock.patch.object(runtime.subprocess, 'run', return_value=mock.Mock(
                         returncode=1, stdout='ERROR: synthetic compile diagnostic')), \
                     mock.patch.object(sys, 'path', [str(ROOT/'submission')] + sys.path):
                    runtime.worker(task, out)
                self.assertEqual((out/'solution.v').read_text().strip(), first)

    def test_vram_does_not_sum_invisible_host_cards(self):
        own = mock.Mock(); own.name = 'card5'
        # The container exposes card5; host sysfs additionally exposes card3.
        def glob(path, pattern):
            if str(path).replace('\\', '/') == '/dev/dri':
                return [own] if pattern.startswith('card') else []
            return [Path('/sys/class/drm/card5/device/mem_info_vram_used'),
                    Path('/sys/class/drm/card3/device/mem_info_vram_used')]
        def read(path, *args, **kwargs):
            return str((4 if 'card5' in str(path) else 40) * 1024**3)
        with mock.patch.object(runtime.Path, 'glob', glob), \
             mock.patch.object(runtime.Path, 'read_text', read):
            self.assertEqual(runtime.vram_gb(), 4.0)

    def test_stream_utf8_boundaries_ids_and_no_replay(self):
        with tempfile.TemporaryDirectory() as td:
            FakeModel.stream_mode = 'split'
            path = Path(td)/'call.sse'
            body = dict(model='contract-test-model', messages=[], max_tokens=64, return_token_ids=True)
            result = runtime.chat_stream(body, path, 2)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['reasoning'], '想')
            self.assertIn('endmodule', result['content'])
            self.assertEqual(result['token_ids'], [11, 12])
            self.assertEqual(result['prompt_token_ids'], [9, 10])
            self.assertEqual(result['usage']['completion_tokens'], 2)
            with self.assertRaises(FileExistsError):
                runtime.chat_stream(body, path, 2)
            self.assertEqual(len(FakeModel.requests), 1)

    def test_stream_absolute_deadline_even_with_continuous_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            FakeModel.stream_mode = 'drip'
            path = Path(td)/'slow.sse'
            result = runtime.chat_stream(dict(model='contract-test-model', messages=[]), path, .25)
            self.assertEqual(result['status'], 'deadline')
            self.assertLess(result['elapsed_s'], .8)
            self.assertEqual(result['reasoning'], '想')
            self.assertIn(b'keepalive', path.read_bytes())
            self.assertEqual(len(FakeModel.requests), 1)

    def test_stream_disconnect_malformed_and_limit_are_not_success(self):
        with tempfile.TemporaryDirectory() as td:
            for mode, status in [('broken', 'incomplete'), ('malformed', 'stream_error'),
                                 ('oversized', 'stream_error')]:
                FakeModel.stream_mode = mode
                path = Path(td)/(mode+'.sse')
                result = runtime.chat_stream(dict(model='contract-test-model', messages=[]), path, 2)
                self.assertEqual(result['status'], status)
                self.assertLessEqual(path.stat().st_size, 16*1024*1024)

    def test_valid_long_stream_metadata_does_not_exhaust_evidence_limit(self):
        with tempfile.TemporaryDirectory() as td:
            FakeModel.stream_mode = 'long'
            path = Path(td)/'long.sse'
            result = runtime.chat_stream(dict(model='contract-test-model', messages=[], max_tokens=8192), path, 5)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(len(result['token_ids']), 8192)
            self.assertEqual(result['content'], 'token_text'*8192)
            self.assertGreater(path.stat().st_size, 2*1024*1024)

    def test_external_resource_stop_interrupts_request(self):
        with tempfile.TemporaryDirectory() as td:
            FakeModel.stream_mode = 'drip'
            stop = threading.Event()
            timer = threading.Timer(.1, stop.set)
            timer.start()
            try:
                result = runtime.chat_stream(dict(model='contract-test-model', messages=[]),
                                             Path(td)/'cancelled.sse', 3, stop)
            finally:
                timer.cancel(); timer.join()
            self.assertEqual(result['status'], 'cancelled')
            self.assertLess(result['elapsed_s'], .8)

    def test_worker_never_retries_broken_stream_or_submits_partial(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)/'task'; task.mkdir()
            (task/'prompt.txt').write_text('p', encoding='utf-8')
            FakeModel.stream_mode = 'broken'
            solution, events = runtime.run_job('agent', task, Path(td)/'out', 3)
            self.assertEqual(solution, '')
            self.assertEqual(len(FakeModel.requests), 1)
            self.assertIn('incomplete_response', events)
            self.assertGreater((Path(td)/'out/response-0.sse').stat().st_size, 0)

    def test_no_candidate_remains_empty_and_failed_complete_repair_preserves_first(self):
        first = 'module TopModule(input a, output y); assign y=a; endmodule'
        other = 'module TopModule(input a, output y); assign y=~a; endmodule'
        for replies, expected in [([None, None], ''), ([first, other], first)]:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as td:
                task, out = Path(td)/'task', Path(td)/'out'
                task.mkdir(); out.mkdir()
                (task/'prompt.txt').write_text('p', encoding='utf-8')
                FakeModel.replies = replies.copy()
                with mock.patch.object(runtime.Path, 'cwd', return_value=Path(td)), \
                     mock.patch.object(runtime, 'vivado_tool', return_value='fake-xvlog'), \
                     mock.patch.object(runtime.subprocess, 'run', return_value=mock.Mock(
                         returncode=1, stdout='ERROR: own candidate')), \
                     mock.patch.object(sys, 'path', [str(ROOT/'submission')] + sys.path):
                    runtime.worker(task, out)
                self.assertEqual((out/'solution.v').read_text().strip(), expected)

    def test_compile_receives_remaining_whole_task_budget(self):
        with tempfile.TemporaryDirectory() as td:
            task, out = Path(td)/'task', Path(td)/'out'
            task.mkdir(); out.mkdir()
            (task/'prompt.txt').write_text('p', encoding='utf-8')
            def compile_once(*args, **kwargs):
                self.assertGreater(kwargs['timeout'], 0)
                self.assertLessEqual(kwargs['timeout'], 1)
                raise subprocess.TimeoutExpired('xvlog', kwargs['timeout'])
            with mock.patch.object(runtime.Path, 'cwd', return_value=Path(td)), \
                 mock.patch.object(runtime, 'vivado_tool', return_value='fake-xvlog'), \
                 mock.patch.object(runtime.subprocess, 'run', side_effect=compile_once), \
                 mock.patch.object(sys, 'path', [str(ROOT/'submission')] + sys.path), \
                 mock.patch.dict(os.environ, RTL_DEADLINE_MONOTONIC=str(time.monotonic()+1)):
                runtime.worker(task, out)
            self.assertEqual(len(FakeModel.requests), 1)
            self.assertIn('deadline', (out/'trace.jsonl').read_text())

    def test_submission_requires_local_service_and_actual_vram(self):
        with mock.patch.dict(os.environ, RTL_PROFILE='submission', LLM_BASE_URL='https://example.com/v1'):
            with self.assertRaises(ValueError):
                runtime.endpoint()
        with mock.patch.dict(os.environ, RTL_PROFILE='submission'), mock.patch.object(runtime, 'vram_gb', return_value=None), mock.patch.object(runtime, 'vivado_tool', return_value='xvlog'):
            self.assertFalse(runtime.health()['ready'])

    def test_official_coefficients_exclusions_and_complete_batch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            levels = [0, 1, 2, 3, 3]
            for tid in ('a', 'bad'):
                for k, level in enumerate(levels):
                    item = dict(task_id=tid, level=level, coefficient=[0, .2, .7, 1][level], elapsed_s=1)
                    if tid == 'bad' or k == 4:
                        item['tool_error'] = 'FIXTURE_ERROR'
                    (root/f'agent.{tid}.s{k}.json').write_text(json.dumps(item), encoding='utf-8')
            s = evaluation.summarize(root, ['a', 'bad'], ['agent'], 5)['modes']['agent']
            self.assertEqual(s['scored_tasks'], 1)
            self.assertEqual(s['pass@1'], .475)
            self.assertEqual(s['pass@5'], 1)
            self.assertEqual(s['tool_errors'], 6)
            (root/'agent.a.s0.json').write_text(json.dumps(dict(task_id='a', passed=True)), encoding='utf-8')
            with self.assertRaises(ValueError):
                evaluation.summarize(root, ['a', 'bad'], ['agent'], 5)


if __name__ == '__main__':
    unittest.main()
