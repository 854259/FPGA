"""AMD-only whole submission wiring with synthetic transport/tools, no model or EDA."""
import contextlib
import http.client
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

PKG = Path(__file__).resolve().parents[1] / 'submission'
sys.path.insert(0, str(PKG / 'agent'))
sys.path.insert(0, str(PKG))
import runtime
import candidate_worker
import deadline_supervisor
import generation
import first_system_request

PROMPT = """I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

- input a
- input b
- output y

The module should implement the Karnaugh map below.
a
b 0 1
0 | 0 | 0 |
1 | 0 | 1 |
"""
GOOD = 'module TopModule(input a, input b, output y); assign y = a & b; endmodule' + '\n'
BAD = "module TopModule(input a, input b, output y); assign y = 1'b0; endmodule"


class SlowBody(io.BytesIO):
    def __init__(self, raw, delay=.4):
        super().__init__(raw)
        self.delay = delay

    def read(self, *args):
        time.sleep(self.delay)
        return super().read(*args)


class SyntheticIO:
    def __init__(self, scenario='normal'):
        self.scenario = scenario
        self.calls = []
        self.baseline_commands = []
        self.stage_commands = []
        self.slow_next = scenario in ('one_timeout', 'one_long_timeout')
        self.real_owned = deadline_supervisor.owned_command

    def open(self, request, *args, **kwargs):
        url = getattr(request, 'full_url', str(request))
        if url == 'http://127.0.0.1:8000/health':
            value = dict(status='ok')
        elif url == 'http://127.0.0.1:8000/v1/models':
            value = dict(data=[dict(id='synthetic-no-model')])
        elif url == 'http://127.0.0.1:8000/slots':
            value = [dict(id=0, is_processing=False)]
        elif url == 'http://127.0.0.1:8000/v1/chat/completions':
            if self.scenario in ('cancel_transport', 'cancel_recovery'):
                Path(os.environ['EDA_TMP']).parent.joinpath('cancel-at.json').write_text(
                    json.dumps(dict(monotonic=time.monotonic())))
                os.kill(os.getpid(), signal.SIGTERM)
            body = json.loads(request.data)
            self.calls.append(body)
            repair = '\nPrevious candidate:\n' in body['messages'][1]['content']
            value = dict(choices=[dict(message=dict(content=GOOD if repair else BAD),
                                      finish_reason='stop')],
                         usage=dict(prompt_tokens=1, completion_tokens=1))
            if self.slow_next:
                self.slow_next = False
                return SlowBody(json.dumps(value).encode(), 5 if self.scenario == 'one_long_timeout' else .4)
        else:
            raise AssertionError('Synthetic case attempted real/external transport: ' + url)
        return io.BytesIO(json.dumps(value).encode())

    def owned(self, argv, cwd, log, seconds, **kwargs):
        log, cwd = Path(log), Path(cwd)
        if self.scenario == 'cancel_native':
            def cancel():
                Path(os.environ['EDA_TMP']).parent.joinpath('cancel-at.json').write_text(
                    json.dumps(dict(monotonic=time.monotonic())))
                os.kill(os.getpid(), signal.SIGTERM)
            timer = threading.Timer(.15, cancel)
            timer.start()
            try:
                return self.real_owned([sys.executable, '-B', '-c', 'import time;time.sleep(20)'],
                                       cwd, log, seconds, **kwargs)
            finally:
                timer.cancel()
                timer.join()
        text = ''
        if len(argv) >= 6 and Path(argv[2]).name == 'baseline.py':
            self.baseline_commands.append(argv)
            out = Path(argv[4])
            (out / 'solution.v').write_text(GOOD)
            (out / 'trace.jsonl').write_text(json.dumps(dict(tool='synthetic_baseline_process')) + '\n')
        else:
            self.stage_commands.append(argv)
            if Path(argv[0]).name == 'xsim':
                if self.scenario == 'bad_probe':
                    text = 'No completed probe summary\n'
                else:
                    negative = "1'b0" in (cwd / 'dut.sv').read_text()
                    text = ('TABLE_FIRST row=3 expected=1 observed=0\n' if negative else '')
                    text += 'R2_PROBE_RESULT task=CurrentTask checks=8 mismatches=' + str(int(negative)) + '\n'
        log.write_text(text)
        return dict(returncode=0, launch_error=None, timeout=False, remaining_live_group=[],
                    elapsed_s=.001, log=str(log), log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
                    log_bytes=log.stat().st_size)

    @contextlib.contextmanager
    def installed(self):
        with patch.dict(os.environ, dict(MODEL_NAME='synthetic-no-model', RTL_REPAIRS='1',
                         RTL_MAX_TOKENS='8192', RTL_TEMPERATURE='0',
                         LLM_BASE_URL='http://127.0.0.1:8000/v1')), \
             patch.object(urllib.request, 'urlopen', self.open), \
             patch.object(deadline_supervisor, 'owned_command', self.owned), \
             patch.object(generation, 'vivado_tool', lambda name: '/synthetic-tools/' + name), \
             patch.object(runtime, 'vivado_tool', lambda name: '/synthetic-tools/' + name), \
             patch.object(runtime, 'vivado_version', lambda path: '2026.1'):
            yield self


