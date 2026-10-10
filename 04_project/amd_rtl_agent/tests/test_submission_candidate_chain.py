"""AMD-only whole submission wiring with synthetic transport/tools, no model or EDA."""
import contextlib
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
    def read(self, *args):
        time.sleep(.4)
        return super().read(*args)


class SyntheticIO:
    def __init__(self, scenario='normal'):
        self.scenario = scenario
        self.calls = []
        self.baseline_commands = []
        self.stage_commands = []
        self.slow_next = scenario == 'one_timeout'

    def open(self, request, *args, **kwargs):
        url = getattr(request, 'full_url', str(request))
        if url == 'http://127.0.0.1:8000/health':
            value = dict(status='ok')
        elif url == 'http://127.0.0.1:8000/v1/models':
            value = dict(data=[dict(id='synthetic-no-model')])
        elif url == 'http://127.0.0.1:8000/slots':
            value = [dict(id=0, is_processing=False)]
        elif url == 'http://127.0.0.1:8000/v1/chat/completions':
            body = json.loads(request.data)
            self.calls.append(body)
            repair = '\nPrevious candidate:\n' in body['messages'][1]['content']
            value = dict(choices=[dict(message=dict(content=GOOD if repair else BAD),
                                      finish_reason='stop')],
                         usage=dict(prompt_tokens=1, completion_tokens=1))
            if self.slow_next:
                self.slow_next = False
                return SlowBody(json.dumps(value).encode())
        else:
            raise AssertionError('Synthetic case attempted real/external transport: ' + url)
        return io.BytesIO(json.dumps(value).encode())

    def owned(self, argv, cwd, log, seconds, **kwargs):
        log, cwd = Path(log), Path(cwd)
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
    with fake.installed():
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
    def server(self, scenario='normal'):
        stderr = (self.root / 'server.stderr').open('wb')
        proc = subprocess.Popen([sys.executable, '-B', __file__, '--fixture', 'http',
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
        with self.server('one_timeout') as (port, proc):
            data = self.data('timeout')
            data['deadline_s'] = .1
            status, value = self.request(port, data)
            self.assertEqual(status, 200)
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

