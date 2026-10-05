"""Fixed zero-real-model HTTP/CLI controls for the unchanged official B arm."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

import official_baseline_arm_20261005 as arm


CODE = 'module TopModule(input a, output y); assign y = a; endmodule\n'
PROMPT = 'Implement a combinational wire from a to y.'
INTERFACE = 'module TopModule(input a, output y); endmodule\n'
SYSTEM = ('You are an expert Verilog designer. Reply with a single synthesizable '
          'SystemVerilog module named TopModule. Output only code — no prose, no '
          'markdown fences.')
CASES = ['fenced_code', 'missing_interface', 'null_length', 'http_error',
         'invalid_json', 'body_hang', 'recovery']


def preflight(args):
    resource = arm.resource_module()
    resource.check_resource(args.resource_check, args.kit, first=True)
    out = args.out.resolve(); assert not out.exists(); out.mkdir(parents=True)
    requests, gets, rows = [], [], []
    state = {'case': None}
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def send(self, body, status=200):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            gets.append({'case': state['case'], 'path': self.path})
            if self.path == '/v1/models':
                self.send(json.dumps({'data': [{'id': arm.MODEL}]}).encode())
            else:
                self.send(b'{}', 404)

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            case = state['case']
            requests.append({'case': case, 'path': self.path, 'payload': json.loads(body)})
            if self.path != '/v1/chat/completions':
                self.send(b'{}', 404); return
            if case == 'http_error':
                self.send(b'{"error":"frozen synthetic failure"}', 500); return
            if case == 'invalid_json':
                self.send(b'not-json'); return
            if case == 'body_hang':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', '1000')
                self.end_headers(); self.wfile.write(b'{'); self.wfile.flush()
                release.wait(5); return
            content = None if case == 'null_length' else CODE
            if case == 'fenced_code':
                fence = chr(96)*3
                content = 'Here is code:\n'+fence+'sv\n'+CODE+fence
            payload = {'choices': [{'message': {'content': content},
                                   'finish_reason': 'length' if case == 'null_length' else 'stop'}],
                       'usage': {'prompt_tokens': 9, 'completion_tokens': 12}}
            self.send(json.dumps(payload).encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    endpoint = 'http://127.0.0.1:'+str(server.server_port)+'/v1'
    try:
        for case in CASES:
            state['case'] = case
            task = out/'inputs'/case; task.mkdir(parents=True)
            (task/'prompt.txt').write_text(PROMPT)
            if case != 'missing_interface':
                (task/'interface.txt').write_text(INTERFACE)
            (task/'tb.sv').write_text('EVALUATOR_SENTINEL_DO_NOT_COPY')
            (task/'reference.sv').write_text('REFERENCE_SENTINEL_DO_NOT_COPY')
            before = len(requests)
            result = arm.run_arm(args.kit/'official_reference', task, out/'cases'/case,
                                 resource, endpoint, 1.5 if case == 'body_hang' else 10)
            assert len(requests) == before+1, (case, 'must make exactly one POST, no retry')
            request = requests[-1]
            assert request['case'] == case and request['path'] == '/v1/chat/completions'
            expected_user = PROMPT+('' if case == 'missing_interface' else '\n\nInterface:\n'+INTERFACE)
            assert request['payload'] == dict(model=arm.MODEL,
                messages=[dict(role='system', content=SYSTEM), dict(role='user', content=expected_user)],
                temperature=0, top_p=1, max_tokens=8192)
            assert sorted(p.name for p in (out/'cases'/case/'prompt_only').iterdir()) == (
                ['prompt.txt'] if case == 'missing_interface' else ['interface.txt', 'prompt.txt'])
            solution = out/'cases'/case/'output/solution.v'
            if case == 'body_hang':
                release.set()
                assert result['timeout'] and not result['complete'] and not result['transport_ok']
                assert result['unconfirmed_call'] and result['confirmed_model_responses'] == 0
                assert result['solve_elapsed_s'] < 4 and not result['solution_present']
            elif case in ['http_error', 'invalid_json']:
                assert result['complete'] and not result['transport_ok'] and result['transport_error']
                assert result['confirmed_model_responses'] == 0 and solution.read_text() == ''
            elif case == 'null_length':
                assert result['transport_ok'] and result['empty_content'] and result['finish'] == 'length'
                assert result['confirmed_model_responses'] == 1 and solution.read_text() == '\n'
            else:
                assert result['transport_ok'] and result['complete'] and solution.read_text() == CODE
                assert result['confirmed_model_responses'] == 1
            assert result['functional_grade'] is None and result['retry_count'] == 0
            rows.append(dict(case=case, passed=True, actual_fake_posts=1, **result))
            arm.save(out/'PROGRESS.json', dict(rows=rows, fake_posts=len(requests)))
    finally:
        release.set(); server.shutdown(); server.server_close(); thread.join(2)
        arm.save(out/'HTTP_REQUESTS.json', requests)
        arm.save(out/'HTTP_GETS.json', gets)
    assert not thread.is_alive() and len(requests) == 7 and len(rows) == 7
    assert all(row['path'] == '/v1/models' for row in gets)
    resource.check_resource(args.resource_check, args.kit)
    result = dict(schema='official_baseline_cli_preflight_v1', complete=True, passed=True,
                  cases=CASES, fake_model_posts=len(requests), real_model_calls=0, eda_calls=0,
                  original_official_files=arm.OFFICIAL, wrapper_sha256=arm.sha(arm.__file__),
                  driver_sha256=arm.sha(__file__), rows=rows, full_batch=False,
                  independent_tasks=0, paired_quality_measured=False,
                  limitations=['Synthetic local HTTP only; real27B cancellation remains unverified.',
                               'Direct original baseline trace does not record raw response or server POST receipt.',
                               'No A/P/B scheduler, natural quality, five-sample or32GB certification.'])
    arm.save(out/'RESULTS.json', result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--resource-check', type=Path, required=True)
    preflight(p.parse_args())
