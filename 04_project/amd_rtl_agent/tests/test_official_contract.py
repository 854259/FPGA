"""Protocol integration tests use a local fake model, never a paid endpoint."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import sys
import subprocess
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


class VivadoHealthTests(unittest.TestCase):
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
                     mock.Mock(returncode=0, stdout='')]), \
                 mock.patch.object(sys, 'path', [str(ROOT/'submission')] + sys.path):
                runtime.worker(task, out)
            self.assertEqual(len(FakeModel.requests), 2)
            self.assertIn('own candidate invalid wire assignment', FakeModel.requests[1]['messages'][1]['content'])
            events = [json.loads(s) for s in (out/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([s['rc'] for s in events if s['tool'] == 'lint'], [1, 0])

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
