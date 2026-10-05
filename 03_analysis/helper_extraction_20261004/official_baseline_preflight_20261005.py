"""Fixed zero-real-model HTTP/CLI controls for the unchanged official B arm."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading
import time

import official_baseline_arm_20261005 as arm
import official_baseline_scoring_20261005 as scoring


CODE = 'module TopModule(input a, output y); assign y = a; endmodule\n'
PROMPT = 'Implement a combinational wire from a to y.'
INTERFACE = 'module TopModule(input a, output y); endmodule\n'
SYSTEM = ('You are an expert Verilog designer. Reply with a single synthesizable '
          'SystemVerilog module named TopModule. Output only code — no prose, no '
          'markdown fences.')
CASES = ['fenced_code', 'missing_interface', 'null_length', 'http_error',
         'invalid_json', 'body_hang', 'recovery', 'wrong_function', 'invalid_syntax']


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
            if case == 'wrong_function': content = CODE.replace('y = a','y = ~a')
            if case == 'invalid_syntax': content = 'module TopModule(input a, output y); assign y = ; endmodule\n'
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
            result = arm.run_arm(args.kit/'submission', task, out/'cases'/case,
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
                expected=CODE
                if case=='wrong_function': expected=CODE.replace('y = a','y = ~a')
                if case=='invalid_syntax': expected='module TopModule(input a, output y); assign y = ; endmodule\n'
                assert result['transport_ok'] and result['complete'] and solution.read_text() == expected
                assert result['confirmed_model_responses'] == 1
            assert result['functional_grade'] is None and result['retry_count'] == 0
            assert result['recorder_ready'] and result['client_request_attempts'] == 1
            receipt=out/'cases'/case/'transport/request_0'
            assert json.loads((receipt/'request.bin').read_text()) == request['payload']
            state_record=json.loads((receipt/'STATE.json').read_text())
            assert state_record['server_received'] is None
            if case in ['body_hang','http_error']:
                assert not state_record['response_body_complete']
            else:
                assert state_record['response_body_complete']
                if case=='invalid_json': assert (receipt/'response.bin').read_bytes()==b'not-json'
                else:
                    body=json.loads((receipt/'response.bin').read_text())
                    content=body['choices'][0]['message']['content'] or ''
                    assert ('EVALUATOR_SENTINEL' not in content and 'REFERENCE_SENTINEL' not in content)
            rows.append(dict(case=case, passed=True, actual_fake_posts=1, **result))
            arm.save(out/'PROGRESS.json', dict(rows=rows, fake_posts=len(requests)))
    finally:
        release.set(); server.shutdown(); server.server_close(); thread.join(2)
        arm.save(out/'HTTP_REQUESTS.json', requests)
        arm.save(out/'HTTP_GETS.json', gets)
    assert not thread.is_alive() and len(requests) == 9 and len(rows) == 9
    assert all(row['path'] == '/v1/models' for row in gets)
    resource.check_resource(args.resource_check, args.kit)
    # Observer initialization must fail before running an altered baseline.
    bad=out/'bad_bootstrap';bad.mkdir()
    for name in arm.OFFICIAL: shutil.copyfile(args.kit/'submission'/name,bad/name)
    (bad/'baseline.py').write_text((bad/'baseline.py').read_text()+'\n# frozen tamper control\n')
    empty_receipts=bad/'transport';empty_receipts.mkdir()
    command=resource.owned_command(['/usr/bin/env','BASELINE_RECEIPTS='+str(empty_receipts),
        '/usr/bin/python3','-B',str(Path(arm.__file__).with_name('official_baseline_observed_20261005.py')),
        str(bad/'baseline.py'),str(out/'inputs/recovery'),str(bad/'output'),'rtl'],bad,bad/'bootstrap.log',5)
    arm.save(bad/'COMMAND.json',command)
    assert command['returncode']!=0 and not command['remaining_live_group']
    assert not (bad/'output').exists() and not any(empty_receipts.iterdir())
    # Evaluate constructed outputs in a separate process, with reference/TB
    # only in this evaluator directory, after baseline generation is complete.
    task=out/'evaluator_task';task.mkdir()
    (task/'prompt.txt').write_text(PROMPT);(task/'interface.txt').write_text(INTERFACE)
    (task/'ref.sv').write_text(CODE.replace('TopModule','RefModule'))
    (task/'tb.sv').write_text('''module tb;
reg a; wire y, yr;
TopModule dut(.a(a),.y(y)); RefModule refdut(.a(a),.y(yr));
integer mismatches=0; integer samples=0;
initial begin
 a=0; #5; samples=samples+1; if(y!==yr) mismatches=mismatches+1;
 a=1; #5; samples=samples+1; if(y!==yr) mismatches=mismatches+1;
 $display("Mismatches: %0d in %0d samples",mismatches,samples); $finish;
end
endmodule
''')
    arm.save(task/'task.json',dict(task_id='U13_constructed_wire',top='TopModule',
        reference_module='ref.sv',testbench='tb.sv',part='xczu3eg-sbva484-1-e',period_ns=5))
    judges=[]
    for case, level in [('recovery',3),('wrong_function',1),('invalid_syntax',0),('null_length',0)]:
        solve=out/'cases'/case; judge=out/'judges'/case
        log=out/(case+'_judge.log')
        command=resource.owned_command(['/usr/bin/python3','-B',str(Path(scoring.__file__).resolve()),
            '--kit',str(args.kit),'--solve',str(solve),'--task',str(task),'--out',str(judge),
            '--resource-check',str(args.resource_check)],out,log,360)
        arm.save(out/(case+'_judge_command.json'),command)
        assert command['returncode']==0 and not command['timeout'] and not command['remaining_live_group'],case
        bound=json.loads((judge/'BOUND_VERDICT.json').read_text())
        assert bound['verdict']['level']==level and not bound['verdict']['tool_error'],(case,bound)
        judges.append(dict(case=case,expected_level=level,actual_level=bound['verdict']['level'],
                           command_elapsed_s=command['elapsed_s'],bound_sha256=arm.sha(judge/'BOUND_VERDICT.json')))
    blocked=[]
    for case in ['http_error','invalid_json','body_hang']:
        try: scoring.eligible(out/'cases'/case,task)
        except AssertionError: blocked.append(case)
        else: raise AssertionError('Transport failure admitted to scoring: '+case)
    missing=out/'judges/missing_tool'
    command=resource.owned_command(['/usr/bin/env','PATH=/usr/bin:/bin','/usr/bin/python3','-B',
        str(Path(scoring.__file__).resolve()),'--kit',str(args.kit),'--solve',str(out/'cases/recovery'),
        '--task',str(task),'--out',str(missing),'--resource-check',str(args.resource_check)],
        out,out/'missing_tool.log',10)
    arm.save(out/'missing_tool_command.json',command)
    assert command['returncode']!=0 and not command['remaining_live_group']
    assert 'judge environment: executable unavailable on PATH' in (out/'missing_tool.log').read_text()
    assert not (missing/'verdict.json').exists() and not (missing/'BOUND_VERDICT.json').exists()
    resource.check_resource(args.resource_check,args.kit)
    result = dict(schema='official_baseline_receipt_scoring_preflight_v1', complete=True, passed=True,
                  cases=CASES, fake_model_posts=len(requests), real_model_calls=0,
                  official_judge_invocations=4,nonempty_native_judgements=3,judges=judges,
                  rejected_before_scoring=blocked,observer_initialization_failure_rejected=True,
                  missing_tool_not_graded_L0=True,
                  original_official_files=arm.OFFICIAL, wrapper_sha256=arm.sha(arm.__file__),
                  driver_sha256=arm.sha(__file__), rows=rows, full_batch=False,
                  independent_tasks=0, paired_quality_measured=False,
                  limitations=['Synthetic local HTTP only; real27B cancellation remains unverified.',
                               'Client attempt/response evidence is not proof of server execution for interrupted requests.',
                               'Original baseline files unchanged; explicit observer adds measured evidence I/O overhead.',
                               'Constructed judging only; no natural quality, full A/P/B, independent, five-sample or32GB certification.'])
    arm.save(out/'RESULTS.json', result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--resource-check', type=Path, required=True)
    preflight(p.parse_args())
