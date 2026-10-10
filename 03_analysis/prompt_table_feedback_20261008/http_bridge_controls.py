"""AMD-only HTTP integration delta; fake model and tools, no scoring calls."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

PROMPT = ('I would like you to implement a module named TopModule with the following\n'
          'interface. All input and output ports are one bit unless otherwise specified.\n'
          '- input a\n- input b\n- output y\n\n'
          'The module should implement the Karnaugh map below.\n'
          'b\na 0 1\n0 | 0 | 1 |\n1 | 1 | 0 |\n')
GOOD = 'module TopModule(input a, input b, output y); assign y=a^b; endmodule\n'
BAD = GOOD.replace('a^b', 'a&b')


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    args.out.mkdir(exist_ok=False)
    sys.path.insert(0, str(args.package / 'agent'))
    import runtime as app
    app.bridge_runtime.verify_package()
    manifest = json.loads((args.package / 'INTEGRITY.json').read_text())
    report = dict(complete=False, passed=False, real_model_calls=0, actual_eda_commands=0,
                  cases=[], fake_model_calls=0, deployed=False, new_accuracy=False)
    save(args.out / 'INTENT.json', dict(http_requests=4, max_fake_model_posts=5,
         max_fake_tool_processes=13, child_cap_s=80, real_model_calls=0, eda_calls=0))
    tools = args.out / 'fake_tools'
    tools.mkdir()
    fake = ('#!' + sys.executable + '\n' +
            'import os,sys\nfrom pathlib import Path\n'
            'name=Path(sys.argv[0]).name\n'
            'with open(os.environ["FAKE_TOOL_LOG"],"a") as f: f.write(name+"\\n")\n'
            'print("FAKE_TOOL_ONLY",name)\n'
            'if name=="xsim":\n'
            ' bad="a&b" in Path("dut.sv").read_text()\n'
            ' if bad: print("TABLE_FIRST row=1 expected=1 observed=0")\n'
            ' print("R2_PROBE_RESULT task=TableProbe checks=8 mismatches="+str(4 if bad else 0))\n')
    for name in ('xvlog', 'xelab', 'xsim'):
        path = tools / name
        path.write_text(fake)
        path.chmod(0o700)

    class Model(BaseHTTPRequestHandler):
        replies = []
        calls = []

        def log_message(self, *a):
            pass

        def emit(self, value):
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.emit([dict(is_processing=False)] if self.path == '/slots'
                      else dict(data=[dict(id='FAKE_HTTP_ONLY')]))

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            index = len(self.calls)
            self.calls.append(body)
            assert index < len(self.replies), 'unexpected extra model request'
            self.emit(dict(choices=[dict(finish_reason='stop', message=dict(content=self.replies[index]))], usage={}))

    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.core.Handler)
    threads = []
    for item in (model, server):
        thread = threading.Thread(target=item.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    started = time.monotonic()
    try:
        with patch.dict(os.environ, LLM_BASE_URL=f'http://127.0.0.1:{model.server_port}/v1',
                        MODEL_NAME='FAKE_HTTP_ONLY', FPGACHINA_TOKEN='synthetic-local-control',
                        RTL_PROFILE='development', VIVADO_BIN=str(tools), RTL_REPAIRS='1',
                        RTL_MAX_TOKENS='8192', RTL_TEMPERATURE='0', PYTHONDONTWRITEBYTECODE='1',
                        FAKE_TOOL_LOG=str(args.out / 'fake_tools.log')):
            for name, mode, prompt, replies, probes in [
                ('table_repair', 'agent', PROMPT, [BAD, GOOD], 2),
                ('table_correct', 'agent', PROMPT, [GOOD], 1),
                ('abstention', 'agent', 'Synthetic interface-only task.', [GOOD], 0),
                ('official_baseline', 'baseline', PROMPT, [GOOD], 0)]:
                folder = args.out / name
                folder.mkdir()
                Model.calls, Model.replies = [], replies

                def capture(selected, task, work, seconds):
                    return app.bridge_runtime.run_job(selected, task, folder / 'worker', seconds)

                body = dict(task_id='same/opaque', nonce=name, mode=mode, prompt=prompt,
                            interface='', deadline_s=15)
                request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v1/solve',
                    data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                    'Authorization': 'Bearer synthetic-local-control'})
                with patch.object(app.core, 'run_job', side_effect=capture):
                    with urllib.request.urlopen(request, timeout=20) as response:
                        reply = json.load(response)
                save(folder / 'response.json', reply)
                save(folder / 'model_requests.json', Model.calls)
                report['fake_model_calls'] += len(Model.calls)
                assert reply['task_id'] == body['task_id'] and reply['solution'] == GOOD, name
                assert len(Model.calls) == len(replies), name
                found = list((folder / 'worker').glob('table_check_*/probe/result.json'))
                assert len(found) == probes, name
                if mode == 'agent':
                    skill, _ = app.core.skill_texts()
                    assert Model.calls[0]['messages'] == [dict(role='system', content=skill), dict(role='user', content=prompt)]
                if name == 'table_repair':
                    diagnostic = (folder / 'worker/table_check_0/feedback.txt').read_text()
                    assert Model.calls[1]['messages'][1]['content'] == prompt + '\nPrevious candidate:\n' + BAD + '\nCandidate diagnostics:\n' + diagnostic
                report['cases'].append(dict(name=name, passed=True, fake_posts=len(Model.calls), probes=probes))
                save(args.out / 'RESULT.json', report)
            # The HTTP fallback must use the actual scored phase-feedback path,
            # not the older bridge's point-only candidate. No old controls rerun.
            f = app.table_http_feedback
            old_root = f.base.ROOT
            with patch.object(f.table_feedback, 'check', return_value=None), \
                    patch.object(f.base, 'functional_feedback', return_value='scored-fallback') as fallback:
                assert f.feedback('synthetic', GOOD, args.out, 9) == 'scored-fallback'
                assert fallback.call_args.kwargs == dict(candidate=True)
            with patch.object(f.table_feedback, 'check', side_effect=RuntimeError('synthetic tool failure')):
                try:
                    f.feedback(PROMPT, BAD, args.out, 9)
                except RuntimeError as error:
                    assert str(error) == 'synthetic tool failure'
                else:
                    raise AssertionError('tool failure swallowed')
            assert f.base.ROOT == old_root
            assert len((args.out / 'fake_tools.log').read_text().splitlines()) == 13
            assert report['fake_model_calls'] == 5
            for name, digest in manifest['files'].items():
                assert hashlib.sha256((args.package / name).read_bytes()).hexdigest() == digest
            report.update(complete=True, passed=True, fallback_matches_scored=True,
                          failure_propagates=True, package_unchanged=True, fake_tool_processes=13)
    except BaseException as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        for item, thread in zip((server, model), reversed(threads)):
            item.shutdown()
            item.server_close()
            thread.join()
        report['elapsed_s'] = time.monotonic() - started
        save(args.out / 'RESULT.json', report)
