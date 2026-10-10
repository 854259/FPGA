"""AMD-only changed-scope CLI tests with synthetic admission/runtime/local HTTP.

The production worker __main__ and original owned supervisor execute. Aged
parent anchors reduce waiting in this isolated fixture; no physical300-second
run, real model cancellation, RTL grade, EDA or FIFO qualification is claimed.
"""
import ctypes,hashlib,http.server,importlib.util,json,os,sys,threading,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
assert sys.platform=='linux' and sys.dont_write_bytecode
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
manifest=read(ROOT/'SOURCE_MANIFEST.json')
assert all(sha(ROOT/n)==h for n,h in manifest.items())
import shared_budget,three_arm_queue_20261005 as queue,failure_continuation
resource=queue.official.resource_module()
requests=[]
class Fixture(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=self.rfile.read(int(self.headers['Content-Length']))
        event=dict(body_sha256=hashlib.sha256(body).hexdigest(),bytes=len(body),path=self.path,closed=False)
        requests.append(event)
        fast=self.path=='/fast'
        data=json.dumps(dict(choices=[dict(message=dict(content='module TopModule; endmodule'),finish_reason='stop')],usage={})).encode() if fast else b' '*10000
        self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers()
        try:
            if fast:self.wfile.write(data);self.wfile.flush()
            else:
                for b in data:self.wfile.write(bytes([b]));self.wfile.flush();time.sleep(.01)
        except (BrokenPipeError,ConnectionResetError):event['closed']=True
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Fixture);server.daemon_threads=True
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
reports=[]
try:
    for index,(name,age,mode,bootstrap) in enumerate([
        ('parent_clock_includes_CLI_bootstrap_then_HTTP',299.25,'continuous',.15),
        ('bootstrap_already_exhausted_zero_dispatch',301,'continuous',0),
        ('missing_parent_binding_refused',None,'continuous',0),
        ('fast_response_with_parent_clock',299,'fast',.10)]):
        if (ROOT/'PRIOR_ALL_CLI_CASES.json').exists():
            retained=read(ROOT/'PRIOR_ALL_CLI_CASES.json')['cases']
            if name in retained:
                prior=retained[name];assert prior['verified']
                reports.append(dict(case=name,passed=True,retained_original_CLI_observation=True,
                                    original_qualification_passed=False,no_repeat=True,evidence=prior))
                continue
        if index==0 and (ROOT/'PRIOR_CLI_EXPIRY.json').exists():
            prior=read(ROOT/'PRIOR_CLI_EXPIRY.json')
            assert prior['verified'] and prior['command']['returncode']==1 and not prior['command']['timeout']
            assert prior['budget']['elapsed_s']>=300 and prior['requests'][0]['dispatch_started'] and not prior['requests'][0]['response_received']
            reports.append(dict(case=name,passed=True,retained_original_CLI_observation=True,original_qualification_passed=False,
                                original_clock_scope_refusal_preserved=True,no_repeat=True,evidence=prior))
            continue
        folder=ROOT/'cases'/name;folder.mkdir(parents=True)
        solve=folder/'solve';anchor=time.monotonic();before=len(requests)
        argv=['/usr/bin/env','RTL_SOLVE_PARENT_STARTED_MONOTONIC='+format(anchor,'.17g'),
              '/usr/bin/python3','-B',str(ROOT/'fixture_cli_wrapper.py'),
              '--fixture-age',str(age) if age is not None else 'missing',
              '--fixture-bootstrap',str(bootstrap),'--fixture-url',
              'http://127.0.0.1:'+str(server.server_port)+('/fast' if mode=='fast' else '/continuous'),
              '--out',str(solve),'--kit','/workspace/team/tasks/autodl-rtl-kit/project',
              '--resource-check',str(ROOT/'synthetic_admission.json'),'--task','SyntheticParentClock','--arm','A']
        command=resource.owned_command(argv,folder,folder/'solve.log',5)
        queue.save(folder/'SOLVE_COMMAND.json',command)
        assert not command['timeout'] and command['launch_error'] is None and command['remaining_live_group']==[]
        assert command['elapsed_s']<3
        if mode=='fast':
            assert command['returncode']==0 and (solve/'worker_result.json').exists()
            entries=read(solve/'requests.json');assert len(entries)==1 and entries[0]['response_received']
            assert len(requests)-before==1 and not (solve/'SHARED_BUDGET_EXIT.json').exists()
        elif age is None:
            assert command['returncode']==1 and not solve.exists() and len(requests)==before
            assert 'Missing parent solve-start binding' in (folder/'solve.log').read_text()
        else:
            assert command['returncode']==1 and not (solve/'worker_result.json').exists()
            entries=read(solve/'requests.json');budget=read(solve/'SHARED_BUDGET_EXIT.json')
            assert budget['budget_s']==300 and budget['elapsed_s']>=300 and budget['grade'] is None and budget['actual_calls'] is None
            assert budget['worker_source_sha256']==sha(ROOT/'baseline_worker.py') and budget['budget_source_sha256']==sha(ROOT/'shared_budget.py')
            assert len(entries)==(1 if age<300 else 0) and len(requests)-before==len(entries)
            assert all(not r['response_received'] for r in entries)
            row=dict(key='new-parent-clock-'+str(index),reserved_calls=2)
            plan=dict(allow_inspected_solver_failure=True,allow_shared_budget_failure=True,kit='/workspace/team/tasks/autodl-rtl-kit/project',
                      sources=dict(root=str(ROOT),files={str(ROOT/n):sha(ROOT/n) for n in ['shared_budget.py','baseline_worker.py']}))
            plan_sha=queue.digest(plan);queue.save(folder/'STARTED.json',dict(row=row,plan_sha256=plan_sha))
            terminal=dict(complete=False,error='Solver supervision failure',actual_calls=None,unconfirmed_calls=None,
                          files={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()})
            queue.save(folder/'TERMINAL.json',terminal)
            class SyntheticAdmission:
                def check_resource(self,*a):return dict(llm_base_url='http://127.0.0.1:8000/v1',model_name='SYNTHETIC_IDLE')
                def model_idle(self,*a):return dict(model='SYNTHETIC_IDLE',health_status='ok',processing_slots=0,slot_count=1)
            original=(folder/'TERMINAL.json').read_bytes()
            # Aged clock is deliberately synthetic and is inconsistent with
            # the actual short command receipt. It must never qualify a real seal.
            try:failure_continuation.seal_failed_row(folder,row,plan,plan_sha,ROOT/'synthetic_admission.json',SyntheticAdmission(),queue.save)
            except AssertionError:assert budget['elapsed_s']>command['elapsed_s']
            else:raise AssertionError('Synthetic aged clock was admitted as a real parent command')
            assert (folder/'TERMINAL.json').read_bytes()==original
            assert not (folder/'FAILED_SEALED.json').exists()
        reports.append(dict(case=name,passed=True,production_worker_CLI_main_executed=True,
                            original_owned_supervisor_executed=True,synthetic_parent_age_s=age,bootstrap_delay_s=bootstrap,
                            actual_command_elapsed_s=command['elapsed_s'],command=command,local_fixture_HTTP_attempts=len(requests)-before,
                            actual_shared_model_calls=0,new_EDA=0))

    # Test the changed zero-request route with explicitly synthetic, internally
    # consistent supervision clocks; no actual cleanup/idle proof is inferred.
    for external in (False,True):
        folder=ROOT/'synthetic_zero_seals'/str(external);solve=folder/'solve';solve.mkdir(parents=True)
        queue.save(solve/'requests.json',[])
        budget=shared_budget.SolveBudget(300,clock=lambda:1000,parent_started=700)
        queue.save(solve/'SHARED_BUDGET_EXIT.json',budget.exit_receipt(solve/'requests.json',ROOT/'baseline_worker.py'))
        log=folder/'synthetic.log';log.write_text('Synthetic supervision receipt only; no dispatched request.')
        command=dict(timeout=external,returncode=-9 if external else 1,launch_error=None,remaining_live_group=[],
                     elapsed_s=300.1,group_signals=['SIGKILL'] if external else [],log=str(log),log_sha256=sha(log),log_bytes=log.stat().st_size)
        queue.save(folder/'SOLVE_COMMAND.json',command)
        row=dict(key='synthetic-zero-'+str(external),reserved_calls=2)
        plan=dict(allow_inspected_solver_failure=True,allow_shared_budget_failure=True,kit='/workspace/team/tasks/autodl-rtl-kit/project',
                  sources=dict(root=str(ROOT),files={str(ROOT/n):sha(ROOT/n) for n in ['shared_budget.py','baseline_worker.py']}))
        digest=queue.digest(plan);queue.save(folder/'STARTED.json',dict(row=row,plan_sha256=digest))
        terminal=dict(complete=False,error='Solver supervision failure',actual_calls=None,unconfirmed_calls=None,
                      files={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()})
        queue.save(folder/'TERMINAL.json',terminal)
        class SyntheticAdmission:
            def check_resource(self,*a):return dict(llm_base_url='http://127.0.0.1:8000/v1',model_name='SYNTHETIC_IDLE')
            def model_idle(self,*a):return dict(model='SYNTHETIC_IDLE',health_status='ok',processing_slots=0,slot_count=1)
        try:failure_continuation.seal_failed_row(folder,row,plan,digest,ROOT/'synthetic_admission.json',SyntheticAdmission(),queue.save)
        except AssertionError:assert external and not (folder/'FAILED_SEALED.json').exists()
        else:
            assert not external and failure_continuation.verify_failed_seal(folder,row,digest)==terminal
            assert not read(folder/'FAILED_SEALED.json')['score_eligible']
        reports.append(dict(case='zero_request_external_timeout_refused' if external else 'zero_request_bound_budget_exit_sealed',
                            passed=True,synthetic_command_clock_cleanup_and_idle=True,new_model_calls=0,new_EDA=0))

    # Reject malformed/future parent bindings without contacting HTTP or model.
    for raw in ['nan','inf','-1','not-a-number',str(time.monotonic()+100)]:
        os.environ[shared_budget.PARENT_STARTED_ENV]=raw
        try:shared_budget.SolveBudget(300,parent_started=shared_budget.parent_started_from_environment())
        except ValueError:pass
        else:raise AssertionError('Invalid parent binding accepted')
    reports.append(dict(case='invalid_and_future_parent_bindings_refused',passed=True,values=5))
finally:
    server.shutdown();server.server_close();thread.join(2)
assert all(sha(ROOT/n)==h for n,h in manifest.items())
result=dict(schema='parent_started_changed_scope_CLI_and_failed_seal_qualification_v1',passed=True,cases=reports,
            source_manifest=manifest,synthetic_admission_runtime_dependencies_and_model_idle=True,
            actual_worker_CLI_main=True,original_CPU_supervision=True,real_clock_remaining_budget=True,
            physical300_second_run=False,real_model_cancellation_proven=False,
            full_production_dependencies_or_queue_chain_qualified=False,
            new_shared_model_calls=0,new_EDA=0,new_FIFO=0,full_goal_complete=False)
(ROOT/'QUALIFICATION_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(passed=True,cases=len(reports),physical300_second_run=False,real_model_cancellation_proven=False)))