def fixture(action, root, scenario):
    root = Path(root)
    os.environ.update(EDA_TMP=str(root / 'scratch'), RTL_EVIDENCE_DIR=str(root / 'evidence'),
                      FPGACHINA_TOKEN='synthetic-test-token')
    fake = SyntheticIO(scenario)
    if action == 'health':
        import ctypes
        assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0
        tool = root / 'synthetic-vivado'
        program = """#!/usr/bin/python3
import os,sys,time,json,subprocess
from pathlib import Path
root=Path(os.environ['EDA_TMP']).parent
child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(20)'],
                       start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def birth(pid):
    return dict(pid=pid,starttime=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19])
(root/'health-births.json').write_text(json.dumps(dict(tool=birth(os.getpid()),child=birth(child.pid),cwd=os.getcwd())))
print('vivado v2026.1 (synthetic CPU tool)',flush=True)
if os.environ['HEALTH_SCENARIO'].startswith('cancel_health'):time.sleep(20)
"""
        tool.write_text(program)
        tool.chmod(0o755)
        if scenario.startswith('cancel_health'):
            def cancel_health():
                end = time.monotonic() + 3
                while not (root / 'health-births.json').is_file() and time.monotonic() < end:
                    time.sleep(.01)
                (root / 'cancel-at.json').write_text(json.dumps(dict(monotonic=time.monotonic())))
                os.kill(os.getpid(), signal.SIGTERM)
            threading.Thread(target=cancel_health, daemon=True).start()
        def failed_group_cleanup(pgid, signum):
            (root / 'native-cleanup-failure.json').write_text(json.dumps(
                dict(pgid=pgid, signal=signum, at=time.monotonic())))
            raise PermissionError('Synthetic native group cleanup failure')
        native_failure = (patch.object(os, 'killpg', failed_group_cleanup)
                          if scenario == 'cancel_health_native_failure' else contextlib.nullcontext())
        with native_failure, patch.dict(os.environ, dict(MODEL_NAME='synthetic-no-model', HEALTH_SCENARIO=scenario,
                                         LLM_BASE_URL='http://127.0.0.1:8000/v1')), \
             patch.object(urllib.request, 'urlopen', fake.open), \
             patch.object(runtime, 'vivado_tool', lambda name: str(tool)), \
             patch.object(runtime, 'vram_gb', lambda: 0):
            server = runtime.HTTPServer(('127.0.0.1', 0), runtime.Handler)
            print(json.dumps(dict(port=server.server_port, pid=os.getpid())), flush=True)
            server.serve_forever()
        return
    with fake.installed():
        if scenario == 'cancel_recovery':
            actual_idle = candidate_worker.model_idle
            def failed_recovery(budget, opener, *, allow_busy=False):
                if allow_busy:
                    raise RuntimeError('Synthetic recovery failure after cancellation')
                return actual_idle(budget, opener)
            candidate_worker.model_idle = failed_recovery
        if action == 'http':
            server = runtime.HTTPServer(('127.0.0.1', 0), runtime.Handler)
            print(json.dumps(dict(port=server.server_port, pid=os.getpid())), flush=True)
            server.serve_forever()
        else:
            sys.argv = ['runtime.py', 'run', str(root / 'input'), str(root / 'cli-out')]
            runtime.main()
            print(json.dumps(dict(client_calls=len(fake.calls), baseline_commands=len(fake.baseline_commands))))


class SubmissionChainTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ['RTL_TEST_OUTPUT_ROOT']) / self._testMethodName
        self.root.mkdir(parents=True, exist_ok=False)
        self.inp = self.root / 'input'
        self.inp.mkdir()
        (self.inp / 'prompt.txt').write_text(PROMPT)
        (self.inp / 'interface.txt').write_text('')
        (self.inp / 'task.json').write_text('Forbidden evaluator metadata')
        (self.inp / 'reference').mkdir()
        (self.inp / 'reference/solution.v').write_text('Forbidden reference marker')
        runtime.BLOCKED = None
        self.env = patch.dict(os.environ, dict(EDA_TMP=str(self.root / 'scratch'),
                              RTL_EVIDENCE_DIR=str(self.root / 'evidence')))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.assertEqual(deadline_supervisor.descendants(os.getpid()), {})

    def request(self, port, data=None, token=True, path='/v1/solve'):
        body = None if data is None else json.dumps(data).encode()
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer synthetic-test-token'
        req = urllib.request.Request('http://127.0.0.1:' + str(port) + path,
                                     data=body, headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    @contextlib.contextmanager
    def server(self, scenario='normal', action='http'):
        stderr = (self.root / 'server.stderr').open('wb')
        proc = subprocess.Popen([sys.executable, '-B', __file__, '--fixture', action,
                                 str(self.root), scenario], stdout=subprocess.PIPE,
                                stderr=stderr, text=True)
        try:
            line = proc.stdout.readline()
            self.assertTrue(line, 'HTTP fixture did not report startup')
            start = json.loads(line)
            (self.root / 'server-start.json').write_text(json.dumps(start))
            yield start['port'], proc
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()
            stderr.close()
            (self.root / 'server-exit.json').write_text(json.dumps(
                dict(pid=proc.pid, returncode=proc.returncode, reaped=True)))

    def data(self, nonce, **extra):
        return dict(task_id='opaque/id:without-semantic-role', nonce=nonce,
                    prompt=PROMPT, interface='', deadline_s=5, **extra)

    def test_direct_complete_table_repair_and_next_request_reset(self):
        fake = SyntheticIO()
        original_request = urllib.request.Request
        original_read = Path.read_text
        reads = []
        def guarded_read(path, *args, **kwargs):
            if path.is_relative_to(self.inp):
                rel = path.relative_to(self.inp).as_posix()
                self.assertIn(rel, ('prompt.txt', 'interface.txt'))
                reads.append(rel)
            return original_read(path, *args, **kwargs)
        with fake.installed(), patch.object(Path, 'read_text', guarded_read):
            first = runtime.run_job('agent', self.inp, self.root / 'out1', 5)
            second = runtime.run_job('agent', self.inp, self.root / 'out2', 5)
        self.assertEqual(first[0], GOOD)
        self.assertEqual(second[0], GOOD)
        self.assertEqual(len(fake.calls), 4)
        for index, body in enumerate(fake.calls):
            suffix = first_system_request.SYSTEM_SUFFIX in body['messages'][0]['content']
            self.assertEqual(suffix, index % 2 == 0)
            self.assertEqual(body['max_tokens'], 8192)
            if index % 2:
                self.assertIn("expected y=1, observed y=0", body['messages'][1]['content'])
                self.assertIn(BAD, body['messages'][1]['content'])
        self.assertIs(urllib.request.Request, original_request)
        self.assertNotIn('map_feedback', generation.__dict__)
        self.assertTrue(reads)
        self.assertEqual(len(list((self.root / 'scratch').iterdir())), 0)
        for out in [self.root / 'out1', self.root / 'out2']:
            self.assertEqual(len(json.loads((out / 'requests.json').read_text())), 2)
            self.assertTrue(json.loads((out / 'OWNED_CLEANUP.json').read_text())['verified'])
            self.assertTrue(json.loads((out / 'MODEL_RECOVERY.json').read_text())['complete'])

    def test_http_persistent_agent_baseline_and_auth(self):
        with self.server() as (port, proc):
            status, _ = self.request(port, self.data('unauthorized'), token=False)
            self.assertEqual(status, 401)
            for nonce in ['first', 'second']:
                status, value = self.request(port, self.data(nonce))
                self.assertEqual(status, 200)
                self.assertEqual(set(value), {'task_id', 'solution', 'trace', 'elapsed_s'})
                self.assertEqual(value['solution'], GOOD)
            status, value = self.request(port, self.data('baseline', mode='baseline'))
            self.assertEqual(status, 200)
            self.assertEqual(value['solution'], GOOD)
            self.assertIn('synthetic_baseline_process', value['trace'])
            self.assertNotIn('agent_meta', value['trace'])
            status, value = self.request(port, path='/v1/health')
            self.assertEqual(status, 200)
            self.assertTrue(value['ready'])
            self.assertIsNone(proc.poll())
        evidence = list((self.root / 'evidence').glob('request-*'))
        self.assertEqual(len(evidence), 3)
        self.assertEqual(sum((p / 'out/requests.json').exists() for p in evidence), 2)
        self.assertEqual(sum((p / 'out/BASELINE_SUPERVISION.json').exists() for p in evidence), 1)

    def test_http_real_deadline_then_next_request_same_service(self):
        with self.server('one_long_timeout') as (port, proc):
            data = self.data('timeout')
            data['deadline_s'] = 3
            started = time.monotonic()
            status, value = self.request(port, data)
            elapsed = time.monotonic() - started
            (self.root / 'request-wall.json').write_text(json.dumps(dict(
                deadline_s=data['deadline_s'], elapsed_s=elapsed)))
            self.assertLess(elapsed, data['deadline_s'])
            self.assertEqual(status, 200)
            self.assertLess(value['elapsed_s'], data['deadline_s'])
            self.assertEqual(value['solution'], '')
            self.assertIn('"event": "deadline"', value['trace'])
            status, value = self.request(port, self.data('after-timeout'))
            self.assertEqual(status, 200)
            self.assertEqual(value['solution'], GOOD)
            self.assertIsNone(proc.poll())
        evidence = list((self.root / 'evidence').glob('request-*'))
        failed = [p for p in evidence if (p / 'out/SHARED_BUDGET_EXIT.json').exists()]
        self.assertEqual(len(failed), 1)
        calls = json.loads((failed[0] / 'out/requests.json').read_text())
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]['response_received'])
        self.assertTrue(json.loads((failed[0] / 'out/MODEL_RECOVERY.json').read_text())['complete'])

    def test_short_http_recovery_cannot_borrow_time_past_deadline(self):
        with self.server('one_long_timeout') as (port, proc):
            data = self.data('short-timeout')
            data['deadline_s'] = .1
            started = time.monotonic()
            status, value = self.request(port, data)
            elapsed = time.monotonic() - started
            (self.root / 'request-wall.json').write_text(json.dumps(
                dict(deadline_s=data['deadline_s'], elapsed_s=elapsed, status=status)))
            self.assertLess(elapsed, data['deadline_s'])
            self.assertEqual(status, 503)
            status, _ = self.request(port, self.data('after-block'))
            self.assertEqual(status, 503)
            self.assertIsNone(proc.poll())
        records = list((self.root / 'evidence').glob('request-*/out/MODEL_RECOVERY.json'))
        self.assertEqual(len(records), 1)
        self.assertFalse(json.loads(records[0].read_text())['complete'])

    def test_solve_preserves_request_start_before_body_parsing(self):
        with SyntheticIO().installed():
            started = time.monotonic() - 1
            result = runtime.solve(self.data('inherited-start'), parent_started=started)
        clock_file = next((self.root / 'evidence').glob('request-*/out/SOLVE_CLOCK.json'))
        clock = json.loads(clock_file.read_text())
        self.assertEqual(clock['started_monotonic'], started)
        self.assertLessEqual(clock['cleanup_deadline_monotonic'], started + 5)
        self.assertGreaterEqual(result['elapsed_s'], 1)
        self.assertEqual(result['solution'], GOOD)

    def test_http_baseline_receives_the_same_cleanup_ceiling(self):
        fake = SyntheticIO()
        observed = []
        def command(*args, **kwargs):
            observed.append(kwargs)
            return fake.owned(*args, **kwargs)
        with fake.installed(), patch.object(deadline_supervisor, 'owned_command', command):
            result = runtime.solve(self.data('baseline-ceiling', mode='baseline'))
        clock = json.loads(next((self.root / 'evidence').glob('request-*/out/SOLVE_CLOCK.json')).read_text())
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]['deadline'], clock['work_deadline_monotonic'])
        self.assertEqual(observed[0]['cleanup_deadline'], clock['cleanup_deadline_monotonic'])
        self.assertLess(clock['cleanup_deadline_monotonic'], clock['started_monotonic'] + 5)
        self.assertEqual(result['solution'], GOOD)

    def test_native_budget_forwards_cleanup_ceiling_and_keeps_cli_default(self):
        import shared_budget
        seen = []
        def command(*args, **kwargs):
            seen.append(kwargs)
            return {}
        with patch.object(deadline_supervisor, 'owned_command', command):
            bounded = shared_budget.SolveBudget(3, clock=lambda: 100, cleanup_deadline=105)
            bounded.owned_operation(command)([], self.root, self.root / 'unused.log', 1)
        self.assertEqual(seen[0]['deadline'], 103)
        self.assertEqual(seen[0]['cleanup_deadline'], 105)
        default = shared_budget.SolveBudget(300, clock=lambda: 100)
        self.assertEqual(default.end, 400)
        self.assertEqual(default.cleanup_end, 410)
        capped = shared_budget.SolveBudget(3, clock=lambda: 100, cleanup_deadline=120)
        self.assertEqual(capped.cleanup_end, 113)
        for value in (102, True, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                shared_budget.SolveBudget(3, clock=lambda: 100, cleanup_deadline=value)

    def test_malformed_probe_blocks_following_request_without_retry(self):
        with self.server('bad_probe') as (port, proc):
            status, _ = self.request(port, self.data('malformed'))
            self.assertEqual(status, 503)
            status, _ = self.request(port, self.data('must-not-dispatch'))
            self.assertEqual(status, 503)
            status, value = self.request(port, path='/v1/health')
            self.assertEqual(status, 200)
            self.assertFalse(value['ready'])
            self.assertIsNone(proc.poll())
        attempts = [p for p in (self.root / 'evidence').glob('request-*/out/requests.json')]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(json.loads(attempts[0].read_text())), 1)

    def test_cli_uses_same_selected_chain(self):
        with (self.root / 'cli.stdout').open('wb') as stdout, (self.root / 'cli.stderr').open('wb') as stderr:
            proc = subprocess.Popen([sys.executable, '-B', __file__, '--fixture', 'cli',
                                     str(self.root), 'normal'], stdout=stdout, stderr=stderr)
            self.assertEqual(proc.wait(timeout=15), 0)
        result = json.loads((self.root / 'cli.stdout').read_text())
        self.assertEqual(result, dict(client_calls=2, baseline_commands=0))
        self.assertEqual((self.root / 'cli-out/solution.v').read_text(), GOOD)

    def test_sigterm_native_and_recovery_share_first_cancel_deadline(self):
        real_owned = deadline_supervisor.owned_command
        def interrupted(task, out, work, budget):
            import ctypes
            self.assertEqual(ctypes.CDLL(None).prctl(36, 1, 0, 0, 0), 0)
            candidate_worker.save(out / 'requests.json', [dict(dispatch_started=True,
                                   response_received=False, server_received_count=None)])
            timer = threading.Timer(.15, lambda: os.kill(os.getpid(), signal.SIGTERM))
            timer.start()
            try:
                real_owned([sys.executable, '-B', '-c', 'import time;time.sleep(20)'],
                           task, out / 'native.log', budget.remaining(), deadline=budget.end,
                           cleanup_deadline=budget.end + 10)
            finally:
                timer.cancel()
                timer.join()
        fake = SyntheticIO()
        with fake.installed(), patch.object(candidate_worker, 'run', interrupted):
            with self.assertRaises(InterruptedError) as caught:
                runtime.run_job('agent', self.inp, self.root / 'out', 30)
        start = caught.exception.cancelled_at_monotonic
        cleanup = json.loads((self.root / 'out/OWNED_CLEANUP.json').read_text())
        recovery = json.loads((self.root / 'out/MODEL_RECOVERY.json').read_text())
        self.assertAlmostEqual(cleanup['deadline_monotonic'], start + 10, places=5)
        self.assertAlmostEqual(recovery['cleanup_deadline_monotonic'], start + 10, places=5)
        self.assertTrue(cleanup['verified'] and recovery['complete'])
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(fake.calls, [])

    def cancellation_service_case(self, scenario):
        with self.server(scenario) as (port, proc):
            started = time.monotonic()
            try:
                self.request(port, self.data('cancel-service'))
            except (OSError, http.client.RemoteDisconnected):
                pass
            self.assertEqual(proc.wait(timeout=2), 1)
            self.assertFalse(Path('/proc', str(proc.pid)).exists())
            cancelled = json.loads((self.root / 'cancel-at.json').read_text())['monotonic']
            self.assertLess(time.monotonic() - cancelled, 2)
            records = list((self.root / 'evidence').glob('request-*/out/OWNED_CLEANUP.json'))
            self.assertEqual(len(records), 1)
            cleanup = json.loads(records[0].read_text())
            self.assertTrue(cleanup['verified'])
            self.assertLessEqual(cleanup['completed_monotonic'], cancelled + 10.1)
            print(json.dumps(dict(case=scenario, service_retired=True,
                                  elapsed_s=time.monotonic() - started, cleanup=cleanup)))

    def test_http_sigterm_during_transport_exits_service(self):
        self.cancellation_service_case('cancel_transport')

    def test_http_sigterm_during_native_exits_service(self):
        self.cancellation_service_case('cancel_native')

    def test_http_sigterm_with_failed_recovery_still_exits_service(self):
        self.cancellation_service_case('cancel_recovery')
        records = list((self.root / 'evidence').glob('request-*/out/MODEL_RECOVERY.json'))
        self.assertFalse(json.loads(records[0].read_text())['complete'])
        self.assertTrue(list((self.root / 'evidence').glob('request-*/out/SCRATCH_RETAINED.json')))

    def test_supervisor_never_restarts_model_or_agent_after_startup(self):
        source = (PKG / 'serve/serve_all.sh').read_text()
        prefix = source.split('# ---- 首次启动 ----')[0]
        loop = source[source.index('while true; do'):].replace('while true; do', 'for cycle in 1 2; do', 1)
        for kind in ('model', 'agent'):
            for alive in (True, False):
                with self.subTest(kind=kind, alive=alive):
                    folder = self.root / (kind + ('-alive' if alive else '-exited'))
                    folder.mkdir()
                    proc = subprocess.Popen([sys.executable, '-B', '-c', 'import time;time.sleep(20)'])
                    pid = proc.pid
                    try:
                        stat = Path('/proc', str(pid), 'stat').read_text()
                        birth = stat.rsplit(')', 1)[1].split()[19]
                        (folder / 'child-start.json').write_text(json.dumps(
                            dict(pid=pid, starttime=birth)))
                        if not alive:
                            proc.terminate()
                            proc.wait(timeout=2)
                        (folder / 'agent-serve.pid').write_text(str(pid))
                        (folder / 'llama-server.pid').write_text(str(pid))
                        overrides = """
sleep() { :; }
model_state() { return """ + ('2' if kind == 'model' else '0') + """; }
agent_state() { return """ + ('2' if kind == 'agent' else '0') + """; }
pid_is_ours() { return 0; }
stop_ours() { echo called >> "$LOG_DIR/unexpected-stop"; return 0; }
start_agent() { echo agent >> "$LOG_DIR/start"; return 0; }
start_model() { echo model >> "$LOG_DIR/start"; return 0; }
FAIL_MODEL=0
FAIL_AGENT=0
NOTREADY_AGENT=0
"""
                        control = folder / 'guard-control.sh'
                        control.write_text(prefix + overrides + loop)
                        result = subprocess.run(['/bin/bash', str(control)], cwd=folder,
                            env=dict(os.environ, KIT=str(PKG.parent), LOG_DIR=str(folder),
                                     FPGACHINA_TOKEN='synthetic-test-token'), capture_output=True,
                            text=True, timeout=5)
                        (folder / 'stdout.txt').write_text(result.stdout)
                        (folder / 'stderr.txt').write_text(result.stderr)
                        observed = dict(kind=kind, alive=alive, pid=pid,
                                        returncode=result.returncode,
                                        stopped=(folder / 'unexpected-stop').exists(),
                                        restart_called=(folder / 'start').exists(),
                                        still_alive=proc.poll() is None)
                        (folder / 'observed.json').write_text(json.dumps(observed))
                        print(json.dumps(observed))
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertFalse(observed['stopped'])
                        self.assertFalse(observed['restart_called'])
                        self.assertEqual(observed['still_alive'], alive)
                    finally:
                        if proc.poll() is None:
                            proc.terminate()
                        proc.wait(timeout=2)
                        (folder / 'child-exit.json').write_text(json.dumps(
                            dict(pid=pid, returncode=proc.returncode, reaped=True,
                                 proc_missing=not Path('/proc', str(pid)).exists())))

    def health_process_case(self, scenario):
        import ctypes
        import shutil
        import tempfile
        self.assertEqual(ctypes.CDLL(None).prctl(36, 1, 0, 0, 0), 0)
        try:
            with self.server(scenario, action='health') as (port, proc):
                if scenario.startswith('cancel_health'):
                    with self.assertRaises((OSError, http.client.RemoteDisconnected)):
                        self.request(port, path='/v1/health')
                    self.assertEqual(proc.wait(timeout=2), 1)
                else:
                    status, value = self.request(port, path='/v1/health')
                    self.assertEqual(status, 200)
                    self.assertTrue(value['ready'])
                births = json.loads((self.root / 'health-births.json').read_text())
                for key in ('tool', 'child'):
                    self.assertIsNone(deadline_supervisor.process_record(births[key]['pid']))
                print(json.dumps(dict(case=scenario, tool_and_child_retired=True, births=births)))
        finally:
            # Negative-control cleanup only: these exact fixture births are
            # adopted by this test after its HTTP process exits.
            path = self.root / 'health-births.json'
            if path.is_file():
                births = json.loads(path.read_text())
                for key in ('tool', 'child'):
                    row = births[key]
                    current = deadline_supervisor.process_record(row['pid'])
                    if current and current['starttime'] == row['starttime']:
                        try:
                            os.kill(row['pid'], signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        end = time.monotonic() + 2
                        while deadline_supervisor.process_record(row['pid']) and time.monotonic() < end:
                            try:
                                os.waitpid(row['pid'], os.WNOHANG)
                            except ChildProcessError:
                                pass
                            time.sleep(.01)
                old_scratch = Path(births['cwd'])
                if (old_scratch.parent == Path(tempfile.gettempdir()) and
                        old_scratch.name.startswith('rtl-version-') and old_scratch.is_dir()):
                    self.assertEqual(list(old_scratch.iterdir()), [])
                    old_scratch.rmdir()

    def test_health_version_reaps_detached_child(self):
        self.health_process_case('normal_health')

    def test_health_sigterm_reaps_tool_and_exits(self):
        self.health_process_case('cancel_health')

    def test_health_cancellation_survives_native_cleanup_failure(self):
        self.health_process_case('cancel_health_native_failure')
        failure = json.loads((self.root / 'native-cleanup-failure.json').read_text())
        cancel = json.loads((self.root / 'cancel-at.json').read_text())
        self.assertGreaterEqual(failure['at'], cancel['monotonic'])
        receipt = next((self.root / 'evidence').glob('health-*/OWNED_CLEANUP.json'))
        cleanup = json.loads(receipt.read_text())
        self.assertTrue(cleanup['verified'])
        self.assertLessEqual(cleanup['deadline_monotonic'], cancel['monotonic'] + 10.1)

    def test_endpoint_rejects_remote_in_all_profiles(self):
        for profile in ('submission', 'development', 'other'):
            for base in ('http://model.invalid/v1', 'https://model.invalid/v1'):
                with self.subTest(profile=profile, base=base), patch.dict(
                        os.environ, dict(RTL_PROFILE=profile, LLM_BASE_URL=base)):
                    with self.assertRaisesRegex(ValueError, 'loopback'):
                        runtime.endpoint()

    def test_models_rejects_development_remote_before_http(self):
        with patch.dict(os.environ, dict(RTL_PROFILE='development',
                        LLM_BASE_URL='https://model.invalid/v1')), patch.object(
                        urllib.request, 'urlopen', return_value=io.BytesIO(b'{"data":[]}')) as opener:
            with self.assertRaisesRegex(ValueError, 'loopback'):
                runtime.models()
            opener.assert_not_called()

    def test_run_job_rejects_remote_before_baseline_work(self):
        with patch.dict(os.environ, dict(RTL_PROFILE='development',
                        LLM_BASE_URL='https://model.invalid/v1')), patch.object(
                        runtime, 'baseline_integrity', side_effect=AssertionError('baseline work reached')) as baseline:
            with self.assertRaisesRegex(ValueError, 'loopback'):
                runtime.run_job('baseline', self.inp, self.root / 'out', 1)
            baseline.assert_not_called()
        self.assertFalse((self.root / 'out').exists())

    def test_local_endpoints_remain_valid_in_all_profiles(self):
        for profile in ('submission', 'development', 'other'):
            for base in ('http://127.0.0.1:8000/v1/', 'http://localhost:8000/v1',
                         'http://[::1]:8000/v1'):
                with self.subTest(profile=profile, base=base), patch.dict(
                        os.environ, dict(RTL_PROFILE=profile, LLM_BASE_URL=base)):
                    self.assertEqual(runtime.endpoint(), base.rstrip('/'))
        with patch.dict(os.environ, dict(RTL_PROFILE='development',
                        LLM_BASE_URL='http://127.0.0.1:8000/v1/')), patch.object(
                        urllib.request, 'urlopen', return_value=io.BytesIO(
                            b'{"data":[{"id":"synthetic-no-model"}]}')) as opener:
            self.assertEqual(runtime.models(), ['synthetic-no-model'])
            opener.assert_called_once_with('http://127.0.0.1:8000/v1/models', timeout=2)

    def test_detached_tool_child_is_reaped_before_next_request(self):
        real_owned = deadline_supervisor.owned_command
        def detached(task, out, work, budget):
            import ctypes
            self.assertEqual(ctypes.CDLL(None).prctl(36, 1, 0, 0, 0), 0)
            code = ("import subprocess,sys,time,pathlib,json;"
                    "p=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(20)'],start_new_session=True);"
                    "f=pathlib.Path('/proc/'+str(p.pid)+'/stat').read_text().rsplit(')',1)[1].split();"
                    "pathlib.Path(sys.argv[1]).write_text(json.dumps(dict(pid=p.pid,starttime=f[19])));"
                    "time.sleep(.05)")
            result = real_owned([sys.executable, '-B', '-c', code, str(out / 'detached.json')],
                                task, out / 'native.log', budget.remaining(), deadline=budget.end,
                                cleanup_deadline=budget.end + 10)
            self.assertEqual(result['returncode'], 0)
            self.assertEqual(result['remaining_live_group'], [])
        with SyntheticIO().installed(), patch.object(candidate_worker, 'run', detached):
            runtime.run_job('agent', self.inp, self.root / 'out', 5)
        birth = json.loads((self.root / 'out/detached.json').read_text())
        cleanup = json.loads((self.root / 'out/OWNED_CLEANUP.json').read_text())
        self.assertTrue(cleanup['verified'])
        self.assertTrue(any(r['pid'] == birth['pid'] and r['starttime'] == birth['starttime']
                            for r in cleanup['recorded']))
        self.assertIsNone(deadline_supervisor.process_record(birth['pid']))
        self.assertEqual(list((self.root / 'scratch').iterdir()), [])


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fixture':
        fixture(*sys.argv[2:])
    else:
        if sys.platform != 'linux':
            raise SystemExit('Run only on the authorized AMD server')
        unittest.main(verbosity=2)

