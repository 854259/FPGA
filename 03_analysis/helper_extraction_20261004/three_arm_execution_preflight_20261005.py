"""AMD U14: actual pinned solvers and native judges, fixed synthetic HTTP only.

Test child bootstrap changes transport destination in memory, never source bytes.
It is not imported by production routing. Private activity rows written by the
original worker describe synthetic calls here; this run manifest is authoritative.
"""
import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
import threading
import time
import urllib.request

import three_arm_queue_20261005 as queue
import official_baseline_scoring_20261005 as scoring
from three_arm_queue_20261005 import official

CODE = 'module TopModule(input a, output y); assign y = a; endmodule\n'
BROKEN = 'module TopModule(input a, output y); assign y = ; endmodule\n'
PROMPT = 'Implement a combinational wire from a to y.'
INTERFACE = 'module TopModule(input a, output y); endmodule\n'


def synthetic_child(path):
    control = json.loads(path.read_text()); argv = control['argv'][:]
    endpoint = control['synthetic_endpoint']
    assert endpoint.startswith('http://127.0.0.1:') and not endpoint.startswith('http://127.0.0.1:8000/')
    if argv[0] == '/usr/bin/env':
        argv.pop(0)
        while '=' in argv[0]:
            key,value=argv.pop(0).split('=',1);os.environ[key]=value
    assert argv[:2] == ['/usr/bin/python3','-B']
    script = Path(argv[2]); sys.argv=argv[2:]
    sys.path.insert(0,str(script.parent))
    if script.name == 'worker.py':
        original = urllib.request.urlopen
        def redirect(request, *args, **kwargs):
            if isinstance(request,urllib.request.Request) and request.get_method() == 'POST':
                assert request.full_url == 'http://127.0.0.1:8000/v1/chat/completions'
                # Only the test transport changes the port; payload bytes are identical.
                request=urllib.request.Request(endpoint+'/chat/completions',data=request.data,
                                               headers=dict(request.header_items()),method='POST')
            return original(request,*args,**kwargs)
        urllib.request.urlopen=redirect
        try: runpy.run_path(str(script),run_name='__main__')
        finally: urllib.request.urlopen=original
    else:
        assert script.name == 'official_baseline_arm_20261005.py'
        spec=importlib.util.spec_from_file_location('baseline_synthetic_entry',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        original=module.run_arm
        def local_only(official_dir,task,out,resource,unused_endpoint,seconds=300):
            assert unused_endpoint == 'http://127.0.0.1:8000/v1'
            return original(official_dir,task,out,resource,endpoint,seconds)
        module.run_arm=local_only
        module.main()


def preflight(args):
    resource = official.resource_module()
    resource.check_resource(args.resource_check,args.kit,first=True)
    out=args.out.resolve();assert not out.exists();out.mkdir(parents=True)
    started=time.monotonic(); sources=queue.prepare_sources(out/'sources')
    queue.save(out/'SOURCE_COPY.json',sources)
    tasks=[]
    for case in ['correct','repair']:
        folder=out/'inputs'/case;folder.mkdir(parents=True)
        (folder/'prompt.txt').write_text(PROMPT);(folder/'interface.txt').write_text(INTERFACE)
        (folder/'ref.sv').write_text(CODE.replace('TopModule','RefModule'))
        (folder/'tb.sv').write_text('''module tb;
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
        (folder/'EVALUATOR_SENTINEL.txt').write_text('PRIVATE_U14_EVALUATOR_DO_NOT_SEND')
        queue.save(folder/'task.json',dict(task_id='U14_wire_'+case,top='TopModule',
            reference_module='ref.sv',testbench='tb.sv',part='xczu3eg-sbva484-1-e',period_ns=5))
        tasks.append(dict(dataset=case,task='same_name',family='constructed_wire',use='development',
            task_dir=str(folder),hashes={n:official.sha(folder/n) for n in ['prompt.txt','interface.txt']},
            evaluator_dir=str(folder),evaluator_hashes={p.name:official.sha(p) for p in folder.iterdir()}))
    plan=queue.build_plan(tasks,1,sources,Path(official.__file__).resolve(),args.kit,10,1500)
    queue.save(out/'CONTROL_PLAN.json',plan)
    requests=[]; launches=[]; state={}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused): pass
        def send(self,body,status=200):
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            assert self.path == '/v1/models'
            self.send(json.dumps({'data':[{'id':official.MODEL}]}).encode())
        def do_POST(self):
            assert self.path == '/v1/chat/completions'
            raw=self.rfile.read(int(self.headers['Content-Length']));body=json.loads(raw)
            index=state['count'];state['count']+=1
            assert state['row']['arm'] in ['A','P','B']
            assert (body['model'],body['temperature'],body['top_p'],body['max_tokens']) == (official.MODEL,0,1,8192)
            assert 'PRIVATE_U14_EVALUATOR_DO_NOT_SEND' not in raw.decode() and 'RefModule' not in raw.decode()
            content=BROKEN if state['case']=='repair' and index==0 else CODE
            response=json.dumps({'choices':[{'message':{'content':content},'finish_reason':'stop'}],
                                 'usage':{'prompt_tokens':9,'completion_tokens':12}}).encode()
            failed=state['case']=='transport_failure'
            if failed: response=b'{"error":"frozen U14 synthetic failure"}'
            requests.append(dict(case=state['case'],key=state['row']['key'],arm=state['row']['arm'],
                                 index=index,request=body,response=response.decode(),status=500 if failed else 200))
            self.send(response,500 if failed else 200)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    endpoint='http://127.0.0.1:'+str(server.server_port)+'/v1'
    original_owned=resource.owned_command;original_resource=official.resource_module
    def controlled_owned(argv,cwd,log,seconds):
        is_solver=any(str(x).endswith(('/worker.py','/official_baseline_arm_20261005.py')) for x in argv)
        if is_solver:
            launches.append(state['row']['key'])
            control=Path(cwd)/'SYNTHETIC_LAUNCH.json'
            queue.save(control,dict(argv=argv,synthetic_endpoint=endpoint,real_model_calls=0,
                bootstrap_sha256=official.sha(__file__),activity_ledger_interpretation='synthetic_only'))
            argv=['/usr/bin/python3','-B',str(Path(__file__).resolve()),'--synthetic-child',str(control)]
        return original_owned(argv,cwd,log,seconds)
    resource.owned_command=controlled_owned;official.resource_module=lambda:resource
    root=Path(sources['root'])/'queues';paired=root/'paired';controls=[]
    def execute(argv,row,folder):
        state.update(case=row['dataset'],row=row,count=0)
        receipt=queue.execute_row(plan,argv,row,folder,args.resource_check)
        receipt.update(synthetic=True,real_model_calls=0)
        return receipt
    def blocked(name,fn):
        before=len(launches)
        try:fn()
        except (AssertionError,BlockingIOError):
            assert len(launches)==before;controls.append(name)
        else:raise AssertionError('Missing rejection: '+name)
    try:
        for index,row in enumerate(plan['rows']):
            queue.advance(plan,paired,args.resource_check,execute)
            folder=paired/('row_'+str(index).zfill(6))
            receipt=json.loads((folder/'TERMINAL.json').read_text())
            expected=0 if row['dataset']=='repair' and row['arm']=='B' else 3
            assert receipt['complete'] and receipt['level']==expected,(row['dataset'],row['arm'],receipt)
            count=2 if row['dataset']=='repair' and row['arm']!='B' else 1
            assert receipt['actual_calls']==count and receipt['unconfirmed_calls']==0
            assert set(p.name for p in (folder/'prompt_only').iterdir())=={'prompt.txt','interface.txt'}
            assert set(p.name for p in (folder/'solve/prompt_only').iterdir())=={'prompt.txt','interface.txt'}
            for r in [r for r in requests if r['key']==row['key']]:
                if row['arm']=='B':
                    path=folder/'solve/transport/request_0'
                    assert json.loads((path/'request.bin').read_text())==r['request']
                    assert (path/'response.bin').read_text()==r['response']
                else:
                    path=folder/'solve/requests'/str(r['index'])
                    assert json.loads((path/'request.json').read_text())==r['request']
                    assert (path/'response.json').read_text()==r['response']
            queue.save(out/'PROGRESS.json',dict(completed_rows=index+1,fake_posts=len(requests),last_arm=row['arm']))
        assert queue.advance(plan,paired,args.resource_check,execute)['complete']
        assert len(launches)==6 and len(requests)==8
        controls.append('complete_resume_no_duplicate_dispatch')
        first=paired/'row_000000'
        blocked('wrong_arm_receipt',lambda:scoring.eligible(first/'solve',Path(tasks[0]['evaluator_dir']),'P'))
        # New wall admission includes the judge as well as the solver.
        short=copy.deepcopy(plan);short['wall_seconds']=669
        blocked('whole_row_wall_budget',lambda:queue.advance(short,root/'wall',args.resource_check,execute))
        for label,path in [('observer_hash_drift',Path(official.__file__).with_name('official_baseline_observed_20261005.py')),
                           ('evaluator_input_drift',Path(tasks[0]['evaluator_dir'])/'tb.sv'),
                           ('terminal_response_drift',first/'solve/requests/0/response.json')]:
            original=path.read_bytes();path.write_bytes(original+b'\nDRIFT')
            try:
                blocked(label,lambda:queue.advance(plan,paired,args.resource_check,execute))
                (out/(label+'.observed')).write_bytes(path.read_bytes())
            finally:path.write_bytes(original)
        # A failed actual child is retained and cannot be silently retried or L0-graded.
        failure_plan=queue.build_plan(tasks[:1],1,sources,Path(official.__file__).resolve(),args.kit,5,1500)
        def fail(argv,row,folder):
            state.update(case='transport_failure',row=row,count=0)
            return queue.execute_row(failure_plan,argv,row,folder,args.resource_check)
        queue.advance(failure_plan,root/'failure',args.resource_check,fail)
        failed=root/'failure/row_000000'
        receipt=json.loads((failed/'TERMINAL.json').read_text())
        assert not receipt['complete'] and not (failed/'judge').exists()
        blocked('failed_actual_child_never_retried_or_graded',lambda:queue.advance(failure_plan,root/'failure',args.resource_check,fail))
        assert len(launches)==7 and len(requests)==9
        resource.check_resource(args.resource_check,args.kit)
        result=dict(schema='three_arm_execution_U14_v1',complete=True,passed=True,
            actual_solver_child_invocations=7,completed_paired_rows=6,official_judgements=6,
            fake_http_posts=9,real_model_calls=0,controls=controls,
            levels=[json.loads((paired/('row_'+str(i).zfill(6))/'TERMINAL.json').read_text())['level'] for i in range(6)],
            client_attempts_completed_rows=8,conservative_reserved_calls=10,
            elapsed_s=time.monotonic()-started,full_batch=False,independent_natural_tasks=0,
            limitations=['Actual pinned solvers and Vivado judges, but synthetic HTTP, not real27B accuracy or cancellation.',
                        'Original worker activity records in this owned root describe synthetic calls, never real model usage.',
                        'No full-batch admission: independent data, audited RTLLM, budget/credits and formal32GB remain open.'])
        queue.save(out/'RESULTS.json',result);print(json.dumps(result))
    finally:
        resource.owned_command=original_owned;official.resource_module=original_resource
        server.shutdown();server.server_close();thread.join(2)
        queue.save(out/'HTTP_REQUESTS.json',requests)
        queue.save(out/'CONTROL_LAUNCHES.json',launches)
    assert not thread.is_alive()


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--synthetic-child':
        synthetic_child(Path(sys.argv[2]))
    else:
        parser=argparse.ArgumentParser()
        for name in ['kit','out','resource-check']:parser.add_argument('--'+name,type=Path,required=True)
        preflight(parser.parse_args())
