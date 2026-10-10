
import ast,hashlib,json
from pathlib import Path
r=Path('/workspace/team/runs/fpga_owner/absolute_http_budget_qualification_20261010_v1')
read=lambda p:json.loads(Path(p).read_bytes());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=read(r/'SOURCE_MANIFEST.json');protected=read(r/'PROTECTED_MANIFEST.json')
assert all(sha(r/n)==h for n,h in manifest.items()) and all(sha(n)==h for n,h in protected.items())
birth=read(r/'CONTROLLER_BIRTH.json');p=Path('/proc')/str(birth['pid'])
if p.exists():
 s=(p/'stat').read_text().rsplit(')',1)[1].split();assert s[19]!=birth['starttime'] or s[0] in ('Z','X')
process=read(r/'ACTUAL300_PROCESS_RECEIPT.json');assert process['passed'] is False and process['result'] is None
receipt=process['process'];assert receipt['returncode']==1 and not receipt['timeout'] and receipt['leader_reaped'] and not receipt['remaining_group']
assert 300<=receipt['elapsed_s']<305
requests=read(r/'actual300_solve/requests.json');assert len(requests)==1
entry=requests[0];assert entry['index']==0 and entry['dispatch_started'] and not entry['response_received'] and not entry['replayed'] and entry['error']=='BudgetExpired'
body_file=r/'actual300_solve/requests/0/request.json';body=read(body_file)
assert sha(body_file)==entry['request_sha256']
runtime=r/'package/agent/runtime.py';tree=ast.parse(runtime.read_bytes())
worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='worker')
calls=[n for n in ast.walk(worker) if isinstance(n,ast.Call) and any(k.arg=='data' for k in n.keywords)]
serialized=[k.value for n in calls for k in n.keywords if k.arg=='data']
expected=ast.parse('json.dumps(body).encode()',mode='eval').body
assert sum(ast.dump(n)==ast.dump(expected) for n in serialized)==1
wire=json.dumps(body).encode();fixture=read(r/'FIXTURE_RECEIVED.json');connection=read(r/'FIXTURE_CONNECTION_RESULT.json')
assert len(wire)==fixture['request_bytes'] and hashlib.sha256(wire).hexdigest()==fixture['request_sha256']==connection['request_sha256']
assert fixture['request_sha256']!=entry['request_sha256']
assert connection['connection_closed'] and connection['sent_bytes']>5000
budget=read(r/'actual300_solve/SHARED_BUDGET_EXIT.json')
assert budget['schema']=='shared_worker_budget_expired_v1' and budget['budget_s']==300 and 300<=budget['elapsed_s']<301
assert budget['requests_sha256']==sha(r/'actual300_solve/requests.json') and budget['worker_source_sha256']==sha(r/'baseline_worker.py') and budget['budget_source_sha256']==sha(r/'shared_budget.py')
assert budget['grade'] is None and budget['actual_calls'] is None and budget['unconfirmed_calls'] is None and not budget['complete'] and not budget['score_eligible']
assert not (r/'actual300_solve/worker_result.json').exists() and not list((r/'actual300_solve').glob('compile_receipts/*'))
log=(r/'PROCESS300/stdout.bin').read_text()
assert 'Shared solve budget exhausted during HTTP' in log and 'Shared budget ended with an unconfirmed request' in log
assert "assert requests[0]['request_sha256']==observed[0]['request_sha256']" in log and log.rstrip().endswith('AssertionError')
quick=read(r/'QUICK_PROCESS_RECEIPT.json');assert quick['passed'] and len(quick['result']['cases'])==7
report=dict(schema='retained_actual300_http_expiry_metadata_audit_v1',audited=True,actual_HTTP_deadline_observed=True,
 actual_budget_exit_elapsed_s=budget['elapsed_s'],owned_wrapper_elapsed_s=receipt['elapsed_s'],
 original_wrapper_passed=False,original_wrapper_failure_preserved=True,
 failure_reason='Post-expiry qualifier compared pretty request-record SHA with compact actual-wire SHA;original runtime serialization independently AST-bound and actual wire hash matches.',
 actual_worker_run_function_proven=True,production_worker_CLI_exit_proven=False,actual_model_cancel_proven=False,
 fixture_connection_closed=True,fixture_sent_bytes=connection['sent_bytes'],fixture_request_attempts=1,
 grade_and_calls_unknown=True,source_manifest_held=True,protected_held=True,
 new_model_calls=0,new_EDA=0,new_FIFO=0,new_HTTP_fixture_calls=0,old_execution_reruns=0,
 execution_scope='Real300 clock and real local streaming HTTP;resource/model-idle admission synthetic;original failed wrapper remains failed',
 source_hashes={n:sha(r/n) for n in ['baseline_worker.py','shared_budget.py','qualify_worker300.py','package/agent/runtime.py']},
 originals={str(p.relative_to(r)):sha(p) for p in [body_file,r/'actual300_solve/requests.json',r/'actual300_solve/SHARED_BUDGET_EXIT.json',r/'FIXTURE_RECEIVED.json',r/'FIXTURE_CONNECTION_RESULT.json',r/'PROCESS300/stdout.bin',r/'ACTUAL300_PROCESS_RECEIPT.json']})
assert not (r/'ACTUAL300_METADATA_AUDIT.json').exists();(r/'ACTUAL300_METADATA_AUDIT.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
