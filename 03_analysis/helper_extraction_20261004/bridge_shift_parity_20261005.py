"""AMD native shift bridge controls; fake replies, no model quality claim."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def prompt(width):
    return ('I would like you to implement a module named TopModule with the following interface. '
        'All input and output ports are one bit unless otherwise specified.\n'
        '- input clock\n- input fill\n- input advance\n- input stride (2 bits)\n'
        f'- input payload ({width} bits)\n- output state ({width} bits)\n'
        f'The module should implement a {width}-bit arithmetic shift register, with synchronous load. '
        'The shifter can shift both left and right, and by 1 or 8 bit positions, selected by "stride." '
        'Assume the right shift is an arithmetic right shift. Signals are defined as below: '
        f'(1) fill: Loads shift register with payload[{width-1}:0] instead of shifting. Active high. '
        '(2) advance: Chooses whether to shift. Active high. '
        '(3) stride: Chooses which direction and how much to shift. '
        "(a) 2'b00: shift left by 1 bit. (b) 2'b01: shift left by 8 bits. "
        "(c) 2'b10: shift right by 1 bit. (d) 2'b11: shift right by 8 bits. "
        '(4) state: The contents of the shifter.')


def source(width, wrong):
    right1 = 'state >> 1' if wrong else '{state['+str(width-1)+'],state['+str(width-1)+':1]}'
    right8 = 'state >> 8' if wrong else ('{8{state[7]}}' if width == 8 else
        '{{8{state['+str(width-1)+']}},state['+str(width-1)+':8]}')
    return (f'module TopModule(input clock,fill,advance,input [1:0] stride,input [{width-1}:0] payload,'
        f'output reg [{width-1}:0] state);\nalways @(posedge clock) begin\n'
        'if(fill) state <= payload; else if(advance) case(stride)\n'
        "2'b00: state <= state << 1; 2'b01: state <= state << 8;\n"
        f"2'b10: state <= {right1}; 2'b11: state <= {right8};\n"
        'endcase\nend\nendmodule\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ['owner-copy', 'paired', 'kit', 'resource-check', 'out']:
        p.add_argument('--'+name, required=True, type=Path)
    a = p.parse_args()
    assert sys.platform == 'linux'
    assert sha(a.owner_copy/'RUN_SPEC.json') == 'b98742b9694454c2dc41654a8bcb3668b7c2ee2066bb8dc85fa6009cc3e2eee3'
    frozen = json.loads((a.owner_copy/'RUN_SPEC.json').read_text())
    for name, digest in frozen['source_hashes'].items():
        assert sha(a.owner_copy/name) == digest, name
    assert sha(a.paired) == '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    rs = importlib.util.spec_from_file_location('shift_resource', a.paired)
    resource = importlib.util.module_from_spec(rs);rs.loader.exec_module(resource)
    resource.check_resource(a.resource_check, a.kit, first=True)
    sys.path.insert(0, str(a.owner_copy))
    import test_bridge
    app = test_bridge.app
    app.verify_package()
    toolroot = Path('/workspace/AMD/2026.1/Vivado/bin')
    assert all((toolroot/n).is_file() for n in ['xvlog', 'xelab', 'xsim'])
    a.out.mkdir(exist_ok=False)
    started = time.monotonic()
    report = dict(complete=False, passed=False, actual_model_requests=0,
        fake_model_requests=0, actual_native_probes=0, actual_compile_commands=0,
        actual_synthesis_commands=0, widths=[8,17,64], rows=[], independent_tasks=0,
        full_batch_complete=False, scope='Constructed shift HTTP-worker/legacy native parity only')

    class FakeShift(test_bridge.FakeModel):
        replies = []
        all_requests = []
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.requests.append(body)
            self.all_requests.append(body)
            reply = self.replies[min(len(self.requests)-1, len(self.replies)-1)]
            self.emit(dict(model='fake-model', choices=[dict(finish_reason='stop',
                message=dict(content=reply))], usage=dict(prompt_tokens=10, completion_tokens=20)))

    model = ThreadingHTTPServer(('127.0.0.1',0), FakeShift)
    agent = ThreadingHTTPServer(('127.0.0.1',0), app.core.Handler)
    mt = threading.Thread(target=model.serve_forever, daemon=True);mt.start()
    at = threading.Thread(target=agent.serve_forever, daemon=True);at.start()
    try:
        for width in report['widths']:
            text = prompt(width);contract = app.native_contract.prompt_map.parse(text)
            assert contract['status'] == 'supported' and contract['width'] == width
            good, bad = source(width,False), source(width,True)
            legacy_results = {}
            for label, code in [('good',good),('bad',bad)]:
                resource.check_resource(a.resource_check,a.kit)
                folder = a.out/f'w{width}_legacy_{label}';folder.mkdir()
                inputs = folder/'inputs';inputs.mkdir();task = inputs/'ContractProbe';task.mkdir()
                (task/'tb.sv').write_text(app.native_contract.prompt_map.render_tb(contract,'ContractProbe'))
                helper = inputs/'probe_runner.py';helper.write_bytes((a.owner_copy/'package/agent/probe_runner.py').read_bytes())
                sp = importlib.util.spec_from_file_location('legacy_shift',helper)
                legacy = importlib.util.module_from_spec(sp);sp.loader.exec_module(legacy)
                legacy.TASK_CHECKS = {'ContractProbe':contract['checks']}
                dut = inputs/'source.sv';dut.write_text(code)
                with patch.dict(os.environ,PATH=str(toolroot)+os.pathsep+os.environ['PATH']):
                    result = legacy.probe_candidate('ContractProbe',dut,folder/'probe')
                assert result['checks'] == contract['checks']
                assert result['mismatches'] == 0 if label == 'good' else result['mismatches'] > 0
                assert result['status'] == ('pass' if label == 'good' else 'fail')
                legacy_results[label] = result
                report['actual_native_probes'] += 1
            for case, replies in [('correct',[good]),('repair',[bad,good]),('persistent',[bad,bad])]:
                resource.check_resource(a.resource_check,a.kit)
                folder = a.out/f'w{width}_{case}';folder.mkdir()
                FakeShift.requests = [];FakeShift.replies = replies;FakeShift.busy = False
                def capture(mode,task,work,seconds):
                    result = app.run_job(mode,task,work,seconds)
                    shutil.copytree(work,folder/'http_worker')
                    return result
                with patch.dict(os.environ,LLM_BASE_URL=f'http://127.0.0.1:{model.server_port}/v1',
                        MODEL_NAME='fake-model',FPGACHINA_TOKEN='test-only-local',RTL_PROFILE='development',
                        VIVADO_BIN=str(toolroot),RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0'), \
                        patch.object(app.core,'run_job',side_effect=capture):
                    body = dict(task_id='opaque/../构造移位',nonce=f'{width}-{case}',mode='agent',
                                prompt=text,interface='',deadline_s=120)
                    request = urllib.request.Request(f'http://127.0.0.1:{agent.server_port}/v1/solve',
                        data=json.dumps(body).encode(),headers={'Content-Type':'application/json',
                        'Authorization':'Bearer test-only-local'})
                    with urllib.request.urlopen(request,timeout=130) as response:reply = json.load(response)
                save(folder/'http_reply.json',reply);save(folder/'fake_requests.json',FakeShift.requests)
                assert len(FakeShift.requests) == len(replies) and reply['solution'] == replies[-1]
                events = [json.loads(x) for x in reply['trace'].splitlines()]
                assert sum(e['tool']=='lint' and e['rc']==0 for e in events) == len(replies)
                for i, code in enumerate(replies):
                    check = folder/'http_worker'/f'map_check_{i}'
                    receipt = json.loads((check/'probe/result.json').read_text())
                    prior = legacy_results['good' if code==good else 'bad']
                    assert all(receipt[k]==prior[k] for k in ['checks','mismatches','status','failure_kind'])
                    assert (check/'input.sv').read_text() == code
                    for stage in receipt['stages']:
                        assert stage['returncode']==0 and not stage['timeout']
                        assert stage['session_policy']=='inherit_supervised_worker_group'
                        assert Path(stage['argv'][0]).parent == toolroot
                        assert sha(check/'probe'/Path(stage['log']).name)==stage['log_sha256']
                    if i==0 and len(replies)==2:
                        feedback = json.loads((check/'feedback.json').read_text())['text']
                        assert feedback in FakeShift.requests[1]['messages'][-1]['content']
                assert all('R2Probe' not in json.dumps(b) for b in FakeShift.requests)
                report['fake_model_requests'] += len(replies)
                report['actual_compile_commands'] += len(replies)
                report['actual_native_probes'] += len(replies)
                report['rows'].append(dict(width=width,case=case,passed=True,calls=len(replies),checks=contract['checks']))
                save(a.out/'summary.json',report)
        assert len(report['rows'])==9 and report['fake_model_requests']==15 and report['actual_native_probes']==21
        resource.check_resource(a.resource_check,a.kit)
        report.update(complete=True,passed=True)
    except BaseException as error:
        report['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        report['fake_model_requests_observed'] = len(FakeShift.all_requests)
        report['completed_native_receipts_observed'] = len(list(a.out.rglob('result.json')))
        save(a.out/'all_fake_requests.json',FakeShift.all_requests)
        report['elapsed_s']=time.monotonic()-started
        save(a.out/'summary.json',report)
        for server,thread in [(agent,at),(model,mt)]:
            server.shutdown();server.server_close();thread.join()
