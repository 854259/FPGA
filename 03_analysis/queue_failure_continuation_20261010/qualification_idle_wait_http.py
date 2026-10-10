"""One new actual local HTTP check of the frozen three-probe idle function."""
import argparse
import hashlib
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import time
import failure_continuation as failure


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--inspection',type=Path,required=True)
    p.add_argument('--trace',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    assert sys.platform=='linux' and sys.dont_write_bytecode
    report=json.loads(args.inspection.read_bytes())
    assert hashlib.sha256(args.trace.read_bytes()).hexdigest()==report['observer_result']['observations_sha256']
    paired=Path('/workspace/team/runs/fpga_owner/temporal_shared_budget_production_20261010_v1/dependencies/paired_checkpoint.py')
    assert hashlib.sha256(paired.read_bytes()).hexdigest()=='78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    spec=importlib.util.spec_from_file_location('real_three_probe_source',paired)
    resource=importlib.util.module_from_spec(spec);spec.loader.exec_module(resource)
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            seen.append(dict(path=self.path,monotonic=time.monotonic()))
            self.send_response(200);self.send_header('Content-type','application/json');self.end_headers()
            if self.path=='/health':self.wfile.write(b'{"status":"ok"}')
            elif self.path=='/v1/models':self.wfile.write(b'{"data":[{"id":"Qwen3.6-27B-Q4_K_M"}]}')
            elif self.path=='/slots':
                self.wfile.write(b'[');self.wfile.flush()
                time.sleep(.6)
                try:self.wfile.write(b'{"is_processing":false}]')
                except (BrokenPipeError,ConnectionResetError):pass
            else:raise AssertionError('Unexpected fixture endpoint')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    args.out.mkdir(exist_ok=False)
    origin=time.monotonic()-309.8
    (args.out/'SOLVE_CLOCK.json').write_text(json.dumps(dict(schema='parent_solve_clock_v1',budget_s=300,started_monotonic=origin)))
    now=time.monotonic();error=None
    try:
        failure.idle_after_failed_solver(args.out,dict(allow_shared_budget_failure=True,solve_supervisor_s=310),resource,
          dict(llm_base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',model_name='Qwen3.6-27B-Q4_K_M'))
    except RuntimeError as exc:error=str(exc)
    elapsed=time.monotonic()-now
    server.shutdown();server.server_close();thread.join(timeout=2)
    assert not thread.is_alive()
    assert error=='Shared model did not become idle within original parent310 cleanup end'
    assert [x['path'] for x in seen]==['/health','/v1/models','/slots'] and elapsed<1
    result=dict(schema='failed_idle_wait_three_probe_local_HTTP_delta_v1',complete=True,passed=True,
        source_sha256=hashlib.sha256(Path(failure.__file__).read_bytes()).hexdigest(),
        real_frozen_resource_source_sha256=hashlib.sha256(paired.read_bytes()).hexdigest(),
        real_local_HTTP=True,parent_age_simulated=True,real_shared_model=False,
        three_sequential_probes=seen,elapsed_s=elapsed,error=error,
        scope='Actual frozen model_idle performs three real HTTP GETs on an owned local fixture. Its stalled slots body is interrupted by the new helper total remaining deadline; no shared model, resource admission or native process is exercised.',
        real_model_continuation_qualified=False,new_model_calls=0,new_EDA=0,new_FIFO=0,full_goal_complete=False)
    (args.out/'QUALIFICATION_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':
    main()
