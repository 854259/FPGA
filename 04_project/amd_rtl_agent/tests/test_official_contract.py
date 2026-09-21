"""Protocol integration tests use a local fake model, never a paid endpoint."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import sys
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


class FakeModel(BaseHTTPRequestHandler):
    requests = []
    delay = 0

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
        self.emit({'model': 'contract-test-model', 'choices': [{'finish_reason': 'stop',
                   'message': {'content': 'module TopModule(input a, output y); assign y=a; endmodule'}}],
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
                     mock.Mock(returncode=0, stdout='')]), \
                 mock.patch.object(sys, 'path', [str(ROOT/'submission')] + sys.path):
                runtime.worker(task, out)
            self.assertEqual(len(FakeModel.requests), 2)
            self.assertIn('own candidate invalid wire assignment', FakeModel.requests[1]['messages'][1]['content'])
            events = [json.loads(s) for s in (out/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([s['rc'] for s in events if s['tool'] == 'lint'], [1, 0])

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
